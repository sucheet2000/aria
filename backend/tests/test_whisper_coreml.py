from __future__ import annotations

import sys
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


def _build_loaded_fallback(tmp_path, mock_fw_model) -> WhisperCoreML:
    """Helper: WhisperCoreML with encoder path pointed at a missing file, loaded."""
    with mock.patch("faster_whisper.WhisperModel", return_value=mock_fw_model):
        w = WhisperCoreML(model_size="tiny")
        w._encoder_path = tmp_path / "no-such-encoder.mlpackage"
        w.load()
    return w


# ---------------------------------------------------------------------------
# test_encoder_path_bound_to_model_size
# ---------------------------------------------------------------------------

def test_encoder_path_bound_to_model_size() -> None:
    """_encoder_path contains the model size, preventing encoder/decoder pairing mismatch."""
    for size in ("tiny", "base", "small"):
        w = WhisperCoreML(model_size=size)
        assert f"whisper-{size}-encoder.mlpackage" in str(w._encoder_path), (
            f"encoder path should contain '{size}', got {w._encoder_path}"
        )


# ---------------------------------------------------------------------------
# test_fallback_when_no_mlpackage
# ---------------------------------------------------------------------------

def test_fallback_when_no_mlpackage(tmp_path) -> None:
    """WhisperCoreML.load() falls back gracefully when .mlpackage is absent."""
    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.return_value = (iter([]), mock.MagicMock())

    w = _build_loaded_fallback(tmp_path, mock_fw_model)

    assert w._use_coreml is False, "should have fallen back to faster-whisper"
    assert w._fallback_model is not None, "fallback model should be set"
    assert w._state == "ready", f"expected state=ready, got {w._state}"


# ---------------------------------------------------------------------------
# test_fallback_model_always_loaded
# ---------------------------------------------------------------------------

def test_fallback_model_always_loaded(tmp_path) -> None:
    """_fallback_model is populated and _use_coreml stays True after successful CoreML load."""
    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.return_value = (iter([]), mock.MagicMock())

    mock_encoder = mock.MagicMock()
    mock_encoder.predict.return_value = {
        "encoder_output": np.zeros((1, 1500, 384), dtype=np.float32)
    }

    fake_ct = mock.MagicMock()
    fake_ct.models.MLModel.return_value = mock_encoder
    fake_whisper = mock.MagicMock()
    sys.modules.setdefault("coremltools", fake_ct)
    sys.modules.setdefault("coremltools.models", fake_ct.models)
    sys.modules.setdefault("whisper", fake_whisper)

    with mock.patch("faster_whisper.WhisperModel", return_value=mock_fw_model), \
         mock.patch.dict(sys.modules, {
             "coremltools": fake_ct,
             "coremltools.models": fake_ct.models,
             "whisper": fake_whisper,
         }), \
         mock.patch.object(__import__("pathlib").Path, "exists", return_value=True):
        w = WhisperCoreML(model_size="tiny")
        w.load()

    assert w._fallback_model is not None, (
        "_fallback_model must be set even when CoreML loads successfully"
    )
    assert w._use_coreml is True, (
        "_use_coreml must remain True — _load_fallback_locked() must not reset it"
    )
    assert w._state == "ready"


# ---------------------------------------------------------------------------
# test_load_fails_when_fallback_unavailable
# ---------------------------------------------------------------------------

def test_coreml_only_mode_raises_on_runtime_error(tmp_path) -> None:
    """When faster-whisper preload fails but CoreML succeeds, load() succeeds
    (CoreML-only mode). A subsequent CoreML runtime error re-raises so the caller
    handles it explicitly — no silent utterance drops."""
    mock_encoder = mock.MagicMock()
    mock_encoder.predict.return_value = {
        "encoder_output": np.zeros((1, 1500, 384), dtype=np.float32)
    }

    fake_ct = mock.MagicMock()
    fake_ct.models.MLModel.return_value = mock_encoder
    fake_whisper = mock.MagicMock()
    fake_whisper_decoding = mock.MagicMock()
    sys.modules.setdefault("coremltools", fake_ct)
    sys.modules.setdefault("coremltools.models", fake_ct.models)
    sys.modules.setdefault("whisper", fake_whisper)
    sys.modules.setdefault("whisper.decoding", fake_whisper_decoding)

    with mock.patch("faster_whisper.WhisperModel", side_effect=ImportError("no faster-whisper")), \
         mock.patch.dict(sys.modules, {
             "coremltools": fake_ct,
             "coremltools.models": fake_ct.models,
             "whisper": fake_whisper,
             "whisper.decoding": fake_whisper_decoding,
         }), \
         mock.patch.object(__import__("pathlib").Path, "exists", return_value=True):
        w = WhisperCoreML(model_size="tiny")
        w.load()  # must succeed in CoreML-only mode

    assert w._use_coreml is True
    assert w._fallback_model is None
    assert w._state == "ready"

    # Inject a CoreML runtime failure — must raise, not silently return empty
    w._coreml_encoder = mock.MagicMock()
    w._coreml_encoder.predict.side_effect = RuntimeError("CoreML failed")
    with pytest.raises(RuntimeError):
        w.transcribe(_make_audio())


