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
    WAKE_WORDS = {
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
    }
    SLEEP_PHRASES = {
        "that will be all",
        "that would be all",
        "go to sleep",
        "goodbye aria",
        "bye aria",
        "sleep aria",
        "shut down",
        "that's all",
        "thats all",
    }
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

                text_lower = text.lower().strip()
                contains_wake = any(w in text_lower for w in WAKE_WORDS)

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
                    text_lower_check = text.lower().strip()
                    if any(p in text_lower_check for p in SLEEP_PHRASES):
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
