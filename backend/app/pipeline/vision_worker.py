"""
Standalone vision worker subprocess.
Run directly by the Go server. Writes one JSON line per frame to stdout.
All errors and debug output go to stderr only.
"""
from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time

import cv2
import mediapipe as mp
import numpy as np

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

_stop = False


def _handle_sigterm(signum: int, frame: object) -> None:
    global _stop
    _stop = True


def solve_head_pose(
    landmarks: object,
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


def run_synthetic(args: argparse.Namespace) -> None:
    fake_face = [[0.5, 0.5, 0.0]] * 478
    fake_pose = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
    frame_interval = 1.0 / args.fps
    start = time.time()
    last = 0.0

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


def run_camera(args: argparse.Namespace) -> None:
    classifier = EmotionClassifier()
    mp_face_mesh = mp.solutions.face_mesh
    mp_hands = mp.solutions.hands

    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    hands = mp_hands.Hands(
        max_num_hands=2,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    if args.preview:
        mp_drawing = mp.solutions.drawing_utils
        mp_drawing_styles = mp.solutions.drawing_styles

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
            rgb.flags.writeable = False

            face_results = face_mesh.process(rgb)
            hand_results = hands.process(rgb)

            rgb.flags.writeable = True

            face_landmarks_list: list[list[float]] = []
            head_pose: dict[str, float] = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
            emotion = "neutral"
            emotion_confidence = 0.0
            if face_results.multi_face_landmarks:
                lm = face_results.multi_face_landmarks[0]
                face_landmarks_list = [
                    [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
                    for p in lm.landmark
                ]
                head_pose = solve_head_pose(lm.landmark, args.width, args.height)
                emotion, emotion_confidence = classifier.classify(lm.landmark)

            hand_landmarks_list: list[list[float]] = []
            if hand_results.multi_hand_landmarks:
                for hand_lm in hand_results.multi_hand_landmarks:
                    for p in hand_lm.landmark:
                        hand_landmarks_list.append(
                            [round(p.x, 4), round(p.y, 4), round(p.z, 4)]
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

            if args.preview:
                if face_results.multi_face_landmarks:
                    for face_lm in face_results.multi_face_landmarks:
                        mp_drawing.draw_landmarks(
                            image=frame,
                            landmark_list=face_lm,
                            connections=mp_face_mesh.FACEMESH_TESSELATION,
                            landmark_drawing_spec=None,
                            connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_tesselation_style(),
                        )
                if hand_results.multi_hand_landmarks:
                    for hand_lm in hand_results.multi_hand_landmarks:
                        mp_drawing.draw_landmarks(
                            frame,
                            hand_lm,
                            mp_hands.HAND_CONNECTIONS,
                        )
                cv2.imshow("ARIA Vision Preview", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    finally:
        cap.release()
        face_mesh.close()
        hands.close()
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
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if args.synthetic:
        run_synthetic(args)
    else:
        run_camera(args)


if __name__ == "__main__":
    main()
