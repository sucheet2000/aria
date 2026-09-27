"""The worker's --device flag must reach the Transcriber it builds.

Go hands the configured WHISPER_DEVICE to this process as ``--device`` (pinned
in cmd/server/main_test.go). ``run_stdin`` then constructs the Transcriber, and
nothing tested that hop: dropping ``device=`` there silently falls back to the
Transcriber's own default and every other test still passes.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from app.pipeline import audio_worker


def test_device_flag_reaches_the_transcriber(monkeypatch: pytest.MonkeyPatch) -> None:
    built: dict[str, Any] = {}

    class RecordingTranscriber:
        def __init__(self, model_size: str = "base", device: str = "auto") -> None:
            built.update(model_size=model_size, device=device)

        def load(self) -> None:
            # Stop the worker right after construction; run_stdin turns a load
            # failure into sys.exit(1).
            raise RuntimeError("stop after construction")

    class NoopVAD:
        def __init__(self, **_: Any) -> None:
            pass

        def load(self) -> None:
            pass

    monkeypatch.setattr(audio_worker, "Transcriber", RecordingTranscriber)
    monkeypatch.setattr(audio_worker, "VADProcessor", NoopVAD)
    monkeypatch.setattr(audio_worker, "configure_worker_logging", lambda: None)
    monkeypatch.setattr(audio_worker.signal, "signal", lambda *_: None)
    monkeypatch.setattr(sys, "argv", ["audio_worker.py", "--model", "tiny", "--device", "cuda"])

    with pytest.raises(SystemExit):
        audio_worker.main()

    assert built == {"model_size": "tiny", "device": "cuda"}
