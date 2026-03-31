"""
Standalone vision worker subprocess.
Run directly by the Go server. Writes one JSON line per frame to stdout.
All errors and debug output go to stderr only.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import urllib.request

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision as mp_vision

from app.pipeline.emotion import EmotionClassifier

# 6-point 3D face model in mm (nose tip, chin, eye corners, mouth corners)
FACE_3D_MODEL = np.array(
    [
        [0.0, 0.0, 0.0],          # nose tip
        [0.0, -330.0, -65.0],     # chin
        [-225.0, 170.0, -135.0],  # left eye corner
        [225.0, 170.0, -135.0],   # right eye corner
        [-150.0, -150.0, -125.0], # left mouth corner
        [150.0, -150.0, -125.0],  # right mouth corner
    ],
    dtype=np.float64,
)

# MediaPipe landmark indices for the 6 model points above
FACE_LANDMARK_INDICES = [4, 152, 263, 33, 287, 57]

_FACE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
    "face_landmarker/float16/1/face_landmarker.task"
)
_HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)

_stop = False


class FaceExitDetector:
    """Pure state machine for detecting when a user exits the camera frame.

    Extracted from the frame loop so it can be unit-tested without real gRPC.
    Rules:
    - After first face detection, a 0.5s absence triggers interrupt_needed=True.
    - Once triggered, no further trigger until face reappears and disappears again.
    """

    def __init__(self, absence_threshold: float = 0.5) -> None:
        self._threshold = absence_threshold
        self._last_face_time: float = time.time()
        self._face_was_detected: bool = False
        self._interrupt_sent: bool = False

    def update(self, face_detected: bool, now: float) -> bool:
        """Update state with the current frame's face detection result.

        Returns True exactly once per exit event (when the absence threshold
        is crossed). Returns False in all other cases.
        """
        if face_detected:
            self._last_face_time = now
            self._face_was_detected = True
            self._interrupt_sent = False
            return False

        if self._face_was_detected and not self._interrupt_sent:
            if now - self._last_face_time >= self._threshold:
                self._interrupt_sent = True
                return True

        return False


def _handle_sigterm(signum: int, frame: object) -> None:
    global _stop
    _stop = True


def _ensure_model(url: str, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        print(f"Downloading model to {path} ...", file=sys.stderr)
        urllib.request.urlretrieve(url, path)
        print(f"Downloaded {path}", file=sys.stderr)


def solve_head_pose(
    landmarks: list,
    frame_w: int,
    frame_h: int,
) -> dict[str, float]:
    face_2d = np.array(
        [
            [landmarks[idx].x * frame_w, landmarks[idx].y * frame_h]
            for idx in FACE_LANDMARK_INDICES
        ],
        dtype=np.float64,
    )

    focal_length = float(frame_w)
    camera_matrix = np.array(
        [
            [focal_length, 0.0, frame_w / 2.0],
            [0.0, focal_length, frame_h / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    dist_coeffs = np.zeros((4, 1), dtype=np.float64)

    success, rvec, _tvec = cv2.solvePnP(
        FACE_3D_MODEL,
        face_2d,
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        return {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}

    rmat, _ = cv2.Rodrigues(rvec)
    angles, _, _, _, _, _ = cv2.RQDecomp3x3(rmat)

    return {
        "pitch": round(float(angles[0]), 2),
        "yaw": round(float(angles[1]), 2),
        "roll": round(float(angles[2]), 2),
    }


def _start_cognition_client(session_id: str = "default") -> "queue.Queue | None":
    """Start a background CognitionService gRPC client on port 50052.

    Returns the interrupt queue so the caller can enqueue CognitionRequests,
    or None if grpcio is unavailable (shouldn't happen — already installed).
    The background thread is daemonized and dies with the process.
    """
    import queue as _queue
    import threading

    import grpc as _grpc

    from perception.v1 import perception_pb2 as _pb2
    from perception.v1 import perception_pb2_grpc as _pb2_grpc

    interrupt_queue: _queue.Queue = _queue.Queue()

    def _request_gen(q: "_queue.Queue"):
        while True:
            req = q.get()
            if req is None:
                return
            yield req

    def _run() -> None:
        channel = _grpc.insecure_channel("localhost:50052")
        stub = _pb2_grpc.CognitionServiceStub(channel)
        try:
            list(stub.StreamCognition(_request_gen(interrupt_queue)))
        except Exception:
            pass

    threading.Thread(target=_run, daemon=True).start()
    return interrupt_queue


def run_synthetic(args: argparse.Namespace) -> None:
    fake_face = [[0.5, 0.5, 0.0]] * 478
    fake_pose = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
    frame_interval = 1.0 / args.fps
    start = time.time()
    last = 0.0

    _grpc_servicer = None
    _interrupt_queue = None
    if args.grpc:
        import threading
        from app.pipeline.vision_grpc_server import PerceptionServicer, serve
        from perception.v1 import perception_pb2
        _grpc_servicer = PerceptionServicer()
        _grpc_server = serve(_grpc_servicer)
        threading.Thread(target=_grpc_server.wait_for_termination, daemon=True).start()
        _interrupt_queue = _start_cognition_client()

    while True:
        if _stop:
            break
        now = time.time()
        if args.duration > 0 and (now - start) >= args.duration:
            break
        if now - last < frame_interval:
            time.sleep(0.001)
            continue
        last = now

        state = {
            "face_landmarks": fake_face,
            "emotion": "neutral",
            "emotion_confidence": 1.0,
            "head_pose": fake_pose,
            "hand_landmarks": [],
            "timestamp": round(now, 3),
        }
        print(json.dumps(state), flush=True)

        if _grpc_servicer is not None:
            frame = perception_pb2.PerceptionFrame(
                timestamp_us=int(now * 1_000_000),
                session_id="local",
            )
            _grpc_servicer.push_frame(frame)


def run_camera(args: argparse.Namespace) -> None:
    face_model_path = "models/face_landmarker.task"
    hand_model_path = "models/hand_landmarker.task"
    _ensure_model(_FACE_MODEL_URL, face_model_path)
    _ensure_model(_HAND_MODEL_URL, hand_model_path)

    _grpc_servicer = None
    _interrupt_queue = None
    if args.grpc:
        import threading
        from app.pipeline.vision_grpc_server import PerceptionServicer, serve
        from perception.v1 import perception_pb2
        _grpc_servicer = PerceptionServicer()
        _grpc_server = serve(_grpc_servicer)
        threading.Thread(target=_grpc_server.wait_for_termination, daemon=True).start()
        _interrupt_queue = _start_cognition_client()

    face_exit_detector = FaceExitDetector()
    classifier = EmotionClassifier()

    face_options = mp_vision.FaceLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=face_model_path),
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    face_landmarker = mp_vision.FaceLandmarker.create_from_options(face_options)

    hand_options = mp_vision.HandLandmarkerOptions(
        base_options=mp_tasks.BaseOptions(model_asset_path=hand_model_path),
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    hand_landmarker = mp_vision.HandLandmarker.create_from_options(hand_options)

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)

    frame_interval = 1.0 / args.fps
    last_frame_time = 0.0

    try:
        while not _stop:
            ret, frame = cap.read()
            if not ret:
                print("camera read failed", file=sys.stderr)
                break

            now = time.time()
            if now - last_frame_time < frame_interval:
                continue
            last_frame_time = now

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            face_result = face_landmarker.detect(mp_image)
            hand_result = hand_landmarker.detect(mp_image)

            face_landmarks_list: list[list[float]] = []
            head_pose: dict[str, float] = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
            emotion = "neutral"
            emotion_confidence = 0.0

            if face_result.face_landmarks:
                lm = face_result.face_landmarks[0]
                face_landmarks_list = [
                    [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
                    for p in lm
                ]
                head_pose = solve_head_pose(lm, args.width, args.height)
                emotion, emotion_confidence = classifier.classify(lm)

            hand_landmarks_list: list[list[float]] = []
            if hand_result.hand_landmarks:
                for hand_lm in hand_result.hand_landmarks:
                    for p in hand_lm:
                        hand_landmarks_list.append(
                            [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
                        )

            if _interrupt_queue is not None:
                face_detected = bool(face_result.face_landmarks)
                if face_exit_detector.update(face_detected, now):
                    from perception.v1 import perception_pb2 as _pb2
                    _interrupt_queue.put(
                        _pb2.CognitionRequest(
                            session_id="default",
                            interrupt_signal=True,
                        )
                    )

            state = {
                "face_landmarks": face_landmarks_list,
                "emotion": emotion,
                "emotion_confidence": round(emotion_confidence, 3),
                "head_pose": head_pose,
                "hand_landmarks": hand_landmarks_list,
                "timestamp": round(now, 3),
            }
            print(json.dumps(state), flush=True)

            if _grpc_servicer is not None:
                hands = []
                if hand_result.hand_landmarks:
                    for hand_lm in hand_result.hand_landmarks:
                        hands.append(perception_pb2.HandData(
                            landmarks=[
                                perception_pb2.Point3D(x=p.x, y=p.y, z=p.z)
                                for p in hand_lm
                            ]
                        ))
                frame = perception_pb2.PerceptionFrame(
                    hands=hands,
                    timestamp_us=int(now * 1_000_000),
                    session_id="local",
                )
                _grpc_servicer.push_frame(frame)

            if args.preview:
                cv2.imshow("ARIA Vision Preview", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        cap.release()
        face_landmarker.close()
        hand_landmarker.close()
        if args.preview:
            cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(description="ARIA vision worker")
    parser.add_argument("--preview", action="store_true", default=False)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=15)
    parser.add_argument("--synthetic", action="store_true", default=False)
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument("--grpc", action="store_true", default=False,
        help="Serve frames via gRPC instead of stdout JSON")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if args.synthetic:
        run_synthetic(args)
    else:
        run_camera(args)


if __name__ == "__main__":
    main()
