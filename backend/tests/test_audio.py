from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).parent.parent


def test_audio_transcript_schema() -> None:
    from app.models.schemas import AudioTranscript

    t = AudioTranscript(transcript="hello", is_final=True, confidence=0.9)
    assert t.transcript == "hello"
    assert t.is_final is True
    assert isinstance(t.confidence, float)
    assert t.confidence == 0.9
    assert isinstance(t.duration_ms, int)
    assert isinstance(t.timestamp, float)


def test_vad_processor_init() -> None:
    from app.pipeline.vad import VADProcessor

    VADProcessor()
    assert VADProcessor.SAMPLE_RATE == 16000
    assert VADProcessor.CHUNK_MS == 30
    assert VADProcessor.CHUNK_SAMPLES == 480


def test_transcriber_init() -> None:
    from app.pipeline.transcriber import Transcriber

    t = Transcriber(model_size="base")
    assert t._model is None


def test_denoiser_disabled_before_load() -> None:
    from app.pipeline.denoiser import Denoiser

    d = Denoiser()
    assert d.enabled is False


def test_denoiser_enhance_passthrough_when_not_loaded() -> None:
    from app.pipeline.denoiser import Denoiser

    d = Denoiser()
    audio = np.ones(16000, dtype=np.float32) * 0.5
    result = d.enhance(audio)
    np.testing.assert_array_equal(result, audio)


def test_transcriber_build_initial_prompt_no_keywords() -> None:
    from app.pipeline.transcriber import BASE_DOMAIN_PROMPT, Transcriber

    t = Transcriber()
    assert t._build_initial_prompt() == BASE_DOMAIN_PROMPT


def test_transcriber_build_initial_prompt_with_keywords() -> None:
    from app.pipeline.transcriber import BASE_DOMAIN_PROMPT, Transcriber

    t = Transcriber()
    t.set_dynamic_keywords(["Arsenal", "football", "Premier League"])
    prompt = t._build_initial_prompt()
    assert prompt.startswith("Arsenal, football, Premier League.")
    assert BASE_DOMAIN_PROMPT in prompt


def test_transcriber_reset_context_clears_keywords() -> None:
    from app.pipeline.transcriber import Transcriber

    t = Transcriber()
    t.set_dynamic_keywords(["foo", "bar"])
    assert t._dynamic_keywords == ["foo", "bar"]
    t.reset_context()
    assert t._dynamic_keywords == []


def test_transcriber_reset_context_disables_conditioning() -> None:
    from app.pipeline.transcriber import Transcriber

    t = Transcriber()
    assert t._condition_on_previous is True
    t.reset_context()
    assert t._condition_on_previous is False


def test_transcriber_condition_restored_after_transcribe() -> None:
    from unittest.mock import MagicMock

    from app.pipeline.transcriber import Transcriber

    t = Transcriber()
    t.reset_context()
    assert t._condition_on_previous is False

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "hello"
    mock_segment.avg_logprob = -0.3
    mock_model.transcribe.return_value = ([mock_segment], MagicMock())
    t._model = mock_model

    audio = np.zeros(16000, dtype=np.float32)
    t.transcribe([audio])

    assert t._condition_on_previous is True


def test_audio_worker_synthetic() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(
        [
            sys.executable,
            str(BACKEND_DIR / "app" / "pipeline" / "audio_worker.py"),
            "--synthetic",
            "--duration",
            "4",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(BACKEND_DIR),
        env=env,
    )

    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(lines) >= 1, f"expected at least 1 transcript, got 0\nstderr: {result.stderr}"

    required_keys = {"transcript", "is_final", "confidence", "duration_ms", "timestamp"}
    for line in lines:
        data = json.loads(line)
        missing = required_keys - data.keys()
        assert not missing, f"missing keys {missing} in: {data}"
        assert isinstance(data["transcript"], str)
        assert data["transcript"] != ""


def test_audio_worker_synthetic_denoise() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    result = subprocess.run(
        [
            sys.executable,
            str(BACKEND_DIR / "app" / "pipeline" / "audio_worker.py"),
            "--synthetic",
            "--denoise",
            "--duration",
            "3",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(BACKEND_DIR),
        env=env,
    )

    assert result.returncode == 0, f"worker exited with {result.returncode}\nstderr: {result.stderr}"

    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    assert len(lines) >= 1, f"expected at least 1 transcript\nstderr: {result.stderr}"

    required_keys = {"transcript", "is_final", "confidence", "duration_ms", "timestamp"}
    for line in lines:
        data = json.loads(line)
        missing = required_keys - data.keys()
        assert not missing, f"missing keys {missing} in: {data}"

    assert "synthetic mode" in result.stderr
    assert "denoise=on" in result.stderr
