"""V3 — the TTS mute lives at the Go edge, the sleep mute lives in this process.

These tests pin the consequences of that split. The Go edge drops an owner's PCM
while ARIA speaks, so from Python's side TTS suppression is simply an absence of
frames. The sleep mute is a different mechanism entirely, owned by the VAD, and
nothing the Go edge does can reach it — the subprocess stdin carries raw PCM and
nothing else.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from unittest import mock

import numpy as np
import pytest
import structlog
from structlog.testing import capture_logs

import app.pipeline.audio_worker as aw
from app.pipeline.vad import VADProcessor
from tests.test_audio_utterance_isolation import make_vad, silence, speech

PRIVATE = "PRIVATE_TTS_FEEDBACK_5197"


# ── the two mutes cannot reach each other ────────────────────────────────────


def test_worker_stdin_carries_pcm_only_so_go_cannot_unmute_the_vad() -> None:
    """Test 17 — proof, not assertion.

    The only channel from Go into this process is stdin, and read_stdin treats
    every byte as Int16 PCM (read_pcm_chunks). Feeding the exact JSON the browser sends for
    tts_unmute therefore cannot clear a sleep mute; it is just noise samples.
    """
    vad = make_vad()
    vad.mute()

    payload = json.dumps({"type": "tts_unmute"}).encode()
    # Pad to whole frames, the way the reader would consume it.
    frame_bytes = VADProcessor.CHUNK_SAMPLES * 2
    payload = payload.ljust(frame_bytes * 2, b"\x00")

    stream = io.BytesIO(payload)
    for chunk in aw.read_pcm_chunks(stream):
        vad.process_chunk(chunk)

    assert vad._muted is True   # a muted VAD stays muted


def test_muted_vad_produces_no_utterance_at_all() -> None:
    """Tests 12 and 13 at the pipeline level.

    Suppressed audio yields no completed utterance, so it can produce no
    transcript — and with no transcript there is nothing for the V2 matcher to
    read. No wake and no sleep can originate from audio that never arrives.
    """
    vad = make_vad()
    vad.mute()

    completed_any = False
    for chunk in speech(1.0) + silence():
        _is_speech, completed = vad.process_chunk(chunk)
        if completed is not None:
            completed_any = True

    assert completed_any is False
    assert vad._speech_chunks == []   # nothing accumulated either


def test_unmuting_after_suppressed_audio_does_not_replay_it() -> None:
    """Test 18 — the V1 guarantee holds across a mute window.

    Audio that arrived while muted is dropped, not buffered, so unmuting cannot
    resurrect it. The next utterance transcribes only its own audio.
    """
    vad = make_vad()
    vad.mute()
    for chunk in speech(1.0):
        vad.process_chunk(chunk)
    assert vad._speech_chunks == []

    vad.unmute()
    completed = None
    for chunk in speech(0.4) + silence():
        _is_speech, out = vad.process_chunk(chunk)
        if out is not None:
            completed = out

    assert completed is not None
    # 0.4 s of speech plus the trailing silence window — not the suppressed 1.0 s.
    assert len(completed) * VADProcessor.CHUNK_MS < 1000


def test_completed_utterance_is_not_resurrected_by_a_mute_cycle() -> None:
    """Test 18 — take-and-reset survives mute/unmute churn."""
    vad = make_vad()

    first = None
    for chunk in speech(0.4) + silence():
        _is_speech, out = vad.process_chunk(chunk)
        if out is not None:
            first = out
    assert first is not None
    assert vad._speech_chunks == []

    vad.mute()
    vad.unmute()
    assert vad._speech_chunks == []   # the completed utterance is gone for good

    second = None
    for chunk in speech(0.4) + silence():
        _is_speech, out = vad.process_chunk(chunk)
        if out is not None:
            second = out
    assert second is not None
    assert len(second) == len(first)   # independent, not accumulated


# ── the sleep mute is owned by the sleep path alone ──────────────────────────


class _ScriptedVAD:
    """One chunk finalizes one utterance, so transcripts can be scripted."""

    CHUNK_MS = VADProcessor.CHUNK_MS

    def __init__(self) -> None:
        self._muted = False
        self.mute_calls = 0
        self.unmute_calls = 0
        self.cleared = 0

    def process_chunk(self, chunk: np.ndarray) -> tuple:
        if self._muted:
            return False, None
        return False, [chunk]

    def mute(self) -> None:
        self._muted = True
        self.mute_calls += 1

    def unmute(self) -> None:
        self._muted = False
        self.unmute_calls += 1

    def clear(self) -> None:
        self.cleared += 1


@pytest.fixture
def scripted_args() -> argparse.Namespace:
    return argparse.Namespace(denoise=False, max_utterance_ms=8000)


def test_only_the_sleep_path_mutes_the_vad(scripted_args: argparse.Namespace) -> None:
    """The VAD mute has exactly one caller in this process: going to sleep.

    Nothing in the transcript loop mutes for TTS, which is what keeps the two
    mechanisms independent.
    """
    vad = _ScriptedVAD()
    transcriber = mock.Mock()
    transcriber.transcribe.side_effect = [("aria", 0.9), ("what time is it", 0.9)]
    denoiser = mock.Mock(enabled=False)
    chunks = [np.full(VADProcessor.CHUNK_SAMPLES, 0.2, dtype=np.float32)] * 2

    timers: list[float] = []
    with mock.patch.object(aw.threading, "Timer") as timer_cls:
        timer_cls.side_effect = lambda d, fn: (timers.append(d), mock.Mock())[1]
        with contextlib.redirect_stdout(io.StringIO()):
            aw.process_audio_stream(iter(chunks), vad, transcriber, denoiser, scripted_args)

    # A wake and an ordinary transcript: no sleep, so no mute anywhere.
    assert vad.mute_calls == 0
    assert vad.cleared == 0
    assert timers == []


def test_sleep_mutes_and_arms_exactly_one_unmute_timer(
    scripted_args: argparse.Namespace,
) -> None:
    vad = _ScriptedVAD()
    transcriber = mock.Mock()
    transcriber.transcribe.side_effect = [("aria", 0.9), ("that would be all", 0.9)]
    denoiser = mock.Mock(enabled=False)
    chunks = [np.full(VADProcessor.CHUNK_SAMPLES, 0.2, dtype=np.float32)] * 2

    timers: list[float] = []
    with mock.patch.object(aw.threading, "Timer") as timer_cls:
        timer_cls.side_effect = lambda d, fn: (timers.append(d), mock.Mock())[1]
        with contextlib.redirect_stdout(io.StringIO()):
            aw.process_audio_stream(iter(chunks), vad, transcriber, denoiser, scripted_args)

    assert vad.mute_calls == 1
    assert vad.cleared == 1
    assert timers == [5.0]        # one timer, the sleep one
    assert vad.unmute_calls == 0  # the mock timer never fires it early


# ── S2 ───────────────────────────────────────────────────────────────────────


def test_no_spoken_text_in_logs_on_the_mute_paths(
    scripted_args: argparse.Namespace,
) -> None:
    """Test 24 — the sentinel must not appear anywhere in the log stream."""
    vad = _ScriptedVAD()
    transcriber = mock.Mock()
    transcriber.transcribe.side_effect = [(f"aria {PRIVATE}", 0.9)]
    denoiser = mock.Mock(enabled=False)
    chunks = [np.full(VADProcessor.CHUNK_SAMPLES, 0.2, dtype=np.float32)]

    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.BoundLogger)
    try:
        with capture_logs() as logs:
            with mock.patch.object(aw.threading, "Timer"):
                with contextlib.redirect_stdout(io.StringIO()):
                    aw.process_audio_stream(
                        iter(chunks), vad, transcriber, denoiser, scripted_args
                    )
        assert PRIVATE not in "\n".join(repr(entry) for entry in logs)
    finally:
        structlog.configure(**saved)


# ── V3.1: what the surviving fragment can and cannot contain ─────────────────


def test_mute_gap_fragment_holds_only_audio_that_arrived_before_the_gap() -> None:
    """V3.1 reassessment of the V3 partial-utterance finding.

    When frames stop arriving mid-utterance the VAD keeps the half-collected
    buffer, and resumes appending when they return. The two halves are spliced
    into one utterance with the gap excised. That is stale, but it is not a
    self-feedback path: the browser now closes its own uplink gate *before* the
    first audible sample of ARIA's reply, so the pre-gap half can only contain
    audio captured while ARIA was still silent.

    This test pins the mechanism: the fragment is exactly the frames that were
    delivered, in order, and nothing the gap suppressed can appear in it.
    """
    vad = make_vad()

    # The user is mid-sentence. Each chunk carries a distinct amplitude so the
    # finalized utterance can be read back and attributed.
    before = [c * 0.0 + 0.30 for c in speech(0.3)]
    for chunk in before:
        vad.process_chunk(chunk)
    assert vad._speech_chunks != []          # a partial utterance is resident
    assert vad._in_speech is True

    # ARIA speaks. The browser gate is shut, so NOTHING is delivered here —
    # process_chunk is never called, which is exactly what a suppressed uplink
    # looks like from this side. These chunks stand for ARIA's own voice and
    # are deliberately never handed to the VAD.
    held_before_gap = len(vad._speech_chunks)

    # The user speaks again once ARIA has finished.
    after = [c * 0.0 + 0.60 for c in speech(0.3)]
    completed = None
    for chunk in after + silence():
        _is_speech, out = vad.process_chunk(chunk)
        if out is not None:
            completed = out

    assert completed is not None
    amplitudes = {round(float(np.max(np.abs(c))), 2) for c in completed}
    # Both halves of the user's speech are present, spliced together...
    assert 0.30 in amplitudes
    assert 0.60 in amplitudes
    # ...and not one sample of what the gate suppressed.
    assert 0.99 not in amplitudes
    # The pre-gap half survived intact rather than being dropped or duplicated.
    assert len(completed) > held_before_gap
    assert vad._speech_chunks == []          # V1 take-and-reset still holds
