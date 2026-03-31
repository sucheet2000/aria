"""
Convert Whisper tiny encoder (and attempt decoder) to CoreML.

Usage:
    python3 backend/scripts/convert_whisper_coreml.py

Outputs:
    backend/models/whisper-tiny-encoder.mlpackage  (always produced)
    backend/models/whisper-tiny-decoder.mlpackage  (best-effort — skipped if
                                                    dynamic shapes prevent conversion)

ANE routing requires:
    compute_units = ALL  (CPU + GPU + ANE)
    minimum_deployment_target = iOS16 / macOS13  (ML Program format)
"""
from __future__ import annotations

import pathlib
import sys
import time

import numpy as np
import torch

# Suppress non-fatal coremltools warnings emitted at import time.
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="coremltools")

import coremltools as ct
import whisper

MODELS_DIR = pathlib.Path(__file__).parent.parent / "models"
ENCODER_PATH = MODELS_DIR / "whisper-tiny-encoder.mlpackage"
DECODER_PATH = MODELS_DIR / "whisper-tiny-decoder.mlpackage"

MEL_BINS = 80
MEL_FRAMES = 3000  # 30s of audio at 100 frames/s — always padded to this length


# ---------------------------------------------------------------------------
# Thin wrappers so we can trace without side-effects from the full model
# ---------------------------------------------------------------------------

class EncoderWrapper(torch.nn.Module):
    """Wraps whisper's AudioEncoder so it accepts a plain mel tensor."""
    def __init__(self, encoder: torch.nn.Module) -> None:
        super().__init__()
        self.encoder = encoder

    def forward(self, mel: torch.Tensor) -> torch.Tensor:
        return self.encoder(mel)


class DecoderWrapper(torch.nn.Module):
    """Wraps whisper's TextDecoder for a single decode step (no KV cache)."""
    def __init__(self, decoder: torch.nn.Module) -> None:
        super().__init__()
        self.decoder = decoder

    def forward(
        self,
        tokens: torch.Tensor,          # (batch, seq_len) int32
        encoder_output: torch.Tensor,  # (batch, n_mels/8, d_model)
    ) -> torch.Tensor:
        return self.decoder(tokens, encoder_output)


def convert_encoder(model: whisper.Whisper) -> None:
    print("\n── Encoder conversion ─────────────────────────────────────────")
    encoder_wrapper = EncoderWrapper(model.encoder).eval()
    dummy_mel = torch.zeros(1, MEL_BINS, MEL_FRAMES, dtype=torch.float32)

    print("  Tracing encoder …")
    with torch.no_grad():
        traced = torch.jit.trace(encoder_wrapper, dummy_mel)

    print("  Converting to CoreML (compute_units=ALL, target=iOS16) …")
    mlmodel = ct.convert(
        traced,
        inputs=[ct.TensorType(name="mel", shape=(1, MEL_BINS, MEL_FRAMES))],
        outputs=[ct.TensorType(name="encoder_output")],
        compute_units=ct.ComputeUnit.ALL,
        minimum_deployment_target=ct.target.iOS16,
        convert_to="mlprogram",
    )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    mlmodel.save(str(ENCODER_PATH))
    print(f"  Saved → {ENCODER_PATH}")

    # --- validate ---
    print("  Validating …")
    loaded = ct.models.MLModel(str(ENCODER_PATH))
    dummy_np = {"mel": np.zeros((1, MEL_BINS, MEL_FRAMES), dtype=np.float32)}
    _ = loaded.predict(dummy_np)
    print("  Validation passed ✓")

    # --- benchmark ---
    print("  Benchmarking (10 runs) …")
    latencies = []
    for _ in range(10):
        t0 = time.perf_counter()
        _ = loaded.predict(dummy_np)
        latencies.append((time.perf_counter() - t0) * 1000)

    latencies_sorted = sorted(latencies)
    mean_ms = sum(latencies) / len(latencies)
    p50 = latencies_sorted[5]
    p95 = latencies_sorted[9]
    print(f"  Encoder latency — mean: {mean_ms:.1f}ms  p50: {p50:.1f}ms  p95: {p95:.1f}ms")


def attempt_decoder_conversion(model: whisper.Whisper) -> None:
    print("\n── Decoder conversion (best-effort) ───────────────────────────")
    n_ctx = model.dims.n_text_ctx     # 448
    n_state = model.dims.n_text_state  # 384 for tiny

    # Whisper's encoder output shape: (1, n_audio_ctx, n_state) where
    # n_audio_ctx = MEL_FRAMES // 2 = 1500 for tiny.
    n_audio_ctx = MEL_FRAMES // 2

    decoder_wrapper = DecoderWrapper(model.decoder).eval()
    dummy_tokens = torch.zeros(1, 1, dtype=torch.long)
    dummy_enc_out = torch.zeros(1, n_audio_ctx, n_state, dtype=torch.float32)

    print("  Tracing decoder (single step, no KV cache) …")
    try:
        with torch.no_grad():
            traced = torch.jit.trace(decoder_wrapper, (dummy_tokens, dummy_enc_out))
    except Exception as e:
        print(f"  ✗ Trace failed: {e}")
        print("  Decoder conversion skipped — dynamic shapes in attention mask.")
        return

    print("  Converting to CoreML …")
    try:
        mlmodel = ct.convert(
            traced,
            inputs=[
                ct.TensorType(name="tokens",         shape=(1, 1)),
                ct.TensorType(name="encoder_output", shape=(1, n_audio_ctx, n_state)),
            ],
            outputs=[ct.TensorType(name="logits")],
            compute_units=ct.ComputeUnit.ALL,
            minimum_deployment_target=ct.target.iOS16,
            convert_to="mlprogram",
        )
        mlmodel.save(str(DECODER_PATH))
        print(f"  Saved → {DECODER_PATH}")
    except Exception as e:
        print(f"  ✗ CoreML conversion failed: {e}")
        print("  Decoder conversion skipped — dynamic shapes prevent static graph export.")
        print("  Decoder will continue to run via openai-whisper CPU path.")


def main() -> None:
    print("Loading Whisper tiny …")
    model = whisper.load_model("tiny").eval()
    print(f"  dims: {model.dims}")

    convert_encoder(model)
    attempt_decoder_conversion(model)

    print("\n── Summary ────────────────────────────────────────────────────")
    print(f"  Encoder: {'✓ ' + str(ENCODER_PATH) if ENCODER_PATH.exists() else '✗ not produced'}")
    print(f"  Decoder: {'✓ ' + str(DECODER_PATH) if DECODER_PATH.exists() else '✗ not produced (expected)'}")
    print("\nConversion complete.")


if __name__ == "__main__":
    main()
