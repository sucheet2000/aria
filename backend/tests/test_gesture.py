
from app.models.schemas import GestureState
from app.pipeline.gesture import GestureClassifier


def test_gesture_state_defaults() -> None:
    state = GestureState()
    assert state.gesture_name == "none"
    assert state.confidence == 0.0
    assert state.hand_landmarks == []


def test_gesture_state_with_data() -> None:
    state = GestureState(
        gesture_name="wave",
        confidence=0.95,
        hand_landmarks=[[0.1, 0.2, 0.0]] * 21,
    )
    assert state.gesture_name == "wave"
    assert state.confidence == 0.95
    assert len(state.hand_landmarks) == 21


def test_classifier_predict_returns_defaults() -> None:
    classifier = GestureClassifier()
    gesture, confidence = classifier.predict([])
    assert gesture == "none"
    assert confidence == 0.0


def test_classifier_predict_with_landmarks() -> None:
    classifier = GestureClassifier()
    landmarks = [[float(i), float(i), 0.0] for i in range(21)]
    gesture, confidence = classifier.predict(landmarks)
    assert isinstance(gesture, str)
    assert isinstance(confidence, float)
