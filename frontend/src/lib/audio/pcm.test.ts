import { describe, it, expect } from "vitest";
import {
  PcmDownsampler,
  floatTo16BitPCM,
  TARGET_SAMPLE_RATE,
  FRAME_SAMPLES,
} from "./pcm";

describe("floatTo16BitPCM", () => {
  it("maps the full-scale range to signed 16-bit bounds", () => {
    const out = floatTo16BitPCM(new Float32Array([1, -1, 0]));
    expect(out).toBeInstanceOf(Int16Array);
    expect(out[0]).toBe(32767);
    expect(out[1]).toBe(-32768);
    expect(out[2]).toBe(0);
  });

  it("clamps values outside [-1, 1]", () => {
    const out = floatTo16BitPCM(new Float32Array([2, -2]));
    expect(out[0]).toBe(32767);
    expect(out[1]).toBe(-32768);
  });

  it("preserves length", () => {
    expect(floatTo16BitPCM(new Float32Array(320)).length).toBe(320);
  });
});

describe("PcmDownsampler", () => {
  it("resamples 48kHz to 16kHz at roughly one third the samples", () => {
    const ds = new PcmDownsampler(48000, TARGET_SAMPLE_RATE);
    const out1 = ds.process(new Float32Array(480).fill(0.5));
    const out2 = ds.process(new Float32Array(480).fill(0.5));
    const total = out1.length + out2.length;

    expect(total).toBeGreaterThan(310);
    expect(total).toBeLessThan(325);
  });

  it("preserves a constant signal exactly across block boundaries", () => {
    const ds = new PcmDownsampler(48000, TARGET_SAMPLE_RATE);
    const blocks = [
      ds.process(new Float32Array(512).fill(0.25)),
      ds.process(new Float32Array(512).fill(0.25)),
    ];
    for (const v of blocks.flatMap((b) => Array.from(b))) {
      expect(v).toBeCloseTo(0.25, 6);
    }
  });

  it("linearly interpolates a ramp at a 1.5 ratio", () => {
    const ds = new PcmDownsampler(24000, TARGET_SAMPLE_RATE);
    const ramp = Float32Array.from({ length: 12 }, (_, i) => i);
    const out = ds.process(ramp);

    expect(Array.from(out)).toEqual([0, 1.5, 3, 4.5, 6, 7.5, 9, 10.5]);
  });

  it("passes samples through unchanged at a 1:1 ratio", () => {
    const ds = new PcmDownsampler(16000, TARGET_SAMPLE_RATE);
    const input = Float32Array.from({ length: 8 }, (_, i) => i / 10);
    const out = ds.process(input);

    expect(out.length).toBe(7);
    expect(out[0]).toBeCloseTo(0, 6);
    expect(out[6]).toBeCloseTo(0.6, 6);
  });
});

describe("audio constants", () => {
  it("targets 16kHz frames of 320 samples (20ms)", () => {
    expect(TARGET_SAMPLE_RATE).toBe(16000);
    expect(FRAME_SAMPLES).toBe(320);
  });
});
