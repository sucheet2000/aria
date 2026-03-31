"""
Benchmark faster-whisper vs CoreML hybrid on a synthetic 3s audio clip.

Usage (from repo root):
    PYTHONPATH=backend python3 backend/scripts/benchmark_whisper.py

Outputs:
    backend/benchmarks/whisper_latency.json  — machine-readable results
    stdout                                    — human-readable table

The benchmark result is ground truth.
If the CoreML hybrid path is SLOWER than faster-whisper end-to-end,
the JSON will include a 'recommendation' field warning against --coreml
and a 'coreml_faster' field set to false.
"""
from __future__ import annotations

import json
import pathlib
import platform
import statistics
import subprocess
import sys
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

SAMPLE_RATE = 16000
CLIP_SECONDS = 3
N_RUNS = 20
BENCHMARKS_DIR = pathlib.Path(__file__).parent.parent / "benchmarks"
OUTPUT_PATH = BENCHMARKS_DIR / "whisper_latency.json"
ENCODER_PATH = pathlib.Path(__file__).parent.parent / "models" / "whisper-tiny-encoder.mlpackage"
# Must match Transcriber.BASE_DOMAIN_PROMPT and WhisperCoreML._transcribe_coreml() prompt
DOMAIN_PROMPT = (
    "Software engineering, Go, Python, TypeScript, React, Next.js, "
    "ARIA, machine learning, neural networks, MediaPipe, WebSocket, "
    "FastAPI, ChromaDB, memory, vision, gesture, avatar"
)


