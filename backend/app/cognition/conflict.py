from __future__ import annotations

POSITIVE_EMOTIONS = {"happy", "surprised", "excited"}
NEGATIVE_EMOTIONS = {"sad", "angry", "fearful", "disgusted"}
NEUTRAL_EMOTIONS = {"neutral"}

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


def visual_sentiment(emotion: str, confidence: float) -> float:
    """
    Returns sentiment score from -1.0 to 1.0 based on detected emotion.
    """
    if emotion in POSITIVE_EMOTIONS:
        return round(confidence, 2)
    if emotion in NEGATIVE_EMOTIONS:
        return round(-confidence, 2)
    return 0.0


def detect_conflict(
    transcript: str,
    emotion: str,
    confidence: float,
    threshold: float = 0.4,
) -> tuple[bool, float]:
    """
    Returns (conflict_detected, delta).
    conflict_detected is True when speech and visual signals strongly disagree.
    delta is the absolute difference between speech and visual sentiment.
    """
    speech = speech_sentiment(transcript)
    visual = visual_sentiment(emotion, confidence)
    delta = round(abs(speech - visual), 3)
    return delta >= threshold, delta
