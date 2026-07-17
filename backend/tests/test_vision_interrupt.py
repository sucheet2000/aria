from __future__ import annotations

from app.pipeline.vision_worker import FaceExitDetector


def test_500ms_no_face_triggers_interrupt() -> None:
    detector = FaceExitDetector(absence_threshold=0.5)
    t = 0.0

    # Establish that face was seen
    assert detector.update(face_detected=True, now=t) is False
    t += 0.1

    # Face disappears — under threshold, no interrupt yet
    assert detector.update(face_detected=False, now=t) is False
    t += 0.4  # total absence = 0.5s, crosses threshold

    assert detector.update(face_detected=False, now=t) is True


def test_face_redetected_before_timeout_no_interrupt() -> None:
    detector = FaceExitDetector(absence_threshold=0.5)
    t = 0.0

    detector.update(face_detected=True, now=t)
    t += 0.3
    detector.update(face_detected=False, now=t)  # 0.3s absence — not enough
    t += 0.1
    # Face comes back — resets the timer and clears interrupt_sent flag
    assert detector.update(face_detected=True, now=t) is False
    t += 0.6
    # Face gone again but timer restarted from face redetection
    assert detector.update(face_detected=False, now=t) is True


def test_interrupt_not_sent_twice() -> None:
    detector = FaceExitDetector(absence_threshold=0.5)
    t = 0.0

    detector.update(face_detected=True, now=t)
    t += 0.6
    first = detector.update(face_detected=False, now=t)
    assert first is True

    t += 0.1
    second = detector.update(face_detected=False, now=t)
    assert second is False, "interrupt must not be sent a second time without face reappearing"


def test_no_interrupt_if_face_never_detected() -> None:
    detector = FaceExitDetector(absence_threshold=0.5)
    t = 0.0

    # Face was never seen — should never fire interrupt
    for _ in range(10):
        t += 0.1
        assert detector.update(face_detected=False, now=t) is False


def test_face_reappears_resets_for_next_exit() -> None:
    detector = FaceExitDetector(absence_threshold=0.5)
    t = 0.0

    # First exit
    detector.update(face_detected=True, now=t)
    t += 0.6
    assert detector.update(face_detected=False, now=t) is True

    # Face returns — reset
    t += 0.1
    detector.update(face_detected=True, now=t)

    # Second exit — should trigger again
    t += 0.6
    assert detector.update(face_detected=False, now=t) is True