def detect_hardware() -> str:
    """Query the actual chip name at runtime; never hardcode."""
    try:
        chip = subprocess.check_output(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
        if chip:
            return chip
    except Exception:
        pass
    return platform.processor() or f"{platform.machine()} / {platform.system()}"


def make_synthetic_audio(seconds: float = 3.0, sr: int = SAMPLE_RATE) -> np.ndarray:
    """440Hz sine + Gaussian noise, float32 [-1, 1]."""
    t = np.linspace(0, seconds, int(sr * seconds), dtype=np.float32)
    sine = 0.3 * np.sin(2 * np.pi * 440 * t)
    noise = 0.05 * np.random.default_rng(42).standard_normal(len(t)).astype(np.float32)
    return np.clip(sine + noise, -1.0, 1.0)


def percentile(data: list[float], p: float) -> float:
    data_sorted = sorted(data)
    idx = (len(data_sorted) - 1) * p / 100.0
    lo = int(idx)
    hi = min(lo + 1, len(data_sorted) - 1)
    frac = idx - lo
    return data_sorted[lo] * (1 - frac) + data_sorted[hi] * frac


def stats(latencies: list[float]) -> dict:
    return {
        "mean_ms":  round(statistics.mean(latencies), 1),
        "p50_ms":   round(percentile(latencies, 50), 1),
        "p95_ms":   round(percentile(latencies, 95), 1),
        "p99_ms":   round(percentile(latencies, 99), 1),
        "min_ms":   round(min(latencies), 1),
        "max_ms":   round(max(latencies), 1),
        "n_runs":   len(latencies),
    }


def benchmark_faster_whisper(audio: np.ndarray) -> tuple[dict, str]:
    from faster_whisper import WhisperModel
    print(f"\n[faster-whisper] loading model (tiny, cpu, int8)…")
    model = WhisperModel("tiny", device="cpu", compute_type="int8")

    # Decode settings must match Transcriber and WhisperCoreML production settings
    _decode_kwargs = dict(
        language="en",
        beam_size=5,
        vad_filter=False,
        word_timestamps=False,
        initial_prompt=DOMAIN_PROMPT,
        condition_on_previous_text=True,
    )

    # Warmup
    segs, _ = model.transcribe(audio, **_decode_kwargs)
    warmup_text = " ".join(s.text for s in segs).strip()
    print(f"  warmup transcript: {warmup_text!r}")

    latencies = []
    for i in range(N_RUNS):
        t0 = time.perf_counter()
        segs, _ = model.transcribe(audio, **_decode_kwargs)
        _ = list(segs)  # consume generator to complete inference
        latencies.append((time.perf_counter() - t0) * 1000)
        sys.stdout.write(f"\r  run {i+1}/{N_RUNS}  last={latencies[-1]:.0f}ms")
        sys.stdout.flush()
    print()
    return stats(latencies), warmup_text


def benchmark_coreml(audio: np.ndarray) -> tuple[dict, str] | tuple[None, str]:
    if not ENCODER_PATH.exists():
        return None, "encoder .mlpackage not found — skipped"

    print(f"\n[coreml] loading encoder + whisper decoder…")
    try:
        import coremltools as ct
        import torch
        import whisper as openai_whisper
        from whisper.decoding import DecodingOptions, decode
    except ImportError as e:
        return None, f"import failed: {e}"

    coreml_encoder = ct.models.MLModel(str(ENCODER_PATH))
    whisper_model = openai_whisper.load_model("tiny").eval()

    def run_once(audio_arr: np.ndarray) -> None:
        audio_padded = openai_whisper.pad_or_trim(audio_arr)
        mel = openai_whisper.log_mel_spectrogram(audio_padded)
        mel_np = mel.numpy().astype(np.float32)[np.newaxis]
        enc_out = coreml_encoder.predict({"mel": mel_np})["encoder_output"]
        encoder_output = torch.from_numpy(enc_out)
        # Match WhisperCoreML._transcribe_coreml() settings exactly so the
        # benchmark represents production-equivalent decode workload.
        options = DecodingOptions(
            language="en",
            fp16=False,
            beam_size=5,
            prompt=DOMAIN_PROMPT,
        )
        results = decode(whisper_model, encoder_output, options)
        return results[0].text.strip() if results else ""

    print("  warmup…")
    warmup_text = run_once(audio)
    print(f"  warmup transcript: {warmup_text!r}")

    latencies = []
    for i in range(N_RUNS):
        t0 = time.perf_counter()
        run_once(audio)
        latencies.append((time.perf_counter() - t0) * 1000)
        sys.stdout.write(f"\r  run {i+1}/{N_RUNS}  last={latencies[-1]:.0f}ms")
        sys.stdout.flush()
    print()
    return stats(latencies), warmup_text


def print_table(fw_stats: dict, cml_stats: dict | None) -> None:
    headers = ["metric", "faster-whisper", "coreml hybrid"]
    rows = ["mean_ms", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]
    col_w = [14, 16, 14]
    sep = "┼".join("─" * w for w in col_w)
    header_row = "│".join(h.ljust(col_w[i]) for i, h in enumerate(headers))
    print(f"\n{'─' * sum(col_w)}")
    print(header_row)
    print(sep)
    for row in rows:
        fw_val = f"{fw_stats[row]:.1f}" if fw_stats else "—"
        cml_val = f"{cml_stats[row]:.1f}" if cml_stats else "— (skipped)"
        print(
            f"{row.ljust(col_w[0])}"
            f"│{fw_val.ljust(col_w[1])}"
            f"│{cml_val.ljust(col_w[2])}"
        )
    print(f"{'─' * sum(col_w)}\n")


def main() -> None:
    print("Generating 3s synthetic audio clip…")
    audio = make_synthetic_audio()

    fw_stats, fw_text = benchmark_faster_whisper(audio)
    cml_stats, cml_note = benchmark_coreml(audio)

    print_table(fw_stats, cml_stats)

    # --- ground-truth comparison ---
    result: dict = {
        "hardware": detect_hardware(),
        "audio_clip_seconds": CLIP_SECONDS,
        "n_runs": N_RUNS,
        "model": "whisper-tiny",
        "decode_parity": True,
        "decode_parity_note": (
            "Both paths use beam_size=5 and the same domain prompt, "
            "matching production WhisperCoreML._transcribe_coreml() and Transcriber settings."
        ),
        "ane_utilization_measured": False,
        "ane_validation_note": (
            "Latency alone does not prove ANE execution. "
            "Run Instruments > Metal System Trace to confirm ANE routing."
        ),
        "faster_whisper": fw_stats,
        "coreml_hybrid": cml_stats if cml_stats else {"skipped": True, "reason": cml_note},
    }

    if cml_stats:
        coreml_faster = cml_stats["mean_ms"] < fw_stats["mean_ms"]
        result["coreml_faster"] = coreml_faster
        result["ane_recommendation"] = (
            "validate ANE routing via Instruments before claiming ANE speedup"
        )

        if coreml_faster:
            speedup = fw_stats["mean_ms"] / cml_stats["mean_ms"]
            result["latency_recommendation"] = (
                "CoreML latency is lower on this hardware. "
                "Do NOT enable --coreml in production until ANE utilization "
                "is confirmed via Instruments > Metal System Trace."
            )
            result["recommendation"] = (
                f"CoreML hybrid is {speedup:.2f}x faster than faster-whisper "
                f"({cml_stats['mean_ms']:.1f}ms vs {fw_stats['mean_ms']:.1f}ms) "
                f"on this hardware — latency only, ANE routing unverified. "
                f"Confirm ANE utilization via Instruments before enabling --coreml."
            )
            print(f"✓ CoreML hybrid is FASTER: {speedup:.2f}x speedup "
                  f"({cml_stats['mean_ms']:.1f}ms vs {fw_stats['mean_ms']:.1f}ms mean)")
        else:
            slowdown = cml_stats["mean_ms"] / fw_stats["mean_ms"]
            result["latency_recommendation"] = (
                "do not use --coreml — hybrid path is slower than faster-whisper "
                "on this hardware"
            )
            result["recommendation"] = (
                f"CoreML hybrid is {slowdown:.2f}x SLOWER than faster-whisper "
                f"({cml_stats['mean_ms']:.1f}ms vs {fw_stats['mean_ms']:.1f}ms). "
                f"CoreML encoder available but hybrid path is slower than "
                f"faster-whisper on this hardware — use --coreml only if ANE "
                f"utilization is confirmed via Instruments."
            )
            print(f"⚠  CoreML hybrid is SLOWER: {slowdown:.2f}x slowdown "
                  f"({cml_stats['mean_ms']:.1f}ms vs {fw_stats['mean_ms']:.1f}ms mean)")
            print("   --coreml is opt-in only — faster-whisper remains the default.")
    else:
        result["coreml_faster"] = None
        result["recommendation"] = (
            "CoreML encoder not available — faster-whisper is the only backend. "
            "Run backend/scripts/convert_whisper_coreml.py to generate the encoder."
        )

    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nResults written → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
