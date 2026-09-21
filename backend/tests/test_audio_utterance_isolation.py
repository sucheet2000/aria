"""V1 — ghost retranscription: one utterance, one buffer, one transcription.

The VADProcessor is the sole owner of the utterance buffer. Every
finalization path — trailing silence AND the max-utterance forced flush —
performs an atomic take-and-reset inside ``process_chunk``, so the live
buffer is empty before the transcriber ever runs, a completed utterance can
never leak into the next one, and a long utterance is partitioned rather
than transcribed twice. The worker holds no speech buffer of its own (the
old duplicate was audit finding B5: reset only by its cumulative 8 s flush,
which replayed already-transcribed speech).

All audio here is synthetic: utterances are tagged by a distinctive constant
amplitude so a transcription input can be asked "whose audio is in you?".
No microphone, no webrtcvad, no Whisper model.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from collections.abc import Iterator
from contextlib import contextmanager
from unittest import mock

import numpy as np
import pytest
import structlog
from structlog.testing import capture_logs

from app.pipeline import audio_worker as aw
from app.pipeline.vad import VADProcessor

CHUNK = VADProcessor.CHUNK_SAMPLES  # 480 samples = 30 ms
SPEECH_N = 10                       # 300 ms ≥ MIN_SPEECH_MS (250)
SIL_N = 14                          # 420 ms ≥ MAX_SILENCE_MS (400)

# Utterance markers: distinct amplitudes, all above the fake-VAD speech
# threshold (0.1) and the idle energy gate (0.006).
MARK_A, MARK_B, MARK_C = 0.30, 0.20, 0.12
PRIVATE = "PRIVATE_GHOST_TRANSCRIPT_3814"


class FakeWebRTC:
    """Deterministic stand-in for webrtcvad: speech iff loud.

    Content-based rather than a scripted side_effect list, so interleaved
    multi-utterance and multi-owner sequences stay order-independent.
    """

    def is_speech(self, pcm: bytes, rate: int) -> bool:
        samples = np.frombuffer(pcm, dtype="<i2")
        return bool(np.abs(samples).max() > 3200)  # ≈ 0.1 in float


def make_vad(**kwargs) -> VADProcessor:
    vad = VADProcessor(**kwargs)
    vad._vad = FakeWebRTC()
    return vad


def speech(marker: float, n: int = SPEECH_N) -> list[np.ndarray]:
    return [np.full(CHUNK, marker, dtype=np.float32) for _ in range(n)]


def silence(n: int = SIL_N) -> list[np.ndarray]:
    return [np.zeros(CHUNK, dtype=np.float32) for _ in range(n)]


def markers_in(chunks: list[np.ndarray]) -> set[float]:
    """Which utterance markers appear anywhere in a transcription input."""
    values: set[float] = set()
    for arr in chunks:
        peak = float(np.abs(arr).max())
        if peak > 0:
            values.add(round(peak, 2))
    return values


class RecordingTranscriber:
    """Records a deep snapshot of every transcription input.

    ``results`` maps call index → return value or Exception to raise.
    """

    def __init__(self, results: dict[int, object] | None = None) -> None:
        self.calls: list[dict] = []
        self.results = results or {}
        self.default = ("hey aria", 0.9)

    def transcribe(self, audio_chunks: list[np.ndarray]) -> tuple[str, float]:
        index = len(self.calls)
        self.calls.append(
            {
                "ref": audio_chunks,                       # identity, for aliasing checks
                "copy": [a.copy() for a in audio_chunks],  # content at call time
                "n": len(audio_chunks),
            }
        )
        outcome = self.results.get(index, self.default)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome  # type: ignore[return-value]


def run_worker(
    chunks: list[np.ndarray],
    transcriber: RecordingTranscriber,
    vad: VADProcessor | None = None,
    max_utterance_ms: int = 8000,
) -> tuple[VADProcessor, list[dict]]:
    """Drive process_audio_stream exactly as production does and return the
    VAD plus parsed stdout lines."""
    vad = vad or make_vad(max_utterance_ms=max_utterance_ms)
    denoiser = mock.Mock(enabled=False)
    args = argparse.Namespace(denoise=False, max_utterance_ms=max_utterance_ms)
    saved = structlog.get_config()
    out = io.StringIO()
    try:
        aw.configure_worker_logging()
        with contextlib.redirect_stdout(out):
            aw.process_audio_stream(iter(chunks), vad, transcriber, denoiser, args)
    finally:
        structlog.configure(**saved)
    lines = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    return vad, lines


@contextmanager
def capture_all_levels() -> Iterator[list[dict]]:
    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.BoundLogger)
    try:
        with capture_logs() as logs:
            structlog.get_logger().debug("probe")
            logs.pop()
            yield logs
    finally:
        structlog.configure(**saved)


# ── Tests 1, 18: one utterance → one transcription → one transcript event ────


def test_single_utterance_transcribed_once_and_buffer_empty() -> None:
    ft = RecordingTranscriber()
    vad, lines = run_worker(speech(MARK_A) + silence(), ft)

    assert len(ft.calls) == 1
    assert markers_in(ft.calls[0]["copy"]) == {MARK_A}
    assert ft.calls[0]["n"] == SPEECH_N + SIL_N  # speech + the trailing-silence window
    assert vad._speech_chunks == []              # live buffer empty afterwards

    transcripts = [ln for ln in lines if ln.get("transcript")]
    assert len(transcripts) == 1                 # exactly one downstream event


# ── Tests 2, 3: sequential utterances stay independent ───────────────────────


def test_sequential_utterances_receive_only_their_own_audio() -> None:
    ft = RecordingTranscriber()
    run_worker(speech(MARK_A) + silence() + speech(MARK_B) + silence(), ft)

    assert len(ft.calls) == 2
    assert markers_in(ft.calls[0]["copy"]) == {MARK_A}
    assert markers_in(ft.calls[1]["copy"]) == {MARK_B}


def test_three_utterances_never_accumulate() -> None:
    ft = RecordingTranscriber()
    run_worker(
        speech(MARK_A) + silence() + speech(MARK_B) + silence() + speech(MARK_C) + silence(),
        ft,
    )

    assert [markers_in(c["copy"]) for c in ft.calls] == [{MARK_A}, {MARK_B}, {MARK_C}]
    assert [c["n"] for c in ft.calls] == [SPEECH_N + SIL_N] * 3


# ── The B5 core: the forced flush must never replay completed speech ─────────


def test_completed_speech_cannot_reappear_in_forced_flush() -> None:
    """Pre-fix RED: the worker kept its own speech buffer that was never
    reset when the VAD finalized, so once CUMULATIVE speech crossed the cap
    its flush replayed utterances that were already transcribed."""
    ft = RecordingTranscriber()
    cap_ms = 360  # 12 chunks — under two 10-chunk utterances' cumulative speech
    run_worker(
        speech(MARK_A) + silence() + speech(MARK_B) + silence() + speech(MARK_C) + silence(),
        ft,
        max_utterance_ms=cap_ms,
    )

    for i, call in enumerate(ft.calls):
        found = markers_in(call["copy"])
        assert len(found) == 1, (
            f"call {i} mixed audio from several utterances: {sorted(found)} — ghost retranscription"
        )
    # And every utterance still got through exactly once.
    assert [markers_in(c["copy"]) for c in ft.calls] == [{MARK_A}, {MARK_B}, {MARK_C}]


def test_long_utterance_is_partitioned_not_transcribed_twice() -> None:
    """Pre-fix RED: the worker's flush did not tell the VAD, whose own buffer
    kept everything and re-transcribed the whole utterance on silence."""
    ft = RecordingTranscriber()
    cap_chunks = 12
    total_chunks = 20
    run_worker(
        speech(MARK_A, n=total_chunks) + silence(),
        ft,
        max_utterance_ms=cap_chunks * VADProcessor.CHUNK_MS,
    )

    assert len(ft.calls) == 2
    a_samples = sum(
        int(np.count_nonzero(np.isclose(np.abs(arr), MARK_A)))
        for call in ft.calls
        for arr in call["copy"]
    )
    # Every speech sample exactly once across the two calls — no overlap, no loss.
    assert a_samples == total_chunks * CHUNK
    assert ft.calls[0]["n"] == cap_chunks
    assert ft.calls[1]["n"] == (total_chunks - cap_chunks) + SIL_N


# ── VAD-level cap semantics ───────────────────────────────────────────────────


def test_vad_cap_finalizes_midspeech_and_keeps_collecting() -> None:
    vad = make_vad(max_utterance_ms=12 * VADProcessor.CHUNK_MS)
    loud = np.full(CHUNK, MARK_A, dtype=np.float32)

    completed = None
    for i in range(12):
        is_speech, completed = vad.process_chunk(loud)
        assert is_speech is True
        if i < 11:
            assert completed is None

    assert completed is not None and len(completed) == 12
    assert vad._speech_chunks == []      # take-and-reset happened atomically
    assert vad._in_speech is True        # the continuation is still one utterance

    # The very next chunk starts the NEW buffer — no re-arming of the energy
    # gate, no leftovers from the flushed part.
    _, again = vad.process_chunk(loud)
    assert again is None
    assert len(vad._speech_chunks) == 1


def test_silent_tail_after_forced_flush_is_never_transcribed() -> None:
    """Code review P2: speech stops within a chunk of the cap → the
    continuation buffer holds nothing but the trailing-silence window, which
    must be discarded, not handed to Whisper (it hallucinates on silence)."""
    ft = RecordingTranscriber()
    cap_chunks = 12
    run_worker(
        speech(MARK_A, n=cap_chunks) + silence(),   # flush at the cap, then pure silence
        ft,
        max_utterance_ms=cap_chunks * VADProcessor.CHUNK_MS,
    )

    assert len(ft.calls) == 1                       # the flush only — no silence call
    assert markers_in(ft.calls[0]["copy"]) == {MARK_A}


def test_quiet_continuation_after_forced_flush_survives_the_energy_gate() -> None:
    """Code review P3: staying in-speech after the flush is what lets a quiet
    continuation (voiced, but under the idle RMS gate) keep flowing."""

    class SensitiveWebRTC:
        def is_speech(self, pcm: bytes, rate: int) -> bool:
            return bool(np.abs(np.frombuffer(pcm, dtype="<i2")).max() > 100)

    cap = 12
    vad = VADProcessor(max_utterance_ms=cap * VADProcessor.CHUNK_MS)
    vad._vad = SensitiveWebRTC()
    loud = np.full(CHUNK, MARK_A, dtype=np.float32)
    quiet = np.full(CHUNK, 0.005, dtype=np.float32)   # < 0.006 idle gate

    for _ in range(cap):
        vad.process_chunk(loud)                       # forced flush at the cap
    for _ in range(SPEECH_N):
        vad.process_chunk(quiet)                      # would be gated away if idle

    completed = None
    for arr in silence():
        _, done = vad.process_chunk(arr)
        completed = completed or done
    assert completed is not None
    assert len(completed) == SPEECH_N + SIL_N
    # The quiet chunks themselves made it through: their exact amplitude is in
    # the work item, and nothing from the flushed loud part is.
    peaks = {float(np.abs(a).max()) for a in completed}
    assert any(abs(pk - 0.005) < 1e-6 for pk in peaks)
    assert all(abs(pk - MARK_A) > 1e-6 for pk in peaks)


def test_misconfigured_cap_is_clamped_to_min_speech() -> None:
    assert make_vad(max_utterance_ms=0).max_utterance_ms == 250
    assert make_vad(max_utterance_ms=8000).max_utterance_ms == 8000


def test_run_stdin_wires_cli_cap_into_the_vad(monkeypatch) -> None:
    created: dict = {}

    class FakeVAD:
        def __init__(self, **kwargs):
            created.update(kwargs)

        def load(self):
            raise RuntimeError("stop here")  # abort run_stdin after construction

    monkeypatch.setattr(aw, "VADProcessor", FakeVAD)
    args = argparse.Namespace(
        denoise=False, max_utterance_ms=4321, coreml=False, model="base",
        device="cpu",
    )
    with pytest.raises(SystemExit):
        aw.run_stdin(args)
    assert created.get("max_utterance_ms") == 4321


# ── Tests 4, 5(adapted), 6, 15: failure paths cannot resurrect audio ─────────


def test_transcribe_failure_does_not_resurrect_audio() -> None:
    ft = RecordingTranscriber(results={0: RuntimeError("decoder blew up")})
    vad, _ = run_worker(speech(MARK_A) + silence() + speech(MARK_B) + silence(), ft)

    assert len(ft.calls) == 2
    assert markers_in(ft.calls[1]["copy"]) == {MARK_B}   # B only — A is gone for good
    assert vad._speech_chunks == []


def test_live_buffer_is_already_empty_when_transcription_runs() -> None:
    """Design A: reset happens at handoff, BEFORE transcription — so an
    exception (or a cancellation, in an async architecture) at any point
    inside or after transcribe finds the live buffer already empty."""
    observed: list[list] = []

    class Probe(RecordingTranscriber):
        def __init__(self, vad: VADProcessor):
            super().__init__()
            self._vad = vad

        def transcribe(self, audio_chunks):
            observed.append(list(self._vad._speech_chunks))
            return super().transcribe(audio_chunks)

    vad = make_vad()
    ft = Probe(vad)
    run_worker(speech(MARK_A) + silence(), ft, vad=vad)

    assert observed == [[]]   # empty at the moment transcription starts


def test_empty_transcript_then_next_utterance_clean() -> None:
    ft = RecordingTranscriber(results={0: ("", 0.0)})
    _, lines = run_worker(speech(MARK_A) + silence() + speech(MARK_B) + silence(), ft)

    assert markers_in(ft.calls[1]["copy"]) == {MARK_B}
    transcripts = [ln for ln in lines if ln.get("transcript")]
    assert len(transcripts) == 1   # only B produced a transcript event


# ── Tests 7, 8: the completed work item is an isolated copy ──────────────────


def test_completed_work_item_is_an_isolated_copy() -> None:
    vad = make_vad()
    loud = np.full(CHUNK, MARK_A, dtype=np.float32)
    for _ in range(SPEECH_N):
        vad.process_chunk(loud)

    completed = None
    for arr in silence():
        _, done = vad.process_chunk(arr)
        if done is not None:
            completed = done
    assert completed is not None

    # Not the live list, and the live list is fresh.
    assert completed is not vad._speech_chunks
    snapshot = [a.copy() for a in completed]

    # A next utterance appends only to the new buffer and cannot touch the
    # handed-off work item.
    for _ in range(SPEECH_N):
        vad.process_chunk(np.full(CHUNK, MARK_B, dtype=np.float32))
    assert len(completed) == SPEECH_N + SIL_N
    for before, after in zip(snapshot, completed):
        assert np.array_equal(before, after)
    assert markers_in(completed) == {MARK_A}


def test_vad_copies_input_chunks_so_caller_mutation_is_harmless() -> None:
    vad = make_vad()
    chunk = np.full(CHUNK, MARK_A, dtype=np.float32)
    vad.process_chunk(chunk)
    chunk[:] = 0.99                      # caller reuses / mutates its array
    assert float(np.abs(vad._speech_chunks[0]).max()) == pytest.approx(MARK_A)


# ── Tests 9, 20: per-owner isolation (S1) ─────────────────────────────────────


def test_interleaved_owners_have_independent_buffers() -> None:
    """Each owner has their own worker process in production (S1); state is
    instance-local, so two interleaved sessions can never mix audio."""
    vad_a, vad_b = make_vad(), make_vad()
    a = np.full(CHUNK, MARK_A, dtype=np.float32)
    b = np.full(CHUNK, MARK_B, dtype=np.float32)

    for _ in range(SPEECH_N):            # strictly interleaved
        vad_a.process_chunk(a)
        vad_b.process_chunk(b)

    done_a = done_b = None
    for arr in silence():
        _, da = vad_a.process_chunk(arr)
        _, db = vad_b.process_chunk(arr)
        done_a, done_b = done_a or da, done_b or db

    assert done_a is not None and markers_in(done_a) == {MARK_A}
    assert done_b is not None and markers_in(done_b) == {MARK_B}


# ── Test 10: stream end mid-utterance leaves nothing behind ──────────────────


def test_stream_end_mid_utterance_transcribes_nothing_stale() -> None:
    # Half an utterance, then the connection dies (iterator ends). In
    # production the worker process exits with it, so all state dies too; a
    # reconnect gets a brand-new worker.
    ft1 = RecordingTranscriber()
    run_worker(speech(MARK_A, n=5), ft1)
    assert ft1.calls == []               # a partial utterance is never transcribed

    ft2 = RecordingTranscriber()         # the fresh worker after reconnect
    run_worker(speech(MARK_B) + silence(), ft2)
    assert len(ft2.calls) == 1
    assert markers_in(ft2.calls[0]["copy"]) == {MARK_B}


# ── Tests 12, 13: VAD silence semantics unchanged ─────────────────────────────


def test_finalizing_silence_yields_two_utterances() -> None:
    ft = RecordingTranscriber()
    run_worker(speech(MARK_A) + silence(SIL_N) + speech(MARK_B) + silence(SIL_N), ft)
    assert len(ft.calls) == 2


def test_short_gap_stays_one_utterance() -> None:
    # 13 silence chunks = 390 ms < MAX_SILENCE_MS (400): still the same utterance.
    ft = RecordingTranscriber()
    run_worker(speech(MARK_A) + silence(13) + speech(MARK_B) + silence(SIL_N), ft)

    assert len(ft.calls) == 1
    assert markers_in(ft.calls[0]["copy"]) == {MARK_A, MARK_B}
    assert ft.calls[0]["n"] == SPEECH_N + 13 + SPEECH_N + SIL_N


# ── Test 16: no transcript-level dedupe ───────────────────────────────────────


def test_identical_utterances_are_both_emitted() -> None:
    ft = RecordingTranscriber()          # returns "hey aria" for every call
    _, lines = run_worker(speech(MARK_A) + silence() + speech(MARK_B) + silence(), ft)

    transcripts = [ln["transcript"] for ln in lines if ln.get("transcript")]
    assert transcripts == ["hey aria", "hey aria"]   # repetition is legitimate speech


# ── Test 17 + wake/sleep interaction: sleep clears pending audio ──────────────


def test_sleep_clears_buffered_audio_and_emits_no_transcript(monkeypatch) -> None:
    fired: list[float] = []

    class ImmediateTimer:
        def __init__(self, interval: float, fn):
            fired.append(interval)
            self._fn = fn

        def start(self):
            self._fn()

    monkeypatch.setattr(aw.threading, "Timer", ImmediateTimer)
    ft = RecordingTranscriber(
        results={0: ("hey aria", 0.9), 1: ("that would be all", 0.9)}
    )
    vad, lines = run_worker(
        speech(MARK_A) + silence() + speech(MARK_B) + silence(), ft, vad=make_vad()
    )

    kinds = [ln.get("type") for ln in lines if ln.get("type")]
    assert "aria_sleep" in kinds
    transcripts = [ln for ln in lines if ln.get("transcript")]
    assert len(transcripts) == 1          # the sleep phrase itself is not emitted
    assert vad._speech_chunks == []       # clear() left nothing pending
    assert fired == [5.0]                 # the unmute timer was armed as before


def test_explicit_clear_resets_partial_utterance() -> None:  # Test 17
    vad = make_vad()
    for arr in speech(MARK_A, n=5):
        vad.process_chunk(arr)
    assert len(vad._speech_chunks) == 5
    vad.clear()
    assert vad._speech_chunks == [] and vad._in_speech is False

    for arr in speech(MARK_B) + silence():
        _, done = vad.process_chunk(arr)
        if done is not None:
            assert markers_in(done) == {MARK_B}


# ── Test 19: S2 — no speech content in logs ───────────────────────────────────


def test_no_transcript_content_in_worker_logs() -> None:
    ft = RecordingTranscriber()
    ft.default = (f"{PRIVATE} hey aria", 0.9)

    denoiser = mock.Mock(enabled=False)
    args = argparse.Namespace(denoise=False, max_utterance_ms=8000)
    vad = make_vad()
    out = io.StringIO()
    with capture_all_levels() as logs, contextlib.redirect_stdout(out):
        aw.process_audio_stream(
            iter(speech(MARK_A) + silence()), vad, ft, denoiser, args
        )

    rendered = "\n".join(repr(e) for e in logs)
    assert PRIVATE not in rendered        # stdout is the transport; logs carry counts
    done = next(e for e in logs if e.get("event") == "utterance completed")
    assert done["chunk_count"] == SPEECH_N + SIL_N
    assert done["audio_ms"] == (SPEECH_N + SIL_N) * VADProcessor.CHUNK_MS
    assert all(k not in done for k in ("transcript", "text", "pcm", "audio"))
