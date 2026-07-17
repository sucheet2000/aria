# Week 4: ANE Acceleration — CoreML Whisper

> **Status:** PENDING APPROVAL — do not write implementation code until approved.

---

## What we're building and why

Week 4 accelerates STT inference from 1–2s to <300ms by routing the Whisper encoder
through Apple's ANE (Apple Neural Engine) via CoreML. The decoder cannot be converted
to CoreML in Week 4 (see Constraint below), so openai-whisper's CPU decoder runs
alongside the CoreML encoder. This gives ANE acceleration for the heavy encoder pass —
the dominant latency contributor — while keeping a fully working decode loop.

The existing faster-whisper path remains the default. A `--coreml` flag activates the
CoreML path. No existing behaviour changes unless the flag is passed.

---

## Architecture

```
audio_worker.py (--coreml flag)
  │
  ├─ args.coreml = False (default)
  │     └─ Transcriber  ←── faster-whisper (CPU int8)  [UNCHANGED]
  │
  └─ args.coreml = True
        └─ WhisperCoreML
               ├─ Encoder path:  openai-whisper log_mel_spectrogram()
               │                 → CoreML encoder (.mlpackage, ANE)
               │                 → encoder_hidden_states (torch tensor)
               └─ Decoder path:  openai-whisper DecodingTask
                                  (beam search, CPU — dynamic shapes)
```

**Why encoder-only CoreML?**

The Whisper decoder runs autoregressive token generation with KV-cache; sequence length
grows dynamically with each token step. CoreML requires static or enumerated shapes.
Enumerating all possible sequence lengths is tractable but deferred to a future week.

The encoder takes a fixed 80×3000 mel spectrogram and is trivially convertible.
It accounts for ~60-70% of total Whisper tiny latency, so encoder-only CoreML still
delivers meaningful speedup.

---

## File-by-file breakdown

### Task 1 — Install tooling

No new files. Install into existing conda environment:
```bash
/Users/sucheetboppana/miniconda-arm64/bin/pip install \
  coremltools openai-whisper \
  --break-system-packages
```
Verify:
```bash
python3 -c "import coremltools; print(coremltools.__version__)"
python3 -c "import whisper; print('whisper ok')"
```

---

### Task 2 — Whisper tiny → CoreML conversion script

**New file: `backend/scripts/convert_whisper_coreml.py`**

Steps performed by the script:
1. `whisper.load_model("tiny")` — downloads weights (~150MB) to `~/.cache/whisper/`
2. Trace the encoder forward pass with a fixed `(1, 80, 3000)` mel input via
   `torch.jit.trace` to get a TorchScript graph
3. `ct.convert(traced_encoder, ...)` with:
   - `inputs=[ct.TensorType(shape=(1, 80, 3000))]`
   - `compute_units=ct.ComputeUnit.ALL` — enables ANE routing
   - `minimum_deployment_target=ct.target.iOS16` — required for ANE on M1
   - `convert_to="mlprogram"` — modern ML Program format (required for iOS16 target)
4. Save to `backend/models/whisper-tiny-encoder.mlpackage`
5. Attempt decoder conversion (same trace approach) — document failure and skip if
   dynamic shapes cause `ct.convert` to raise. This is expected; decoder is deferred.
6. Validate encoder loads via `ct.models.MLModel(path)` and runs a dummy forward pass
7. Benchmark: 10× encoder-only inference, report mean latency in ms

**Output files:**
- `backend/models/whisper-tiny-encoder.mlpackage` — created by script, gitignored
- `backend/models/` already in `.gitignore`

---

### Task 3 — `WhisperCoreML` wrapper

**New file: `backend/app/pipeline/whisper_coreml.py`**

```python
class WhisperCoreML:
    def __init__(self, model_size: str = "tiny") -> None: ...
    def load(self) -> None: ...
    def transcribe(self, audio_chunks: list[np.ndarray]) -> tuple[str, float]: ...
```

Interface deliberately matches `Transcriber` (same `.load()` / `.transcribe()` contract)
so `audio_worker.py` can substitute it without restructuring.

**Internal design:**
- `load()` attempts to import `coremltools` and load
  `backend/models/whisper-tiny-encoder.mlpackage`. If either fails, sets
  `self._use_coreml = False` and loads a faster-whisper model as fallback.
  Logs which backend was activated.
- `transcribe(audio_chunks)`:
  - Concatenates chunks, normalises to float32 [-1, 1]
  - If `_use_coreml`:
    - Runs `whisper.log_mel_spectrogram()` to build `(1, 80, 3000)` input
    - Runs CoreML encoder → `encoder_output`
    - Passes `encoder_output` into `whisper.decoding.decode()` (CPU beam search)
    - Returns (text, confidence)
  - Else: falls back to faster-whisper (same logic as `Transcriber.transcribe`)
- **Thread safety:** a `threading.Lock` guards the CoreML model call.
  `ct.models.MLModel` is not documented as thread-safe; the lock ensures one
  inference at a time. The faster-whisper fallback path inherits the same lock.

---

### Task 4 — Wire into `audio_worker.py`

**Modify `backend/app/pipeline/audio_worker.py`**

Changes are minimal and surgical:
1. Add `--coreml` argument (default `False`) to `argparse`
2. In `run_microphone()`, after the existing `Transcriber(model_size=args.model)`:
   ```python
   if args.coreml:
       from app.pipeline.whisper_coreml import WhisperCoreML
       transcriber = WhisperCoreML(model_size=args.model)
   else:
       transcriber = Transcriber(model_size=args.model)
   ```
