import { describe, it, expect } from "vitest";
import {
  GestureClassifier,
  gestureName,
  HAND_GESTURE_OPEN_PALM,
  HAND_GESTURE_PINCH,
  HAND_GESTURE_POINT,
  HAND_GESTURE_THUMB_UP,
  HAND_GESTURE_UNSPECIFIED,
} from "./gesture";

// Ported from backend/tests/test_gesture_classifier.py. Same synthetic landmark
// factories -> same expected gesture labels.

function baseLandmarks(): number[][] {
  return Array.from({ length: 21 }, () => [0.5, 0.5, 0.0]);
}

function extendFinger(
  lm: number[][],
  mcp: number,
  pip: number,
  dip: number,
  tip: number,
  baseY: number,
): void {
  lm[mcp] = [0.5, baseY, 0.0];
  lm[pip] = [0.5, baseY - 0.08, 0.0];
  lm[dip] = [0.5, baseY - 0.16, 0.0];
  lm[tip] = [0.5, baseY - 0.24, 0.0];
}

function curlFinger(
  lm: number[][],
  mcp: number,
  pip: number,
  dip: number,
  tip: number,
  baseY: number,
): void {
  lm[mcp] = [0.5, baseY, 0.0];
  lm[pip] = [0.5, baseY + 0.05, 0.0];
  lm[dip] = [0.5, baseY + 0.09, 0.0];
  lm[tip] = [0.5, baseY + 0.13, 0.0];
}

function openPalm(): number[][] {
  const lm = baseLandmarks();
  lm[0] = [0.5, 0.9, 0.0];
  lm[1] = [0.35, 0.75, 0.0];
  lm[2] = [0.3, 0.65, 0.0];
  lm[3] = [0.25, 0.55, 0.0];
  lm[4] = [0.2, 0.45, 0.0];
  extendFinger(lm, 5, 6, 7, 8, 0.75);
  extendFinger(lm, 9, 10, 11, 12, 0.75);
  extendFinger(lm, 13, 14, 15, 16, 0.75);
  extendFinger(lm, 17, 18, 19, 20, 0.75);
  return lm;
}

function point(): number[][] {
  const lm = baseLandmarks();
  lm[0] = [0.5, 0.9, 0.0];
  // The thumb has to be placed. baseLandmarks() leaves every point at the
  // centre of the frame, which put the thumb tip on top of the index tip —
  // geometrically a pinch, not a point. The old classifier never looked at the
  // thumb so the fixture passed anyway.
  lm[1] = [0.42, 0.82, 0.0];
  lm[2] = [0.38, 0.78, 0.0];
  lm[3] = [0.35, 0.75, 0.0];
  lm[4] = [0.33, 0.72, 0.0];
  extendFinger(lm, 5, 6, 7, 8, 0.75);
  curlFinger(lm, 9, 10, 11, 12, 0.7);
  curlFinger(lm, 13, 14, 15, 16, 0.7);
  curlFinger(lm, 17, 18, 19, 20, 0.7);
  return lm;
}

function fist(): number[][] {
  const lm = baseLandmarks();
  lm[0] = [0.5, 0.6, 0.0];
  lm[1] = [0.45, 0.65, 0.0];
  lm[2] = [0.42, 0.68, 0.0];
  lm[3] = [0.4, 0.71, 0.0];
  lm[4] = [0.38, 0.75, 0.0];
  curlFinger(lm, 5, 6, 7, 8, 0.65);
  curlFinger(lm, 9, 10, 11, 12, 0.65);
  curlFinger(lm, 13, 14, 15, 16, 0.65);
  curlFinger(lm, 17, 18, 19, 20, 0.65);
  return lm;
}

function thumbsUp(): number[][] {
  const lm = baseLandmarks();
  lm[0] = [0.5, 0.85, 0.0];
  lm[1] = [0.5, 0.75, 0.0];
  lm[2] = [0.5, 0.7, 0.0];
  lm[3] = [0.5, 0.6, 0.0];
  lm[4] = [0.5, 0.45, 0.0];
  curlFinger(lm, 5, 6, 7, 8, 0.7);
  curlFinger(lm, 9, 10, 11, 12, 0.7);
  curlFinger(lm, 13, 14, 15, 16, 0.7);
  curlFinger(lm, 17, 18, 19, 20, 0.7);
  return lm;
}

describe("GestureClassifier", () => {
  it("classifies an open palm as OPEN_PALM (stop)", () => {
    const r = new GestureClassifier().classify(openPalm());
    expect(r.gestureType).toBe(HAND_GESTURE_OPEN_PALM);
    expect(gestureName(r.gestureType)).toBe("stop");
    expect(r.confidence).toBeGreaterThanOrEqual(0);
    expect(r.confidence).toBeLessThanOrEqual(1);
  });

  it("classifies a pointing hand as POINT with a unit pointing vector", () => {
    const r = new GestureClassifier().classify(point());
    expect(r.gestureType).toBe(HAND_GESTURE_POINT);
    expect(gestureName(r.gestureType)).toBe("point");
    expect(r.pointingVector).not.toBeNull();
    const [vx, vy, vz] = r.pointingVector!;
    expect(Math.sqrt(vx * vx + vy * vy + vz * vz)).toBeCloseTo(1.0, 5);
  });

  // A closed fist is NOT a pinch. It used to be reported as one — and shown to
  // the user as "cancel" — because PINCH was scored by a curled-finger count
  // that never looked at the thumb. There is no FIST value in the gesture
  // contract, so a fist now correctly reads as no recognized gesture rather
  // than as somebody else's.
  it("does not classify a fist as PINCH", () => {
    const g = new GestureClassifier().classify(fist());
    expect(g.gestureType).not.toBe(HAND_GESTURE_PINCH);
    expect(g.gestureType).toBe(HAND_GESTURE_UNSPECIFIED);
    expect(g.pointingVector).toBeNull();
  });

  it("classifies a thumbs-up as THUMB_UP (confirm)", () => {
    const r = new GestureClassifier().classify(thumbsUp());
    expect(r.gestureType).toBe(HAND_GESTURE_THUMB_UP);
    expect(gestureName(r.gestureType)).toBe("confirm");
  });

  it("returns UNSPECIFIED for the wrong landmark count", () => {
    const r = new GestureClassifier().classify(Array.from({ length: 10 }, () => [0.5, 0.5, 0.0]));
    expect(r.gestureType).toBe(HAND_GESTURE_UNSPECIFIED);
    expect(r.confidence).toBe(0);
  });

  it("returns UNSPECIFIED for empty landmarks", () => {
    const r = new GestureClassifier().classify([]);
    expect(r.gestureType).toBe(HAND_GESTURE_UNSPECIFIED);
  });

  it("maps unspecified/none to the 'none' label", () => {
    expect(gestureName(HAND_GESTURE_UNSPECIFIED)).toBe("none");
  });
});
