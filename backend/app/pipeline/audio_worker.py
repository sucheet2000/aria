"""
Standalone audio worker subprocess.
Run directly by the Go server. Reads raw 16 kHz mono Int16 PCM (little-endian)
from stdin — streamed by the browser mic over the /ws/audio WebSocket and
forwarded by the Go audio edge — and writes one JSON line per transcript to
stdout. All errors and debug output go to stderr only.
"""
from __future__ import annotations

import argparse
import json
import re
import signal
import sys
import threading
import time
from collections.abc import Iterator
from typing import BinaryIO

import numpy as np
import structlog

from app.config import settings
from app.observability.logging import configure_logging
from app.pipeline.denoiser import Denoiser
from app.pipeline.transcriber import Transcriber
from app.pipeline.vad import VADProcessor

CHUNK_MS = 30
SAMPLE_RATE = 16000
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 480
CHUNK_BYTES = CHUNK_SAMPLES * 2  # int16 little-endian
MAX_UTTERANCE_MS = 8000

logger = structlog.get_logger()

_stop = False

# ── Wake / sleep phrase matching (V2) ────────────────────────────────────────
# These are the configured phrases, unchanged. What changed is HOW they are
# matched: audit B6 used ``phrase in text.lower()``, so "maria" woke ARIA and
# "that's allowed" slept it. A phrase now has to appear as a contiguous run of
# whole tokens, which cannot happen inside a larger word.
WAKE_WORDS = frozenset({
    "aria",
    "hey aria",
    "hi aria",
    "area",
    "hey area",
    "hi area",
    "arya",
    "hey arya",
    "harya",
    "haria",
})
SLEEP_PHRASES = frozenset({
    "that will be all",
    "that would be all",
    "go to sleep",
    "goodbye aria",
    "bye aria",
    "sleep aria",
    "shut down",
    "that's all",
    "thats all",
})

# Runs of letters/digits only, so punctuation and whitespace are separators and
# casefold gives Unicode-safe lowercasing. Apostrophes split too, and because
# phrases are tokenized the same way "that's all" -> ("that", "s", "all")
# matches the spoken form either way, while "that's allowed" does not.
# Linear scan, no alternation or nesting: no backtracking risk.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# A phrase may not span a sentence boundary. Without this, dropping punctuation
# would let "I told him that; will be all set" match "that will be all" —
# a false sleep that plain substring matching never had. Commas and dashes are
# NOT boundaries, so "hey, aria" and "that-would-be-all" still match.
_SENTENCE_BREAK_RE = re.compile(r"[.!?;:]+")


def _tokens(text: str) -> list[str]:
    """Normalize a transcript to comparable lowercase word tokens."""
    return _TOKEN_RE.findall(text.casefold())


def _sentences(text: str) -> list[list[str]]:
    """Tokenize into one token list per sentence-like segment."""
    return [_tokens(part) for part in _SENTENCE_BREAK_RE.split(text)]


def _phrase_tokens(phrases: frozenset[str]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(_tokens(p)) for p in sorted(phrases))


# Tokenized once at import; matching reads only these. Rebinding WAKE_WORDS or
# SLEEP_PHRASES at runtime would therefore have no effect.
_WAKE_TOKENS = _phrase_tokens(WAKE_WORDS)
_SLEEP_TOKENS = _phrase_tokens(SLEEP_PHRASES)


def _contains_phrase(
    tokens: list[str], phrases: tuple[tuple[str, ...], ...]
) -> bool:
    """True when any phrase appears as a contiguous run of whole tokens."""
    for phrase in phrases:
        span = len(phrase)
        if not span:
            continue
        for start in range(len(tokens) - span + 1):
            if tuple(tokens[start:start + span]) == phrase:
                return True
    return False


def matches_wake(text: str) -> bool:
    """True when a wake phrase appears as whole words within one sentence."""
    return any(_contains_phrase(s, _WAKE_TOKENS) for s in _sentences(text))


def matches_sleep(text: str) -> bool:
    """True when a sleep phrase appears as whole words within one sentence."""
    return any(_contains_phrase(s, _SLEEP_TOKENS) for s in _sentences(text))


