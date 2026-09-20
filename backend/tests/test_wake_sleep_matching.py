"""V2 — wake/sleep detection matches whole words, not substrings.

Audit B6: wake/sleep used ``any(phrase in text.lower())``, so "maria" woke
ARIA and "that's allowed" slept it. The fix normalizes the transcript to
lowercase alphanumeric tokens and matches each configured phrase as a
contiguous run of whole tokens, so a phrase inside a larger word never fires.

Everything else is preserved exactly: on wake the FULL transcript is still
emitted (there has never been any wake-word stripping), a sleep phrase still
suppresses its own transcript, and the post-sleep gate, the 30 s inactivity
timeout and the mute/unmute timer are untouched. Transcripts here are mocked
strings; no microphone, no Whisper model.
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
from app.pipeline.audio_worker import (
    SLEEP_PHRASES,
    WAKE_WORDS,
    _contains_phrase,
    _tokens,
    matches_sleep,
    matches_wake,
)
from app.pipeline.vad import VADProcessor

PRIVATE = "PRIVATE_WAKE_TRANSCRIPT_7721"


# ── pure matcher: wake positives / negatives ─────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "aria",                       # Test 1
        "ARIA", "Aria",               # Test 17 case
        "ARIA!", "aria?", "aria,", "aria.", "aria...",   # Tests 2, 24
        "(aria)",                     # Test 24
        " aria ", "  aria  ",         # Test 16 whitespace
        "hey aria", "hi aria", "hey, aria", "hey   aria",  # Tests 4, 16
        "aria what time is it",       # Test 5 wake + command
        "aria aria are you there",    # Test 6 repeated
        "arya", "haria", "hey arya",  # configured homophone aliases
        "can you hear me aria",       # phrase not at the start
    ],
)
def test_wake_positives(text: str) -> None:
    assert matches_wake(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "maria", "Maria",             # Test 3 — the core false positive
        "bavaria", "malaria", "arian", "librarian",
        "the variable is set",        # "aria" inside "variable"
        "tell me about maria",        # Test 19 context
        "the aquarium",
        "",                           # Test 15 empty
        "what time is it",            # Test 11 normal awake speech
        "please summarize this",
    ],
)
def test_wake_negatives(text: str) -> None:
    assert matches_wake(text) is False


# ── pure matcher: sleep positives / negatives ────────────────────────────────


@pytest.mark.parametrize(
    "text",
    [
        "that would be all", "that will be all",   # Test 7
        "that would be all.", "that will be all!",  # Test 8
        "okay that would be all",     # phrase with a lead-in
        "go to sleep", "goodbye aria", "bye aria", "sleep aria", "shut down",
        "that's all", "thats all", "THAT'S ALL",
        "that’s all",             # curly apostrophe: casefold + token split handles it
        "that s all",               # apostrophe is a separator, so a stray STT space matches
        "go to sleep aria",
    ],
)
def test_sleep_positives(text: str) -> None:
    assert matches_sleep(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "that's allowed here",        # Test 9 — "that's all" inside "allowed"
        "we should go to sleeping bags",  # "go to sleep" inside "sleeping"
        "shutdown the old server",    # "shut down" inside "shutdown"
        "that will be alright",       # "that will be all" inside "alright"
        "good nighttime routine",
        "that was a good nightmare",
        "tell me tomorrow's weather", # Test 10 realistic false positive
        "",                           # Test 15 empty
        # Security review F1: dropping punctuation must not let a phrase span a
        # sentence boundary — a false sleep that substring matching never had.
        "I told him that; will be all set",
        "Does anyone remember that? Will be all we need.",
        "I doubt that. Will be all right tomorrow",
        # Code review #1: the phrase must be CONTIGUOUS, not merely a
        # subsequence — these are the cases a subsequence matcher would sleep on.
        "go to the bedroom and sleep",
        "we go to bed now to sleep",
    ],
)
def test_sleep_negatives(text: str) -> None:
    assert matches_sleep(text) is False


def test_phrase_cannot_span_a_sentence_boundary() -> None:
    from app.pipeline.audio_worker import _sentences

    assert _sentences("hello there. aria") == [["hello", "there"], ["aria"]]
    # Commas and dashes are not boundaries, so natural speech still matches.
    assert matches_wake("hey, aria") is True
    assert matches_sleep("that-would-be-all") is True


# ── tokenization / boundary semantics ────────────────────────────────────────


def test_tokenize_strips_punctuation_and_casefolds() -> None:
    assert _tokens("Hey, ARIA!") == ["hey", "aria"]
    assert _tokens("that's all...") == ["that", "s", "all"]
    assert _tokens("   ") == []
    assert _tokens("(aria)") == ["aria"]


def test_contains_phrase_requires_contiguous_run() -> None:
    assert _contains_phrase(["hey", "aria"], [("aria",)]) is True
    assert _contains_phrase(["maria"], [("aria",)]) is False
    assert _contains_phrase(["go", "to", "the", "sleep"], [("go", "to", "sleep")]) is False
    assert _contains_phrase(["please", "go", "to", "sleep"], [("go", "to", "sleep")]) is True
    assert _contains_phrase([], [("aria",)]) is False


def test_possessive_aria_still_wakes_via_token_split() -> None:
    # "aria's" tokenizes to ["aria", "s"], so the whole word "aria" is present.
    assert matches_wake("aria's schedule for today") is True


def test_configured_phrase_sets_are_used_unchanged() -> None:
    # V2 must not invent phrase lists.
    assert "aria" in WAKE_WORDS and "hey aria" in WAKE_WORDS
    assert "that would be all" in SLEEP_PHRASES and "shut down" in SLEEP_PHRASES


# ── integration: state transitions through process_audio_stream ──────────────


class ScriptedVAD:
    """One input chunk finalizes one utterance, so a scripted transcript list
    maps 1:1 to utterances — decoupling wake/sleep logic from VAD timing."""

    CHUNK_MS = VADProcessor.CHUNK_MS

    def __init__(self) -> None:
        self._muted = False
        self.cleared = 0

    def process_chunk(self, chunk: np.ndarray) -> tuple[bool, list[np.ndarray] | None]:
        if self._muted:
            return False, None
        return False, [chunk]

    def clear(self) -> None:
        self.cleared += 1

    def mute(self) -> None:
        self._muted = True

    def unmute(self) -> None:
        self._muted = False


@contextmanager
def _patched_timer(immediate: bool = False) -> Iterator[None]:
    """Stand in for the 5 s unmute Timer. ``immediate`` fires it at once, which
    is what lets a test reach the post-sleep gate: while the VAD is muted no
    utterance finalizes at all, so the gate is never consulted."""

    class _T:
        def __init__(self, interval: float, fn, *a, **k) -> None:
            self._fn = fn

        def start(self) -> None:
            if immediate:
                self._fn()

    with mock.patch.object(aw.threading, "Timer", _T):
        yield


def _noop_timer() -> Iterator[None]:
    return _patched_timer(immediate=False)


def run(
    scripted: list[str],
    *,
    clock: list[float] | None = None,
    unmute_immediately: bool = False,
) -> tuple[list[dict], ScriptedVAD]:
    """Drive the worker with one utterance per scripted transcript."""
    vad = ScriptedVAD()
    transcriber = mock.Mock()
    transcriber.transcribe.side_effect = [(t, 0.9) for t in scripted]
    denoiser = mock.Mock(enabled=False)
    args = argparse.Namespace(denoise=False, max_utterance_ms=8000)
    chunks = [np.full(VADProcessor.CHUNK_SAMPLES, 0.2, dtype=np.float32) for _ in scripted]

    saved = structlog.get_config()
    out = io.StringIO()
    ctx = mock.patch.object(aw.time, "time", side_effect=list(clock)) if clock else contextlib.nullcontext()
    try:
        aw.configure_worker_logging()
        with _patched_timer(unmute_immediately), ctx, contextlib.redirect_stdout(out):
            aw.process_audio_stream(iter(chunks), vad, transcriber, denoiser, args)
    finally:
        structlog.configure(**saved)
    lines = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    return lines, vad


def _emitted_transcripts(lines: list[dict]) -> list[str]:
    return [ln["transcript"] for ln in lines if ln.get("transcript")]


def _types(lines: list[dict]) -> list[str]:
    return [ln["type"] for ln in lines if ln.get("type")]


def test_idle_wakes_on_wake_word_and_emits_full_transcript() -> None:  # Tests 1, 5
    lines, _ = run(["aria what time is it"])
    assert "wake_word" in _types(lines)
    # Wake + command: the FULL transcript is emitted, wake word included (no strip).
    assert _emitted_transcripts(lines) == ["aria what time is it"]


def test_idle_ignores_wake_substring_false_positive() -> None:  # Test 3 core
    lines, _ = run(["the variable is set", "tell me about maria", "bavaria is nice"])
    assert "wake_word" not in _types(lines)
    assert _emitted_transcripts(lines) == []   # stayed asleep, nothing emitted


def test_idle_ignores_unrelated_speech() -> None:  # Test 12
    lines, _ = run(["what is the weather today"])
    assert _emitted_transcripts(lines) == [] and "wake_word" not in _types(lines)


def test_awake_sleeps_on_sleep_phrase_and_suppresses_transcript() -> None:  # Test 7
    lines, _ = run(["aria", "that would be all"])
    assert _types(lines) == ["wake_word", "aria_sleep"]
    # Only the wake utterance's transcript is emitted; the sleep phrase is not.
    assert _emitted_transcripts(lines) == ["aria"]


def test_awake_does_not_sleep_on_sleep_substring() -> None:  # Tests 9, 10 core
    lines, _ = run(["aria", "that's allowed here", "we should go to sleeping bags"])
    assert "aria_sleep" not in _types(lines)
    # Both awake utterances are emitted normally.
    assert _emitted_transcripts(lines) == ["aria", "that's allowed here", "we should go to sleeping bags"]


def test_repeated_wake_word_while_awake_is_normal_speech() -> None:  # Tests 6, 23
    lines, _ = run(["aria", "aria aria are you there"])
    assert _emitted_transcripts(lines) == ["aria", "aria aria are you there"]
    assert _types(lines) == ["wake_word"]   # only the first activation


def test_transcript_emitted_unchanged_no_stripping() -> None:  # Tests 18, 19
    lines, _ = run(["aria tell me about Maria"])
    # No wake-word stripping exists; "Maria" is preserved because the transcript
    # is never rewritten.
    assert _emitted_transcripts(lines) == ["aria tell me about Maria"]


def test_empty_transcript_changes_no_state() -> None:  # Test 15
    lines, vad = run(["", "aria"])
    assert "wake_word" in _types(lines)   # the empty one was a no-op, "aria" woke


def test_sleep_clears_vad_buffer() -> None:  # Test 20
    _, vad = run(["aria", "that would be all"])
    assert vad.cleared == 1   # sleep path called vad.clear()


def test_v1_buffer_empty_after_real_wake_utterance() -> None:  # Test 20 with real VAD
    from tests.test_audio_utterance_isolation import make_vad, silence, speech

    transcriber = mock.Mock()
    transcriber.transcribe.return_value = ("aria", 0.9)
    denoiser = mock.Mock(enabled=False)
    args = argparse.Namespace(denoise=False, max_utterance_ms=8000)
    vad = make_vad()
    with _noop_timer(), contextlib.redirect_stdout(io.StringIO()):
        aw.process_audio_stream(iter(speech(0.2) + silence()), vad, transcriber, denoiser, args)
    assert vad._speech_chunks == []   # V1 guarantee intact


# ── inactivity + post-sleep timers preserved ─────────────────────────────────


def test_inactivity_timeout_returns_to_idle() -> None:  # Test 13
    # now() sequence: wake@100, then @140 (>30s later) the second utterance
    # finds the session timed out, so a bare wake word is needed to re-emit.
    lines, _ = run(["aria", "what time is it"], clock=[100.0] * 3 + [140.0] * 3)
    # After the 30s inactivity gap the session is idle again, so a non-wake
    # utterance is ignored rather than emitted.
    assert _emitted_transcripts(lines) == ["aria"]


def test_post_sleep_gate_discards_wake_for_five_seconds() -> None:  # Test 14
    # wake@100, sleep@101 (post_sleep_until=106), wake attempt@104 (<106) discarded,
    # wake attempt@107 (>106) accepted.
    lines, _ = run(
        ["aria", "that would be all", "aria", "aria"],
        clock=[100.0] * 3 + [101.0] * 3 + [104.0] * 3 + [107.0] * 3,
        unmute_immediately=True,
    )
    # Two wake_word events: the first, and the one after the gate expires.
    assert _types(lines).count("wake_word") == 2


# ── S2 privacy ────────────────────────────────────────────────────────────────


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


def test_no_transcript_in_logs() -> None:  # Test 22
    vad = ScriptedVAD()
    transcriber = mock.Mock()
    transcriber.transcribe.side_effect = [(f"aria {PRIVATE}", 0.9)]
    denoiser = mock.Mock(enabled=False)
    args = argparse.Namespace(denoise=False, max_utterance_ms=8000)
    chunk = [np.full(VADProcessor.CHUNK_SAMPLES, 0.2, dtype=np.float32)]
    with capture_all_levels() as logs, _noop_timer(), contextlib.redirect_stdout(io.StringIO()):
        aw.process_audio_stream(iter(chunk), vad, transcriber, denoiser, args)
    assert PRIVATE not in "\n".join(repr(e) for e in logs)
