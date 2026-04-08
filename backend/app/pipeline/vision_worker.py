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
from app.pipeline.gesture_classifier import (
    GestureClassifier as RuleGestureClassifier,
    HAND_GESTURE_NONE,
    HAND_GESTURE_THUMB_UP,
    HAND_GESTURE_OPEN_PALM,
    HAND_GESTURE_PINCH,
    HAND_GESTURE_POINT,
    HAND_GESTURE_UNSPECIFIED,
)

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
_active_session_id: str = ""
_nats_client = None  # set in run_camera/run_synthetic when --nats flag is active


def _watch_stdin() -> None:
    """Background thread: read JSON commands from stdin and update module state."""
    global _active_session_id
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
                if cmd.get("type") == "active_session":
                    _active_session_id = cmd.get("session_id", "")
            except json.JSONDecodeError:
                pass
    except Exception:
        pass


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


def _start_nats_publisher(nats_url: str) -> NatsPublisher | None:  # type: ignore[name-defined]  # noqa: F821
    """Return an async NATS publisher wrapper, or None on import error."""
    try:
        import asyncio
        import threading

        import nats as nats_lib

        class NatsPublisher:
            def __init__(self) -> None:
                self._loop = asyncio.new_event_loop()
                self._nc = None
                self._ready = threading.Event()
                t = threading.Thread(target=self._run_loop, daemon=True)
                t.start()
                self._ready.wait(timeout=5.0)

            def _run_loop(self) -> None:
                asyncio.set_event_loop(self._loop)
                self._loop.run_until_complete(self._connect())
                self._loop.run_forever()

            async def _connect(self) -> None:
                backoff = 1.0
                while True:
                    try:
                        self._nc = await nats_lib.connect(nats_url)  # type: ignore[assignment]
                        print(f"NATS publisher connected to {nats_url}", file=sys.stderr, flush=True)
                        self._ready.set()
                        return
                    except Exception as exc:
                        print(f"NATS connect failed, retrying in {backoff}s: {exc}", file=sys.stderr, flush=True)
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 30.0)

            def publish(self, subject: str, data: bytes) -> None:
                if self._nc is None:
                    return
                asyncio.run_coroutine_threadsafe(
                    self._nc.publish(subject, data), self._loop
                )

        return NatsPublisher()
    except ImportError as exc:
        print(f"nats-py not available, NATS publish disabled: {exc}", file=sys.stderr, flush=True)
        return None