def _handle_sigterm(signum: int, frame: object) -> None:
    global _stop
    _stop = True


def configure_worker_logging() -> None:
    """Route this process's logs to stderr at the environment's level.

    stdout is reserved for the JSON transcript lines the Go edge forwards to
    the browser; a log record there would be misread as a transcript (S2).
    """
    configure_logging(settings.ENV, stream=sys.stderr)


def run_synthetic(args: argparse.Namespace) -> None:
    print(
        f"synthetic mode, denoise={'on' if args.denoise else 'off'}",
        file=sys.stderr,
        flush=True,
    )
    start = time.time()
    last = 0.0
    interval = 3.0

    while True:
        if _stop:
            break
        now = time.time()
        if args.duration > 0 and (now - start) >= args.duration:
            break
        if now - last < interval:
            time.sleep(0.05)
            continue
        last = now

        state = {
            "transcript": "this is a synthetic test transcript",
            "is_final": True,
            "confidence": 0.95,
            "duration_ms": 150,
            "timestamp": round(now, 3),
        }
        print(json.dumps(state), flush=True)


def read_pcm_chunks(stream: BinaryIO) -> Iterator[np.ndarray]:
    """Yield fixed-size float32 chunks from a binary Int16 PCM stream.

    The browser streams 16 kHz mono little-endian Int16 PCM in ~20-40 ms frames;
    they are re-framed here into exactly CHUNK_SAMPLES-sample float32 chunks in
    [-1.0, 1.0] — the same shape the old mic capture callback produced — so the
    VAD/whisper path downstream is unchanged. An incomplete trailing frame is
    buffered until it fills, and dropped at end-of-stream.
    """
    buf = bytearray()
    while not _stop:
        data = stream.read(CHUNK_BYTES)
        if not data:
            break
        buf.extend(data)
        while len(buf) >= CHUNK_BYTES:
            frame = bytes(buf[:CHUNK_BYTES])
            del buf[:CHUNK_BYTES]
            samples = np.frombuffer(frame, dtype="<i2").astype(np.float32)
            yield samples / np.float32(32768.0)


def process_audio_stream(
    chunks: Iterator[np.ndarray],
    vad: VADProcessor,
    transcriber: Transcriber,
    denoiser: Denoiser,
    args: argparse.Namespace,
) -> None:
    ACTIVE_TIMEOUT_S = 30.0
    mode = "idle"  # "idle" or "active"
    last_transcript_time = 0.0
    post_sleep_until = 0.0

    _consecutive_transcribe_errors: int = 0
    _MAX_CONSECUTIVE_ERRORS = 5

    for chunk_f32 in chunks:
        if _stop:
            break

        # V1: the VAD is the sole owner of the utterance buffer; every
        # finalization path take-and-resets inside process_chunk, so the live
        # buffer is already empty here. This loop keeps no speech buffer (B5).
        _is_speech, completed = vad.process_chunk(chunk_f32)

        if completed is not None:
            t0 = time.time()
            # S2: counts and duration only — never audio or text.
            logger.debug(
                "utterance completed",
                chunk_count=len(completed),
                audio_ms=len(completed) * VADProcessor.CHUNK_MS,
            )

            if args.denoise and denoiser.enabled:
                audio_array = np.concatenate(completed)
                cleaned = denoiser.enhance(audio_array)
                completed = [cleaned]
                denoiser.reset()

            try:
                text, confidence = transcriber.transcribe(completed)
                _consecutive_transcribe_errors = 0
            except Exception as exc:
                _consecutive_transcribe_errors += 1
                # S2: classify the failure; never interpolate the exception
                # message (a decoder error could quote audio-derived text).
                logger.warning(
                    "transcribe failed",
                    error_type=type(exc).__name__,
                    consecutive_errors=_consecutive_transcribe_errors,
                )
                if _consecutive_transcribe_errors >= _MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "transcribe failed repeatedly, exiting so supervisor can restart",
                        consecutive_errors=_consecutive_transcribe_errors,
                    )
                    sys.exit(1)
                continue

            duration_ms = int((time.time() - t0) * 1000)
            # S2: transcript text is written to stdout as the transport to Go
            # only; logs carry size and timing.
            logger.debug(
                "transcription complete",
                chars=len(text),
                duration_ms=duration_ms,
                confidence=confidence,
            )
            if text:
                now = time.time()
                state = {
                    "transcript": text,
                    "is_final": True,
                    "confidence": confidence,
                    "duration_ms": duration_ms,
                    "timestamp": round(now, 3),
                }

                if mode == "active" and (now - last_transcript_time) > ACTIVE_TIMEOUT_S:
                    mode = "idle"

                contains_wake = matches_wake(text)

                if mode == "idle":
                    if now < post_sleep_until:
                        pass  # discard, stay idle during post-sleep gate
                    elif contains_wake:
                        mode = "active"
                        last_transcript_time = now
                        wake_event = {"type": "wake_word", "timestamp": round(now, 3)}
                        print(json.dumps(wake_event), flush=True)
                        print(json.dumps(state), flush=True)
                    # else: ignore transcript in idle mode
                else:
                    last_transcript_time = now
                    if matches_sleep(text):
                        mode = "idle"
                        last_transcript_time = 0.0
                        post_sleep_until = now + 5.0
                        vad.clear()   # discard buffered audio
                        vad.mute()
                        sleep_event = {"type": "aria_sleep", "timestamp": round(now, 3)}
                        print(json.dumps(sleep_event), flush=True)
                        # Unmute after 5 seconds to allow queued audio to drain
                        threading.Timer(5.0, vad.unmute).start()
                        # Do not send the transcript — just the sleep event
                    else:
                        print(json.dumps(state), flush=True)


