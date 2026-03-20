"""
Developer test script for the audio pipeline.
Runs VAD + Whisper live from the microphone and prints transcripts to terminal.
Press Ctrl+C to stop.

Usage:
    python3 scripts/audio_test.py [--denoise] [--max-utterance-ms 8000]
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np

sys.path.insert(0, ".")

from app.pipeline.vad import VADProcessor
from app.pipeline.transcriber import Transcriber
from app.pipeline.denoiser import Denoiser

CHUNK_SAMPLES = VADProcessor.CHUNK_SAMPLES
SAMPLE_RATE = VADProcessor.SAMPLE_RATE


def main() -> None:
    parser = argparse.ArgumentParser(description="ARIA audio pipeline test")
    parser.add_argument(
        "--denoise",
        action="store_true",
        default=False,
        help="enable DeepFilterNet noise suppression",
    )
    parser.add_argument(
        "--max-utterance-ms",
        type=int,
        default=8000,
        help="maximum utterance length before forced flush (ms)",
    )
    args = parser.parse_args()

    import pyaudio

    vad = VADProcessor()
    transcriber = Transcriber(model_size="base")
    denoiser = Denoiser()

    print("Loading VAD...")
    vad.load()
    print("Loading Whisper model...")
    transcriber.load()

    if args.denoise:
        print("Loading denoiser...")
        denoiser.load()

    denoise_status = "on" if (args.denoise and denoiser.enabled) else "off"
    print(
        f"Ready. denoise={denoise_status}  max_utterance_ms={args.max_utterance_ms}"
        f"  Speak into the microphone. Press Ctrl+C to stop.\n"
    )

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SAMPLES,
    )

    try:
        speech_chunks: list[np.ndarray] = []

        while True:
            try:
                raw = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            except Exception as exc:
                print(f"stream read error: {exc}", file=sys.stderr)
                break

            chunk = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            t_vad_start = time.time()
            is_speech, completed = vad.process_chunk(chunk)
            vad_ms = int((time.time() - t_vad_start) * 1000)

            if is_speech:
                speech_chunks.append(chunk)
                total_ms = len(speech_chunks) * VADProcessor.CHUNK_MS
                if total_ms >= args.max_utterance_ms:
                    completed = list(speech_chunks)
                    speech_chunks = []

            if completed is not None:
                denoise_ms = 0
                if args.denoise and denoiser.enabled:
                    t_denoise_start = time.time()
                    audio_array = np.concatenate(completed)
                    cleaned = denoiser.enhance(audio_array)
                    completed = [cleaned]
                    denoiser.reset()
                    denoise_ms = int((time.time() - t_denoise_start) * 1000)

                t_whisper_start = time.time()
                text, confidence = transcriber.transcribe(completed)
                whisper_ms = int((time.time() - t_whisper_start) * 1000)

                if text:
                    ts = time.strftime("%H:%M:%S")
                    print(
                        f"[{ts}] transcript={text!r}  "
                        f"confidence={confidence:.3f}  "
                        f"VAD: {vad_ms}ms | Denoise: {denoise_ms}ms | Whisper: {whisper_ms}ms"
                    )
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()


if __name__ == "__main__":
    main()
