from __future__ import annotations

import threading
import unittest.mock as mock

import numpy as np
import pytest

from app.pipeline.whisper_coreml import WhisperCoreML

SAMPLE_RATE = 16000


def _make_audio(seconds: float = 1.0) -> list[np.ndarray]:
    """Return a list with one float32 chunk of silence."""
    samples = np.zeros(int(SAMPLE_RATE * seconds), dtype=np.float32)
    return [samples]


# ---------------------------------------------------------------------------
# test_fallback_when_no_mlpackage
# ---------------------------------------------------------------------------

def test_fallback_when_no_mlpackage(tmp_path, monkeypatch) -> None:
    """WhisperCoreML.load() falls back gracefully when .mlpackage is absent."""

    # Point encoder path at a non-existent location
    monkeypatch.setattr(
        "app.pipeline.whisper_coreml._ENCODER_PATH",
        tmp_path / "no-such-encoder.mlpackage",
    )

    # Also patch faster-whisper so it doesn't actually load a model
    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.return_value = (iter([]), mock.MagicMock())

    with mock.patch("faster_whisper.WhisperModel", return_value=mock_fw_model):
        w = WhisperCoreML(model_size="tiny")
        w.load()

    assert w._use_coreml is False, "should have fallen back to faster-whisper"
    assert w._fallback_model is not None, "fallback model should be set"


# ---------------------------------------------------------------------------
# test_transcribe_returns_string
# ---------------------------------------------------------------------------

def test_transcribe_returns_string(tmp_path, monkeypatch) -> None:
    """transcribe() returns (str, float) when using the faster-whisper fallback."""

    monkeypatch.setattr(
        "app.pipeline.whisper_coreml._ENCODER_PATH",
        tmp_path / "missing.mlpackage",
    )

    # Mock a faster-whisper segment
    mock_segment = mock.MagicMock()
    mock_segment.text = "hello world"
    mock_segment.avg_logprob = -0.3

    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.return_value = (iter([mock_segment]), mock.MagicMock())

    with mock.patch("faster_whisper.WhisperModel", return_value=mock_fw_model):
        w = WhisperCoreML(model_size="tiny")
        w.load()
        text, confidence = w.transcribe(_make_audio())

    assert isinstance(text, str), f"expected str, got {type(text)}"
    assert isinstance(confidence, float), f"expected float, got {type(confidence)}"
    assert text == "hello world"
    assert 0.0 <= confidence <= 1.0


# ---------------------------------------------------------------------------
# test_thread_safety
# ---------------------------------------------------------------------------

def test_thread_safety(tmp_path, monkeypatch) -> None:
    """3 threads call transcribe() concurrently — no exceptions, all return strings."""

    monkeypatch.setattr(
        "app.pipeline.whisper_coreml._ENCODER_PATH",
        tmp_path / "missing.mlpackage",
    )

    mock_segment = mock.MagicMock()
    mock_segment.text = "concurrent"
    mock_segment.avg_logprob = -0.1

    def make_mock_transcribe(*args, **kwargs):
        # Simulate a small amount of work
        import time
        time.sleep(0.01)
        return (iter([mock_segment]), mock.MagicMock())

    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.side_effect = make_mock_transcribe

    with mock.patch("faster_whisper.WhisperModel", return_value=mock_fw_model):
        w = WhisperCoreML(model_size="tiny")
        w.load()

    results: list[tuple[str, float] | Exception] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            r = w.transcribe(_make_audio())
            with lock:
                results.append(r)
        except Exception as exc:
            with lock:
                results.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 3, f"expected 3 results, got {len(results)}"
    for r in results:
        assert not isinstance(r, Exception), f"thread raised: {r}"
        text, confidence = r
        assert isinstance(text, str)
        assert isinstance(confidence, float)