3. Log which backend is active immediately after `.load()`:
   ```python
   logger.info("transcription backend active", backend="coreml" if args.coreml else "faster-whisper")
   ```

**What is NOT touched:**
- VAD logic (`VADProcessor`, `vad.process_chunk`, mute/unmute)
- Wake word / sleep phrase detection
- `run_synthetic()` — CoreML flag has no effect in synthetic mode
- Denoiser logic
- All stream output formats

---

### Task 5 — Benchmark script

**New file: `backend/scripts/benchmark_whisper.py`**

1. Generates a 3s synthetic audio clip: 440Hz sine wave + Gaussian noise, float32 16kHz
2. Runs faster-whisper tiny 20× (with `.load()` overhead excluded from per-run timing)
3. Runs CoreML path 20× if `backend/models/whisper-tiny-encoder.mlpackage` exists
4. Computes mean, p50, p95, p99 for each backend
5. Writes to `backend/benchmarks/whisper_latency.json`:
   ```json
   {
     "faster_whisper": {"mean_ms": ..., "p50_ms": ..., "p95_ms": ..., "p99_ms": ...},
     "coreml":         {"mean_ms": ..., "p50_ms": ..., "p95_ms": ..., "p99_ms": ...}
   }
   ```
6. Prints a human-readable summary table to stdout

---

### Task 6 — MediaPipe CoreML note

**Modify `backend/app/pipeline/vision_worker.py`** — comment only.

MediaPipe's `.task` files already use the Metal/CoreML delegate on Apple Silicon.
No code changes are needed. A comment is added above the `FaceLandmarker` and
`HandLandmarker` option blocks confirming this.

Verification: MediaPipe 0.10+ automatically selects the CoreML delegate when
`mp_tasks.BaseOptions` detects Apple Silicon. The `model_asset_path` pointing to
a `.task` file (not `.tflite`) confirms the modern API path is used.

---

### Task 7 — Tests

**New file: `backend/tests/test_whisper_coreml.py`**

Three tests, no real CoreML or faster-whisper I/O:

| Test | What it covers |
|---|---|
| `test_fallback_when_no_mlpackage` | `WhisperCoreML.load()` with a non-existent model path sets `_use_coreml=False` without raising |
| `test_transcribe_returns_string` | With `_use_coreml=False` and a mocked faster-whisper model, `transcribe()` returns `(str, float)` |
| `test_thread_safety` | 3 threads call `transcribe()` concurrently with mocked internals — no exceptions, all return strings |

All 85 existing tests must still pass.

---

### Task 8 — Build verification

```bash
cd backend && go build ./... && go vet ./...
PYTHONPATH=backend python3 -m pytest backend/tests/ -v | tail -20
cd frontend && npm run build
```

---

### Task 9 — Adversarial review

```
/codex:adversarial-review --base main
```

Focus areas for reviewer:
1. **CoreML fallback correctness** — if `.mlpackage` is missing, does `WhisperCoreML`
   behave identically to `Transcriber`? (same audio normalisation, same confidence calc)
2. **Thread safety** — is the `threading.Lock` scope correct? Does it prevent concurrent
   CoreML calls without unnecessarily blocking the fallback path?
3. **Mel spectrogram shape** — whisper's `log_mel_spectrogram()` pads/crops to exactly
   3000 frames for 30s audio. For our 3–8s utterances, the input is always padded to 3000.
   Confirm the CoreML model receives the correct shape.
4. **openai-whisper decoder confidence** — `Transcriber` derives confidence from
   `segment.avg_logprob + 1.0`. `whisper.decoding.DecodingResult` exposes
   `avg_logprob` directly. Confirm the same formula is used in `WhisperCoreML`.

---

### Task 10 — Commit

```
feat(week4): ANE acceleration — CoreML Whisper, benchmark pipeline

- Encoder-only CoreML conversion script (decoder deferred — dynamic shapes)
- WhisperCoreML wrapper: CoreML encoder + openai-whisper decoder, falls back
  to faster-whisper when .mlpackage absent
- --coreml flag in audio_worker.py (default False, no breaking changes)
- Benchmark script: faster-whisper vs CoreML, writes whisper_latency.json
- MediaPipe CoreML confirmation comment in vision_worker.py
- Tests: fallback, return type, thread safety
```

---

## Dependencies to add

| Dep | Where | Notes |
|---|---|---|
| `openai-whisper` | Python | Provides model weights, mel preprocessing, decoder |
| `coremltools` | Python | Apple's conversion and inference library |

Both are pip-installable into the existing conda env. Neither affects Go or frontend.

---

## Risks and tradeoffs

| Risk | Severity | Mitigation |
|---|---|---|
| Decoder CoreML conversion fails | Expected | Encoder-only is the plan; documented |
| CoreML encoder latency > 300ms target | Medium | Benchmark in Task 5; fall back to faster-whisper if target missed |
| openai-whisper decoder slower than faster-whisper decoder | Medium | Acceptable in `--coreml` mode; faster-whisper remains the default |
| `ct.ComputeUnit.ALL` routes to GPU not ANE | Low | ANE routing is not guaranteed; benchmark will reveal which device is used |
| Thread safety race in `WhisperCoreML` | Low | Lock covers both CoreML and fallback paths |
| `.mlpackage` files should not be committed | None | `backend/models/` already in `.gitignore` |
