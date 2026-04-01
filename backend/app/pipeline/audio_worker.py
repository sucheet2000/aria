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
import threading
import time

import structlog
import numpy as np

from app.pipeline.vad import VADProcessor
from app.pipeline.transcriber import Transcriber
from app.pipeline.denoiser import Denoiser

CHUNK_MS = 30
SAMPLE_RATE = 16000
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_MS / 1000)  # 480
MAX_UTTERANCE_MS = 8000

logger = structlog.get_logger()

_stop = False
_sleep_until: float = 0.0


def _handle_sigterm(signum: int, frame: object) -> None:
    global _stop
    _stop = True


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


def find_best_input_device() -> int | None:
    """
    Return the system default input device.
    This respects whatever the user has set in System Settings > Sound > Input.
    AirPods, MacBook mic, or any other device selected by the user will be used.
    Returns None to let sounddevice use the system default directly.
    """
    import sounddevice as sd
    try:
        default_input = sd.default.device[0]
        if default_input >= 0:
            device_info = sd.query_devices(default_input)
            logger.info(
                "using system default input device",
                device=default_input,
                name=device_info['name'],
            )
            return default_input
    except Exception:
        pass
    return None


def _watch_stdin(vad: VADProcessor) -> None:
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if cmd.get("mute") is True:
            vad.mute()
        elif cmd.get("mute") is False:
            if time.time() >= _sleep_until:
                vad.unmute()


def run_microphone(args: argparse.Namespace) -> None:
    import queue
    import sounddevice as sd

    vad = VADProcessor()
    if args.coreml:
        from app.pipeline.whisper_coreml import WhisperCoreML
        transcriber = WhisperCoreML(model_size=args.model)
    else:
        transcriber = Transcriber(model_size=args.model)
    denoiser = Denoiser()

    try:
        vad.load()
    except Exception as exc:
        print(f"VAD load error: {exc}", file=sys.stderr)
        sys.exit(1)

    threading.Thread(target=_watch_stdin, args=(vad,), daemon=True).start()

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

    audio_queue: queue.Queue[np.ndarray] = queue.Queue()

    device = args.device if args.device is not None else find_best_input_device()

    device_info = sd.query_devices(device)
    native_sr = int(device_info['default_samplerate'])
    capture_sr = [native_sr]

    logger.info(
        "audio capture config",
        device=device,
        capture_sr=native_sr,
        target_sr=SAMPLE_RATE,
    )

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

    def audio_callback(
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            print(f"audio status: {status}", file=sys.stderr)
        audio_queue.put(indata[:, 0].copy())

    speech_chunks: list[np.ndarray] = []
    silence_ms: int = 0
    in_speech: bool = False
    _consecutive_transcribe_errors: int = 0
    _MAX_CONSECUTIVE_ERRORS = 5

    with sd.InputStream(
        samplerate=native_sr,
        channels=1,
        dtype="float32",
        blocksize=int(native_sr * CHUNK_MS / 1000),
        device=device,
        callback=audio_callback,
    ):
        while not _stop:
            try:
                chunk = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if native_sr != SAMPLE_RATE:
                target_len = CHUNK_SAMPLES
                chunk = np.interp(
                    np.linspace(0, len(chunk) - 1, target_len),
                    np.arange(len(chunk)),
                    chunk,
                ).astype(np.float32)

            chunk_f32 = chunk  # float32 in [-1.0, 1.0], resampled to 16kHz
            is_speech_frame, completed = vad.process_chunk(chunk_f32)

            if is_speech_frame:
                speech_chunks.append(chunk_f32)
                in_speech = True
                silence_ms = 0

                total_ms = len(speech_chunks) * VADProcessor.CHUNK_MS
                if total_ms >= args.max_utterance_ms:
                    completed = list(speech_chunks)
                    speech_chunks = []
                    silence_ms = 0
                    in_speech = True

            if completed is not None:
                t0 = time.time()

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
                    print(f"transcribe error: {exc}", file=sys.stderr)
                    if _consecutive_transcribe_errors >= _MAX_CONSECUTIVE_ERRORS:
                        print(
                            f"FATAL: {_consecutive_transcribe_errors} consecutive "
                            "transcription errors — exiting so supervisor can restart",
                            file=sys.stderr,
                        )
                        sys.exit(1)
                    continue

                duration_ms = int((time.time() - t0) * 1000)
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
                            global _sleep_until
                            mode = "idle"
                            last_transcript_time = 0.0
                            _sleep_until = now + 5.0
                            post_sleep_until = now + 5.0
                            vad.clear()   # discard buffered audio
                            vad.mute()
                            sleep_event = {"type": "aria_sleep", "timestamp": round(now, 3)}
                            print(json.dumps(sleep_event), flush=True)
                            # Unmute after 3 seconds to allow queued audio to drain
                            threading.Timer(5.0, vad.unmute).start()
                            # Do not send the transcript — just the sleep event
                        else:
                            print(json.dumps(state), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="ARIA audio worker")
    parser.add_argument("--model", type=str, default="base")
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="sounddevice input device index (overrides auto-detection)",
    )
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

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if args.synthetic:
        run_synthetic(args)
    else:
        run_microphone(args)


if __name__ == "__main__":
    main()
