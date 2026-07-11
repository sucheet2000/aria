// Pure PCM helpers shared by the browser mic-capture pipeline (A.2b-1).
// The AudioContext runs at the hardware's native rate (typically 44.1/48 kHz),
// so the mic path must explicitly downsample to the 16 kHz mono Int16 contract
// the server's STT/VAD pipeline expects.

export const TARGET_SAMPLE_RATE = 16000;

// 320 samples = 20 ms at 16 kHz — squarely inside the contract's 320–640 range
// and a standard VAD frame size.
export const FRAME_SAMPLES = 320;

export function floatTo16BitPCM(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const clamped = Math.max(-1, Math.min(1, input[i]));
    out[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }
  return out;
}

// Streaming linear-interpolation resampler. Carries a fractional read position
// and any unconsumed tail across calls so successive blocks stay phase-aligned.
export class PcmDownsampler {
  private readonly ratio: number;
  private position = 0;
  private tail: Float32Array = new Float32Array(0);

  constructor(inputRate: number, targetRate: number = TARGET_SAMPLE_RATE) {
    this.ratio = inputRate / targetRate;
  }

  process(block: Float32Array): Float32Array {
    const combined = new Float32Array(this.tail.length + block.length);
    combined.set(this.tail);
    combined.set(block, this.tail.length);

    const out: number[] = [];
    let pos = this.position;
    while (Math.floor(pos) + 1 < combined.length) {
      const i = Math.floor(pos);
      const frac = pos - i;
      out.push(combined[i] * (1 - frac) + combined[i + 1] * frac);
      pos += this.ratio;
    }

    const keep = Math.min(Math.floor(pos), combined.length);
    this.tail = combined.slice(keep);
    this.position = pos - keep;
    return Float32Array.from(out);
  }
}
