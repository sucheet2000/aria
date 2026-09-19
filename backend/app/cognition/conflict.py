from __future__ import annotations

POSITIVE_EMOTIONS = {"happy", "surprised", "excited"}
NEGATIVE_EMOTIONS = {"sad", "angry", "fearful", "disgusted"}
NEUTRAL_EMOTIONS = {"neutral"}

# Minimum heuristic facial-affect confidence for the visual signal to count in
# conflict detection (inclusive: ``>=``). The browser classifier emits a
# non-neutral label only when its weighted score clears 0.38–0.45 and reports
# exactly 0.5 when its 5-frame smoothing overrides the raw frame, so 0.6
# requires a stable, clearly-scored expression before speech is contradicted.
CONFLICT_MIN_VISUAL_CONFIDENCE = 0.6

POSITIVE_WORDS = {
    "happy", "great", "good", "fine", "wonderful", "excited",
    "love", "amazing", "perfect", "fantastic", "okay", "ok"
}
NEGATIVE_WORDS = {
    "sad", "angry", "frustrated", "tired", "stressed", "terrible",
    "bad", "awful", "hate", "broken", "stuck", "lost", "confused"
}


def speech_sentiment(transcript: str) -> float:
    """
    Returns sentiment score from -1.0 (negative) to 1.0 (positive).
    Simple keyword scan — no external models needed.
    """
    words = transcript.lower().split()
    pos = sum(1 for w in words if w in POSITIVE_WORDS)
    neg = sum(1 for w in words if w in NEGATIVE_WORDS)
    total = pos + neg
    if total == 0:
        return 0.0
    return round((pos - neg) / total, 2)


def visual_sentiment(emotion: str, confidence: float | None) -> float:
    """
    Returns sentiment score from -1.0 to 1.0 based on the estimated facial
    affect, signed by emotion polarity and scaled by its heuristic confidence.
    ``None`` (perception unavailable) carries no visual signal.
    """
    if confidence is None:
        return 0.0
    if emotion in POSITIVE_EMOTIONS:
        return round(confidence, 2)
    if emotion in NEGATIVE_EMOTIONS:
        return round(-confidence, 2)
    return 0.0


def detect_conflict(
    transcript: str,
    emotion: str,
    confidence: float | None,
    threshold: float = 0.4,
    min_confidence: float = CONFLICT_MIN_VISUAL_CONFIDENCE,
) -> tuple[bool, float]:
    """
    Returns (conflict_detected, delta).
    conflict_detected is True when speech and visual signals strongly disagree:
    both carry a sentiment, of opposite polarity, the visual one is backed by
    at least ``min_confidence`` (inclusive), and they differ by ``threshold``.
    Missing, zero or low confidence never produces a conflict — the visual
    signal is a noisy heuristic and is not allowed to contradict speech on its
    own. delta is the absolute difference between speech and visual sentiment.
    """
    speech = speech_sentiment(transcript)
    visual = visual_sentiment(emotion, confidence)
    delta = round(abs(speech - visual), 3)
    if confidence is None or confidence < min_confidence:
        return False, delta
    if speech == 0.0 or visual == 0.0 or (speech > 0) == (visual > 0):
        return False, delta
    # With both gates passed, delta is the sum of two magnitudes of which the
    # visual one is already >= min_confidence, so ``threshold`` (0.4) is kept
    # for API compatibility and cannot fail at the default values.
    return delta >= threshold, delta
