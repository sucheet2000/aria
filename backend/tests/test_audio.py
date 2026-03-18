from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

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

    vad = VADProcessor()
    assert VADProcessor.SAMPLE_RATE == 16000
    assert VADProcessor.CHUNK_MS == 30
    assert VADProcessor.CHUNK_SAMPLES == 480


def test_transcriber_init() -> None:
    from app.pipeline.transcriber import Transcriber

    t = Transcriber(model_size="base")
    assert t._model is None


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