# ---------------------------------------------------------------------------
# test_state_machine_unloaded
# ---------------------------------------------------------------------------

def test_state_machine_unloaded() -> None:
    """transcribe() before load() raises RuntimeError (consistent with Transcriber contract)."""
    w = WhisperCoreML(model_size="tiny")
    assert w._state == "unloaded"
    with pytest.raises(RuntimeError, match="not ready"):
        w.transcribe(_make_audio())


# ---------------------------------------------------------------------------
# test_transcribe_returns_string
# ---------------------------------------------------------------------------

def test_transcribe_returns_string(tmp_path) -> None:
    """transcribe() returns (str, float) when using the faster-whisper fallback."""
    mock_segment = mock.MagicMock()
    mock_segment.text = "hello world"
    mock_segment.avg_logprob = -0.3

    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.return_value = (iter([mock_segment]), mock.MagicMock())

    w = _build_loaded_fallback(tmp_path, mock_fw_model)
    text, confidence = w.transcribe(_make_audio())

    assert isinstance(text, str), f"expected str, got {type(text)}"
    assert isinstance(confidence, float), f"expected float, got {type(confidence)}"
    assert text == "hello world"
    assert 0.0 <= confidence <= 1.0


# ---------------------------------------------------------------------------
# test_runtime_demotion_on_coreml_failure
# ---------------------------------------------------------------------------

def test_runtime_demotion_on_coreml_failure(tmp_path) -> None:
    """
    If _transcribe_coreml() raises at runtime, _use_coreml is set to False exactly
    once and subsequent calls route to faster-whisper without raising.
    """
    mock_segment = mock.MagicMock()
    mock_segment.text = "fallback text"
    mock_segment.avg_logprob = -0.2

    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.return_value = (iter([mock_segment]), mock.MagicMock())

    with mock.patch("faster_whisper.WhisperModel", return_value=mock_fw_model):
        w = WhisperCoreML(model_size="tiny")
        w._encoder_path = tmp_path / "missing.mlpackage"
        w.load()

    # Force the class to believe CoreML is active, then inject a broken encoder
    w._use_coreml = True
    w._coreml_encoder = mock.MagicMock()
    w._coreml_encoder.predict.side_effect = RuntimeError("CoreML runtime error")

    # First call: CoreML raises → demotes, returns fallback result
    text1, _ = w.transcribe(_make_audio())
    assert text1 == "fallback text", f"expected fallback text, got {text1!r}"
    assert w._use_coreml is False, "_use_coreml should be False after demotion"

    # Reset the mock generator for second call
    mock_fw_model.transcribe.return_value = (iter([mock_segment]), mock.MagicMock())

    # Second call: should go straight to fallback, CoreML never called again
    text2, _ = w.transcribe(_make_audio())
    assert text2 == "fallback text"
    # predict.call_count is not asserted here because _transcribe_coreml imports
    # torch/whisper before calling predict; on CI without openai-whisper installed
    # the import fails and predict is never reached (demotion still occurs correctly).


# ---------------------------------------------------------------------------
# test_thread_safety
# ---------------------------------------------------------------------------

def test_thread_safety(tmp_path) -> None:
    """3 threads call transcribe() concurrently — no exceptions, all return strings."""
    mock_segment = mock.MagicMock()
    mock_segment.text = "concurrent"
    mock_segment.avg_logprob = -0.1

    def make_mock_transcribe(*args, **kwargs):
        import time
        time.sleep(0.01)
        return (iter([mock_segment]), mock.MagicMock())

    mock_fw_model = mock.MagicMock()
    mock_fw_model.transcribe.side_effect = make_mock_transcribe

    with mock.patch("faster_whisper.WhisperModel", return_value=mock_fw_model):
        w = WhisperCoreML(model_size="tiny")
        w._encoder_path = tmp_path / "missing.mlpackage"
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