def run_stdin(args: argparse.Namespace) -> None:
    vad = VADProcessor(max_utterance_ms=args.max_utterance_ms)
    transcriber: Transcriber
    if args.coreml:
        from app.pipeline.whisper_coreml import WhisperCoreML
        transcriber = WhisperCoreML(model_size=args.model)  # type: ignore[assignment]
    else:
        transcriber = Transcriber(model_size=args.model)
    denoiser = Denoiser()

    try:
        vad.load()
    except Exception as exc:
        print(f"VAD load error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        transcriber.load()
    except Exception as exc:
        print(f"Transcriber load error: {exc}", file=sys.stderr)
        sys.exit(1)

    backend = "coreml" if (args.coreml and getattr(transcriber, "_use_coreml", False)) else "faster-whisper"
    logger.info("transcription backend active", backend=backend)

    if args.denoise:
        denoiser.load()
        if denoiser.enabled:
            print("denoiser active", file=sys.stderr, flush=True)
        else:
            print(
                "denoiser requested but unavailable, continuing without",
                file=sys.stderr,
                flush=True,
            )

    logger.info("audio capture from stdin", sample_rate=SAMPLE_RATE, chunk_ms=CHUNK_MS)

    process_audio_stream(read_pcm_chunks(sys.stdin.buffer), vad, transcriber, denoiser, args)


def main() -> None:
    parser = argparse.ArgumentParser(description="ARIA audio worker")
    parser.add_argument("--model", type=str, default="base")
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--synthetic", action="store_true", default=False)
    parser.add_argument("--duration", type=float, default=0.0)
    parser.add_argument(
        "--denoise",
        action="store_true",
        default=False,
        help="enable DeepFilterNet noise suppression",
    )
    parser.add_argument(
        "--max-utterance-ms",
        type=int,
        default=MAX_UTTERANCE_MS,
        help="maximum utterance length before forced flush (ms)",
    )
    parser.add_argument(
        "--coreml",
        action="store_true",
        default=False,
        help=(
            "use CoreML encoder + CPU decoder for STT (ANE-routable on M1). "
            "Defaults to False. Only use if ANE utilization is confirmed via "
            "Instruments — benchmark first with backend/scripts/benchmark_whisper.py"
        ),
    )
    args = parser.parse_args()

    configure_worker_logging()
    signal.signal(signal.SIGTERM, _handle_sigterm)

    if args.synthetic:
        run_synthetic(args)
    else:
        run_stdin(args)


if __name__ == "__main__":
    main()
