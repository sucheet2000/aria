"""Workstream F — the device setting must mean what it says.

Transcriber accepted a `device` argument, stored it, and then built the model
with device="cpu" hardcoded. Configuring anything else changed nothing and said
nothing: the setting read as supported and was silently discarded.
"""
from __future__ import annotations

from unittest import mock

import pytest

from app.pipeline.transcriber import Transcriber


def _captured_kwargs(device: str) -> dict:
    """Build a Transcriber and return the kwargs it passes to WhisperModel."""
    fake_model = mock.Mock()
    fake_module = mock.Mock(WhisperModel=mock.Mock(return_value=fake_model))
    with mock.patch.dict("sys.modules", {"faster_whisper": fake_module}):
        Transcriber(model_size="base", device=device).load()
    return fake_module.WhisperModel.call_args.kwargs


class TestDeviceIsHonoured:
    def test_cpu_is_passed_through(self) -> None:
        assert _captured_kwargs("cpu")["device"] == "cpu"

    def test_auto_is_passed_through_not_rewritten_to_cpu(self) -> None:
        # "auto" is faster-whisper's own value meaning "pick the best available".
        # Rewriting it to "cpu" is what made the setting a lie.
        assert _captured_kwargs("auto")["device"] == "auto"

    def test_cuda_is_passed_through(self) -> None:
        assert _captured_kwargs("cuda")["device"] == "cuda"

    @pytest.mark.parametrize("bad", ["gpu", "metal", "", "CPU!", "cpu; rm -rf /"])
    def test_an_unsupported_value_is_rejected_loudly(self, bad: str) -> None:
        # Better a clear error at startup than a silent fallback that makes the
        # configuration meaningless.
        with pytest.raises(ValueError, match="device"):
            Transcriber(model_size="base", device=bad)

    def test_compute_type_follows_the_device(self) -> None:
        # int8 is the right choice on CPU and the wrong one on an accelerator;
        # hardcoding it alongside a configurable device made no sense.
        assert _captured_kwargs("cpu")["compute_type"] == "int8"
        assert _captured_kwargs("cuda")["compute_type"] != "int8"

    def test_the_default_is_unchanged_from_today(self) -> None:
        # Existing deployments must keep running on CPU/int8 exactly as before.
        kwargs = _captured_kwargs("cpu")
        assert kwargs["device"] == "cpu"
        assert kwargs["compute_type"] == "int8"


class TestFallbackBehaviour:
    def test_an_unavailable_accelerator_falls_back_to_cpu_with_a_warning(self) -> None:
        """A machine configured for cuda that has none must still transcribe."""
        fake_module = mock.Mock()
        fake_module.WhisperModel = mock.Mock(
            side_effect=[RuntimeError("no CUDA device"), mock.Mock()]
        )
        with mock.patch.dict("sys.modules", {"faster_whisper": fake_module}):
            t = Transcriber(model_size="base", device="cuda")
            t.load()

        assert fake_module.WhisperModel.call_count == 2
        first, second = fake_module.WhisperModel.call_args_list
        assert first.kwargs["device"] == "cuda"
        assert second.kwargs["device"] == "cpu"
        assert second.kwargs["compute_type"] == "int8"

    def test_a_cpu_failure_is_not_swallowed(self) -> None:
        """CPU is the fallback; if it fails there is nothing left to try."""
        fake_module = mock.Mock()
        fake_module.WhisperModel = mock.Mock(side_effect=RuntimeError("disk full"))
        with mock.patch.dict("sys.modules", {"faster_whisper": fake_module}):
            with pytest.raises(RuntimeError, match="disk full"):
                Transcriber(model_size="base", device="cpu").load()
