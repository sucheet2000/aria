"""
Standalone audio worker subprocess.
Run directly by the Go server. Writes one JSON line per transcript to stdout.
All errors and debug output go to stderr only.
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time

import numpy as np

from app.pipeline.vad import VADProcessor
from app.pipeline.transcriber import Transcriber

CHUNK_MS = 30
SAMPLE_RATE = 16000
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 480

_stop = False


def _handle_sigterm(signum: int, frame: object) -> None:
    global _stop
    _stop = True


def run_synthetic(args: argparse.Namespace) -> None:
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


def run_microphone(args: argparse.Namespace) -> None:
    import queue
    import sounddevice as sd

    vad = VADProcessor()
    transcriber = Transcriber(model_size=args.model)

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

    audio_queue: queue.Queue[np.ndarray] = queue.Queue()

    def audio_callback(
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            print(f"audio status: {status}", file=sys.stderr)
        audio_queue.put(indata[:, 0].copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=CHUNK_SAMPLES,
        device=args.device if args.device != 0 else None,
        callback=audio_callback,
    ):
        while not _stop:
            try:
                chunk = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            chunk_f32 = chunk.astype("float32") / 32768.0
            is_speech, completed = vad.process_chunk(chunk_f32)

            if completed is not None:
                t0 = time.time()
                try:
                    text, confidence = transcriber.transcribe(completed)
                except Exception as exc:
                    print(f"transcribe error: {exc}", file=sys.stderr)
                    continue

                duration_ms = int((time.time() - t0) * 1000)
                if text:
                    state = {
                        "transcript": text,
                        "is_final": True,
                        "confidence": confidence,
                        "duration_ms": duration_ms,
                        "timestamp": round(time.time(), 3),
                    }
                    print(json.dumps(state), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="ARIA audio worker")
    parser.add_argument("--model", type=str, default="base")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--synthetic", action="store_true", default=False)
    parser.add_argument("--duration", type=float, default=0.0)
    args = parser.parse_args()

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if args.synthetic:
        run_synthetic(args)
    else:
        run_microphone(args)


if __name__ == "__main__":
    main()
