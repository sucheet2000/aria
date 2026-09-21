// Workstream C — PINCH was scored by a fist detector. It counted curled
// fingers and never looked at the thumb at all, so a closed fist was reported
// as a pinch, which the UI shows as "cancel". A real pinch is a relationship
// between two fingertips, so that is what it now measures: thumb tip to index
// tip, normalized by the hand's own size so it holds at any distance from the
// camera and for either hand.
import { describe, it, expect } from "vitest";
import {
  GestureClassifier,
  HAND_GESTURE_OPEN_PALM,
  HAND_GESTURE_PINCH,
  HAND_GESTURE_POINT,
  HAND_GESTURE_UNSPECIFIED,
} from "./gesture";

function baseLandmarks(): number[][] {
  return Array.from({ length: 21 }, () => [0.5, 0.5, 0.0]);
}

function extendFinger(lm: number[][], mcp: number, pip: number, dip: number, tip: number, baseY: number): void {
  lm[mcp] = [0.5, baseY, 0.0];
  lm[pip] = [0.5, baseY - 0.08, 0.0];
  lm[dip] = [0.5, baseY - 0.16, 0.0];
  lm[tip] = [0.5, baseY - 0.24, 0.0];
}

function curlFinger(lm: number[][], mcp: number, pip: number, dip: number, tip: number, baseY: number): void {
  lm[mcp] = [0.5, baseY, 0.0];
  lm[pip] = [0.5, baseY + 0.05, 0.0];
  lm[dip] = [0.5, baseY + 0.09, 0.0];
  lm[tip] = [0.5, baseY + 0.13, 0.0];
}

// A pinch: thumb tip and index tip meet in front of the palm, the remaining
// fingers relaxed and curled. The wrist-to-middle-MCP span is the hand scale.
function pinch(gap = 0.01): number[][] {
  const lm = baseLandmarks();
  lm[0] = [0.5, 0.9, 0.0];              // wrist
  lm[9] = [0.5, 0.6, 0.0];              // middle MCP -> palm span 0.30
  lm[5] = [0.44, 0.62, 0.0];            // index MCP
  lm[6] = [0.44, 0.56, 0.0];
  lm[7] = [0.45, 0.52, 0.0];
  lm[8] = [0.46, 0.50, 0.0];            // index tip
  lm[1] = [0.58, 0.78, 0.0];
  lm[2] = [0.56, 0.70, 0.0];
  lm[3] = [0.52, 0.62, 0.0];
  lm[4] = [0.46 + gap, 0.50, 0.0];      // thumb tip, `gap` from the index tip
  curlFinger(lm, 13, 14, 15, 16, 0.62);
  curlFinger(lm, 17, 18, 19, 20, 0.62);
  lm[10] = [0.5, 0.65, 0.0];
  lm[11] = [0.5, 0.69, 0.0];
  lm[12] = [0.5, 0.73, 0.0];            // middle curled
  return lm;
}

function fist(): number[][] {
  const lm = baseLandmarks();
  lm[0] = [0.5, 0.6, 0.0];
  lm[1] = [0.45, 0.65, 0.0];
  lm[2] = [0.42, 0.68, 0.0];
  lm[3] = [0.4, 0.71, 0.0];
  lm[4] = [0.38, 0.75, 0.0];            // thumb tucked beside the fist
  curlFinger(lm, 5, 6, 7, 8, 0.65);
  curlFinger(lm, 9, 10, 11, 12, 0.65);
  curlFinger(lm, 13, 14, 15, 16, 0.65);
  curlFinger(lm, 17, 18, 19, 20, 0.65);
  return lm;
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
  lm[4] = [0.3, 0.7, 0.0];              // thumb well away from the index tip
  extendFinger(lm, 5, 6, 7, 8, 0.75);
  curlFinger(lm, 9, 10, 11, 12, 0.7);
  curlFinger(lm, 13, 14, 15, 16, 0.7);
  curlFinger(lm, 17, 18, 19, 20, 0.7);
  return lm;
}