def _start_cognition_client(session_id: str = "default") -> queue.Queue | None:  # type: ignore[name-defined]  # noqa: F821
    """Start a background CognitionService gRPC client on port 50052.

    Returns the interrupt queue so the caller can enqueue CognitionRequests,
    or None if grpcio is unavailable (shouldn't happen — already installed).
    The background thread is daemonized and dies with the process.
    """
    import queue as _queue
    import threading

    import grpc as _grpc
    from perception.v1 import perception_pb2_grpc as _pb2_grpc

    interrupt_queue: _queue.Queue = _queue.Queue(maxsize=32)

    def _request_gen(q: _queue.Queue):
        while True:
            req = q.get()
            if req is None:
                return
            yield req

    def _run() -> None:
        backoff = 1.0
        while True:
            try:
                channel = _grpc.insecure_channel("127.0.0.1:50052")
                stub = _pb2_grpc.CognitionServiceStub(channel)
                print("cognition interrupt client connected", file=sys.stderr, flush=True)
                backoff = 1.0
                list(stub.StreamCognition(_request_gen(interrupt_queue)))
            except Exception as exc:
                print(
                    f"cognition interrupt stream disconnected, retrying in {backoff}s: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    threading.Thread(target=_run, daemon=True).start()
    return interrupt_queue


def run_synthetic(args: argparse.Namespace) -> None:
    import threading
    threading.Thread(target=_watch_stdin, daemon=True).start()

    fake_face = [[0.5, 0.5, 0.0]] * 478
    fake_pose = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
    frame_interval = 1.0 / args.fps
    start = time.time()
    last = 0.0

    _grpc_servicer = None
    _interrupt_queue = None
    _nats_pub = None

    if args.grpc:
        import threading

        from perception.v1 import perception_pb2

        from app.pipeline.vision_grpc_server import PerceptionServicer, serve
        _grpc_servicer = PerceptionServicer()
        _grpc_server = serve(_grpc_servicer)
        threading.Thread(target=_grpc_server.wait_for_termination, daemon=True).start()
        _interrupt_queue = _start_cognition_client()

    if args.nats:
        from perception.v1 import perception_pb2
        _nats_pub = _start_nats_publisher(args.nats_url)

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

        if _nats_pub is not None:
            frame = perception_pb2.PerceptionFrame(
                timestamp_us=int(now * 1_000_000),
                session_id=_active_session_id or "local",
            )
            _nats_pub.publish("aria.perception.frames", frame.SerializeToString())


def run_camera(args: argparse.Namespace) -> None:
    import threading
    threading.Thread(target=_watch_stdin, daemon=True).start()

    face_model_path = "models/face_landmarker.task"
    hand_model_path = "models/hand_landmarker.task"
    _ensure_model(_FACE_MODEL_URL, face_model_path)
    _ensure_model(_HAND_MODEL_URL, hand_model_path)

    _grpc_servicer = None
    _interrupt_queue = None
    _nats_pub = None

    if args.grpc:
        import threading

        from perception.v1 import perception_pb2

        from app.pipeline.vision_grpc_server import PerceptionServicer, serve
        _grpc_servicer = PerceptionServicer()
        _grpc_server = serve(_grpc_servicer)
        threading.Thread(target=_grpc_server.wait_for_termination, daemon=True).start()
        _interrupt_queue = _start_cognition_client()

    if args.nats:
        from perception.v1 import perception_pb2
        _nats_pub = _start_nats_publisher(args.nats_url)

    face_exit_detector = FaceExitDetector()
    classifier = EmotionClassifier()
    gesture_clf = RuleGestureClassifier()
    _last_gesture_type: int = HAND_GESTURE_UNSPECIFIED

    # Week 4 ANE note: MediaPipe 0.10+ automatically activates the CoreML delegate
    # on Apple Silicon when using mp_tasks.BaseOptions with a .task file (not .tflite).
    # No explicit CoreML configuration is required — the runtime selects Metal/ANE
    # acceleration transparently. Confirmed active: face_landmarker.task and
    # hand_landmarker.task both use the CoreML path on M1 Pro.
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
            gesture_name: str = "none"
            gesture_confidence: float = 0.0
            pointing_vector: list[float] | None = None

            if hand_result.hand_landmarks:
                for hand_lm in hand_result.hand_landmarks:
                    for p in hand_lm:
                        hand_landmarks_list.append(
                            [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
                        )

                # Classify gesture from first detected hand
                first_hand = [
                    [p.x, p.y, p.z] for p in hand_result.hand_landmarks[0]
                ]
                g_result = gesture_clf.classify(first_hand)
                gesture_confidence = g_result.confidence

                _GESTURE_NAMES = {
                    HAND_GESTURE_UNSPECIFIED: "none",
                    HAND_GESTURE_NONE:        "none",
                    HAND_GESTURE_THUMB_UP:    "confirm",
                    HAND_GESTURE_OPEN_PALM:   "stop",
                    HAND_GESTURE_PINCH:       "cancel",
                    HAND_GESTURE_POINT:       "point",
                }
                gesture_name = _GESTURE_NAMES.get(g_result.gesture_type, "none")

                if g_result.gesture_type != _last_gesture_type:
                    _last_gesture_type = g_result.gesture_type
                    if g_result.gesture_type != HAND_GESTURE_UNSPECIFIED:
                        print(
                            f"gesture change: {gesture_name} "
                            f"(conf={gesture_confidence:.2f})",
                            file=sys.stderr,
                            flush=True,
                        )

                if g_result.gesture_type == HAND_GESTURE_POINT and g_result.pointing_vector:
                    pointing_vector = list(g_result.pointing_vector)

            if _interrupt_queue is not None and _active_session_id:
                face_detected = bool(face_result.face_landmarks)
                if face_exit_detector.update(face_detected, now):
                    import queue as _queue

                    from perception.v1 import perception_pb2 as _pb2
                    try:
                        _interrupt_queue.put_nowait(
                            _pb2.CognitionRequest(
                                session_id=_active_session_id,
                                interrupt_signal=True,
                            )
                        )
                    except _queue.Full:
                        print("interrupt queue full, dropping signal", file=sys.stderr, flush=True)

            state: dict = {
                "face_landmarks": face_landmarks_list,
                "emotion": emotion,
                "emotion_confidence": round(emotion_confidence, 3),
                "head_pose": head_pose,
                "hand_landmarks": hand_landmarks_list,
                "gesture": gesture_name,
                "gesture_confidence": round(gesture_confidence, 3),
                "timestamp": round(now, 3),
            }
            if pointing_vector is not None:
                state["pointing_vector"] = pointing_vector
            print(json.dumps(state), flush=True)

            _perception_frame = None
            if _grpc_servicer is not None or _nats_pub is not None:
                hands = []
                if hand_result.hand_landmarks:
                    for hand_lm in hand_result.hand_landmarks:
                        hands.append(perception_pb2.HandData(
                            landmarks=[
                                perception_pb2.Point3D(
                                    x=p.x,
                                    y=p.y,
                                    z=p.z,
                                    depth_mm=int(abs(p.z) * 1000),  # TurboQuant (Week 9)
                                )
                                for p in hand_lm
                            ]
                        ))
                _perception_frame = perception_pb2.PerceptionFrame(
                    hands=hands,
                    timestamp_us=int(now * 1_000_000),
                    session_id=_active_session_id or "local",
                )

            if _grpc_servicer is not None and _perception_frame is not None:
                _grpc_servicer.push_frame(_perception_frame)

            if _nats_pub is not None and _perception_frame is not None:
                _nats_pub.publish("aria.perception.frames", _perception_frame.SerializeToString())

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
    parser.add_argument("--nats", action="store_true", default=False,
        help="Publish PerceptionFrames to NATS subject (aria.perception.frames)")
    parser.add_argument("--nats-url", dest="nats_url", default="nats://127.0.0.1:4222",
        help="NATS server URL (default: nats://127.0.0.1:4222)")
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if args.synthetic:
        run_synthetic(args)
    else:
        run_camera(args)


if __name__ == "__main__":
    main()
