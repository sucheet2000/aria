from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Protocol


class LandmarkPoint(Protocol):
    x: float
    y: float
    z: float


@dataclass
class ActionUnits:
    brow_raise: float
    brow_lower: float
    smile: float
    lip_depress: float
    jaw_drop: float
    lip_stretch: float
    cheek_raise: float


def _dist(a: LandmarkPoint, b: LandmarkPoint) -> float:
    dx = a.x - b.x
    dy = a.y - b.y
    return math.sqrt(dx * dx + dy * dy)


def _face_height(landmarks: list) -> float:
    forehead = landmarks[10]
    chin = landmarks[152]
    return _dist(forehead, chin)


def compute_action_units(landmarks: list) -> ActionUnits:
    fh = _face_height(landmarks)
    if fh < 1e-6:
        return ActionUnits(
            brow_raise=0.0,
            brow_lower=0.0,
            smile=0.0,
            lip_depress=0.0,
            jaw_drop=0.0,
            lip_stretch=0.0,
            cheek_raise=0.0,
        )

    # brow_raise: average Y of upper brow landmarks relative to eye Y
    # In MediaPipe coordinates Y=0 is top, Y=1 is bottom.
    # Brows are above eyes (smaller Y). Raised brows are even higher (even smaller Y).
    brow_upper_indices = [70, 63, 105, 66, 107, 336, 296, 334, 293, 300]
    eye_indices = [159, 386]
    brow_upper_y = sum(landmarks[i].y for i in brow_upper_indices) / len(brow_upper_indices)
    eye_y = sum(landmarks[i].y for i in eye_indices) / len(eye_indices)
    # eye_y - brow_upper_y = gap (positive because brows above eyes)
    brow_eye_gap = (eye_y - brow_upper_y) / fh
    # typical range 0.05 to 0.15; larger gap = more raised
    brow_raise = max(0.0, min(1.0, (brow_eye_gap - 0.05) / 0.10))

    # brow_lower: how close the lower brow edge is to the eyes
    brow_lower_indices = [46, 53, 52, 65, 276, 283, 282, 295]
    brow_lower_y = sum(landmarks[i].y for i in brow_lower_indices) / len(brow_lower_indices)
    # gap between lower brow edge and eye center
    lower_gap = (eye_y - brow_lower_y) / fh
    # small gap = furrowed brow = high brow_lower score
    # typical range 0.02 to 0.10; smaller gap = more furrowed
    brow_lower = max(0.0, min(1.0, 1.0 - lower_gap / 0.08))

    # smile: horizontal width of mouth corners relative to face height
    left_corner = landmarks[61]
    right_corner = landmarks[291]
    mouth_width = abs(right_corner.x - left_corner.x)
    mouth_width_norm = mouth_width / fh
    # baseline ~0.3 of face height; wider = bigger smile
    smile = max(0.0, min(1.0, (mouth_width_norm - 0.3) / 0.12))

    # lip_depress: Y of mouth corners relative to upper lip center (13)
    # If corners are below center (larger Y), lips are depressed
    upper_lip_center = landmarks[13]
    corner_y_avg = (left_corner.y + right_corner.y) / 2.0
    lip_dep_diff = (corner_y_avg - upper_lip_center.y) / fh
    lip_depress = max(0.0, min(1.0, lip_dep_diff / 0.04))

    # jaw_drop: gap between upper lip top (13) and lower lip bottom (14)
    lower_lip_bottom = landmarks[14]
    mouth_open = (lower_lip_bottom.y - upper_lip_center.y) / fh
    jaw_drop = max(0.0, min(1.0, mouth_open / 0.08))

    # lip_stretch: wide thin mouth (fear)
    mouth_height_raw = abs(lower_lip_bottom.y - upper_lip_center.y)
    ratio = mouth_width / (mouth_height_raw + 1e-6)
    lip_stretch = max(0.0, min(1.0, (ratio - 2.0) / 8.0))

    # cheek_raise: cheek landmarks relative to mouth corners
    cheek_y = (landmarks[116].y + landmarks[345].y) / 2.0
    cheek_diff = (corner_y_avg - cheek_y) / fh
    cheek_raise = max(0.0, min(1.0, cheek_diff / 0.15))

    return ActionUnits(
        brow_raise=brow_raise,
        brow_lower=brow_lower,
        smile=smile,
        lip_depress=lip_depress,
        jaw_drop=jaw_drop,
        lip_stretch=lip_stretch,
        cheek_raise=cheek_raise,
    )


class EmotionClassifier:
    EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"]

    def __init__(self) -> None:
        self._history: deque[str] = deque(maxlen=5)

    def classify(self, landmarks: list) -> tuple[str, float]:
        au = compute_action_units(landmarks)

        scores: dict[str, float] = {}

        scores["happy"] = au.smile * 0.5 + au.cheek_raise * 0.3 + (1.0 - au.lip_depress) * 0.2

        scores["sad"] = au.lip_depress * 0.5 + au.brow_lower * 0.3 + (1.0 - au.smile) * 0.2

        scores["angry"] = au.brow_lower * 0.6 + (1.0 - au.smile) * 0.2 + au.lip_depress * 0.2

        scores["surprised"] = (
            au.brow_raise * 0.4
            + au.jaw_drop * 0.4
            + (1.0 - au.brow_lower) * 0.2
        )

        scores["fearful"] = (
            au.brow_raise * 0.3
            + au.lip_stretch * 0.4
            + au.jaw_drop * 0.2
            + (1.0 - au.smile) * 0.1
        )

        scores["disgusted"] = (
            au.lip_depress * 0.3
            + au.brow_lower * 0.3
            + (1.0 - au.smile) * 0.2
            + au.cheek_raise * 0.2
        )

        thresholds: dict[str, float] = {
            "happy": 0.45,
            "sad": 0.40,
            "angry": 0.45,
            "surprised": 0.40,
            "fearful": 0.38,
            "disgusted": 0.38,
        }

        # disambiguate disgusted vs angry: require brow_lower > 0.6 for angry
        if scores["angry"] > thresholds["angry"] and au.brow_lower <= 0.6:
            scores["angry"] = 0.0

        best_emotion = max(scores, key=lambda e: scores[e])
        best_score = scores[best_emotion]

        if best_score < thresholds[best_emotion]:
            raw_emotion = "neutral"
            raw_confidence = 1.0 - best_score
        else:
            raw_emotion = best_emotion
            raw_confidence = best_score

        self._history.append(raw_emotion)
        smoothed = max(set(self._history), key=lambda e: list(self._history).count(e))
        confidence = raw_confidence if smoothed == raw_emotion else 0.5

        return smoothed, round(confidence, 3)

    def reset(self) -> None:
        self._history.clear()
