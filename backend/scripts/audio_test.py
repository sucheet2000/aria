"""
Developer test script for the audio pipeline.
Runs VAD + Whisper live from the microphone and prints transcripts to terminal.
Press Ctrl+C to stop.

Usage:
    python3 scripts/audio_test.py
"""
from __future__ import annotations

import sys
import time

import numpy as np

sys.path.insert(0, ".")

from app.pipeline.vad import VADProcessor
from app.pipeline.transcriber import Transcriber

CHUNK_SAMPLES = VADProcessor.CHUNK_SAMPLES
SAMPLE_RATE = VADProcessor.SAMPLE_RATE


def main() -> None:
    import pyaudio

    vad = VADProcessor()
    transcriber = Transcriber(model_size="base")

    print("Loading VAD...")
    vad.load()
    print("Loading Whisper model...")
    transcriber.load()
    print("Ready. Speak into the microphone. Press Ctrl+C to stop.\n")

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SAMPLES,
    )

    try:
        while True:
            try:
                raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            except Exception as exc:
                print(f"stream read error: {exc}", file=sys.stderr)
                break

            chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            is_speech, completed = vad.process_chunk(chunk)

            if completed is not None:
                t0 = time.time()
                text, confidence = transcriber.transcribe(completed)
                elapsed_ms = int((time.time() - t0) * 1000)

                if text:
                    ts = time.strftime("%H:%M:%S")
                    print(
                        f"[{ts}] transcript={text!r}  "
                        f"confidence={confidence:.3f}  "
                        f"processing_ms={elapsed_ms}"
                    )
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


if __name__ == "__main__":
    main()
