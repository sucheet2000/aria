"""
Developer preview tool for the ARIA vision pipeline.
Displays camera feed with face mesh and hand landmark overlays.
Press q to quit.
Does not print JSON to stdout. Prints human-readable status to terminal.
"""
from __future__ import annotations

import argparse
import sys
import time

import cv2
import mediapipe as mp
import numpy as np

FACE_3D_MODEL = np.array(
    [
        [0.0, 0.0, 0.0],
        [0.0, -330.0, -65.0],
        [-225.0, 170.0, -135.0],
        [225.0, 170.0, -135.0],
        [-150.0, -150.0, -125.0],
        [150.0, -150.0, -125.0],
    ],
    dtype=np.float64,
)

FACE_LANDMARK_INDICES = [4, 152, 263, 33, 287, 57]


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


def main() -> None:
    parser = argparse.ArgumentParser(description="ARIA vision developer preview")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=15)
    args = parser.parse_args()

    mp_face_mesh = mp.solutions.face_mesh
    mp_hands_mod = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles

    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    hands = mp_hands_mod.Hands(
        max_num_hands=2,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    cap = cv2.VideoCapture(args.camera)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_FPS, 30)

    print(f"Starting preview on camera {args.camera} at {args.fps} fps. Press q to quit.", file=sys.stderr)

    frame_interval = 1.0 / args.fps
    last_frame_time = 0.0
    fps_counter = 0
    fps_start = time.time()
    display_fps = 0.0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("camera read failed", file=sys.stderr)
                break

            now = time.time()
            if now - last_frame_time < frame_interval:
                continue
            last_frame_time = now

            fps_counter += 1
            elapsed = now - fps_start
            if elapsed >= 1.0:
                display_fps = fps_counter / elapsed
                fps_counter = 0
                fps_start = now

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False

            face_results = face_mesh.process(rgb)
            hand_results = hands.process(rgb)

            rgb.flags.writeable = True

            head_pose: dict[str, float] = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
            face_detected = False

            if face_results.multi_face_landmarks:
                face_detected = True
                for face_lm in face_results.multi_face_landmarks:
                    mp_drawing.draw_landmarks(
                        image=frame,
                        landmark_list=face_lm,
                        connections=mp_face_mesh.FACEMESH_TESSELATION,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_tesselation_style(),
                    )
                    mp_drawing.draw_landmarks(
                        image=frame,
                        landmark_list=face_lm,
                        connections=mp_face_mesh.FACEMESH_CONTOURS,
                        landmark_drawing_spec=None,
                        connection_drawing_spec=mp_drawing_styles.get_default_face_mesh_contours_style(),
                    )
                head_pose = solve_head_pose(
                    face_results.multi_face_landmarks[0].landmark,
                    args.width,
                    args.height,
                )

            if hand_results.multi_hand_landmarks:
                for hand_lm in hand_results.multi_hand_landmarks:
                    mp_drawing.draw_landmarks(
                        frame,
                        hand_lm,
                        mp_hands_mod.HAND_CONNECTIONS,
                    )

            overlay_color = (0, 255, 0) if face_detected else (0, 0, 255)
            cv2.putText(
                frame,
                f"FPS: {display_fps:.1f}",
                (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                overlay_color,
                2,
            )
            cv2.putText(
                frame,
                f"emotion: neutral",
                (10, 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                overlay_color,
                2,
            )
            cv2.putText(
                frame,
                f"pitch: {head_pose['pitch']:.1f}  yaw: {head_pose['yaw']:.1f}  roll: {head_pose['roll']:.1f}",
                (10, 90),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                overlay_color,
                2,
            )

            cv2.imshow("ARIA Vision Preview", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                print("quit requested", file=sys.stderr)
                break
    finally:
        cap.release()
        face_mesh.close()
        hands.close()
        cv2.destroyAllWindows()
        print("preview stopped", file=sys.stderr)


if __name__ == "__main__":
    main()