// Mirror across x to make a left hand from a right hand.
function mirrored(lm: number[][]): number[][] {
  return lm.map(([x, yy, z]) => [1 - x, yy, z]);
}

// Uniform scale about the wrist: the same hand, further from the camera.
function scaled(lm: number[][], k: number): number[][] {
  const [wx, wy] = lm[0];
  return lm.map(([x, yy, z]) => [wx + (x - wx) * k, wy + (yy - wy) * k, z * k]);
}

function translated(lm: number[][], dx: number, dy: number): number[][] {
  return lm.map(([x, yy, z]) => [x + dx, yy + dy, z]);
}

const clf = new GestureClassifier();

describe("pinch is a pinch, not a fist", () => {
  it("1: thumb and index touching is a pinch", () => {
    expect(clf.classify(pinch()).gestureType).toBe(HAND_GESTURE_PINCH);
  });

  it("2: a closed fist is NOT a pinch", () => {
    expect(clf.classify(fist()).gestureType).not.toBe(HAND_GESTURE_PINCH);
  });

  it("3: a pointing hand is NOT a pinch", () => {
    expect(clf.classify(point()).gestureType).toBe(HAND_GESTURE_POINT);
  });

  it("4: an open hand is NOT a pinch", () => {
    expect(clf.classify(openPalm()).gestureType).toBe(HAND_GESTURE_OPEN_PALM);
  });

  it("5 and 6: the same verdict for either hand", () => {
    expect(clf.classify(mirrored(pinch())).gestureType).toBe(HAND_GESTURE_PINCH);
    expect(clf.classify(mirrored(fist())).gestureType).not.toBe(HAND_GESTURE_PINCH);
  });

  it("7: a hand further from the camera pinches just the same", () => {
    for (const k of [0.4, 0.7, 1.5, 2.5]) {
      expect(clf.classify(scaled(pinch(), k)).gestureType).toBe(HAND_GESTURE_PINCH);
    }
  });

  it("7: scale does not turn a fist into a pinch either", () => {
    for (const k of [0.4, 2.5]) {
      expect(clf.classify(scaled(fist(), k)).gestureType).not.toBe(HAND_GESTURE_PINCH);
    }
  });

  it("8: moving the hand across the frame changes nothing", () => {
    for (const [dx, dy] of [[-0.3, -0.2], [0.25, 0.3]]) {
      expect(clf.classify(translated(pinch(), dx, dy)).gestureType).toBe(HAND_GESTURE_PINCH);
    }
  });

  it("9 and 12: a clearly open gap is not a pinch, a closed one is", () => {
    expect(clf.classify(pinch(0.005)).gestureType).toBe(HAND_GESTURE_PINCH);
    // Fingers a third of the palm apart are not pinching.
    expect(clf.classify(pinch(0.12)).gestureType).not.toBe(HAND_GESTURE_PINCH);
  });

  it("10: missing landmarks yield UNSPECIFIED rather than a guess", () => {
    expect(clf.classify([]).gestureType).toBe(HAND_GESTURE_UNSPECIFIED);
    expect(clf.classify(baseLandmarks().slice(0, 12)).gestureType).toBe(HAND_GESTURE_UNSPECIFIED);
  });

  it("11: non-finite coordinates never produce a confident gesture", () => {
    const nan = pinch();
    nan[4] = [Number.NaN, Number.NaN, 0];
    expect(clf.classify(nan).gestureType).toBe(HAND_GESTURE_UNSPECIFIED);

    const inf = pinch();
    inf[8] = [Number.POSITIVE_INFINITY, 0.5, 0];
    expect(clf.classify(inf).gestureType).toBe(HAND_GESTURE_UNSPECIFIED);
  });

  it("a degenerate hand with no measurable size is not classified", () => {
    const flat = baseLandmarks(); // every landmark at the same point
    expect(clf.classify(flat).gestureType).toBe(HAND_GESTURE_UNSPECIFIED);
  });
});
