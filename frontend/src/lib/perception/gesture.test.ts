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
  // that never looked at the thumb.
  //
  // Keep this, but do not trust it: fist() places the thumb BELOW the wrist,
  // which no raised hand does, and that accident alone was enough to make it
  // pass while both the pinch and the thumbs-up branches were still broken.
  // The honest coverage is "a raised fist is not a thumbs-up" further down,
  // which builds its hands from anatomy.
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

// ── Raised-fist P1 ───────────────────────────────────────────────────────────
// Found by independent QA and reproduced three ways: every anatomically real
// raised fist was reported as "confirm", or as "cancel" where the folded thumb
// sat near the index tip. The fist() fixture above missed it because it places
// the thumb BELOW the wrist — an inverted hand no raised fist makes.
//
// These build hands from anatomy instead: y grows downward, so a raised hand
// has the wrist at the largest y, the knuckles above it, and curled fingertips
// bent back down below their own knuckles.

interface HandOpts {
  thumb: [number, number];
  scale?: number;
  origin?: [number, number];
  rotation?: number;
  mirror?: boolean;
}

// A closed hand in a canonical frame, then optionally scaled, rotated,
// translated and mirrored — so one description covers every required case.
function builtHand({ thumb, scale = 1, origin = [0, 0], rotation = 0, mirror = false }: HandOpts): number[][] {
  const canonical: number[][] = [];
  const set = (i: number, x: number, yy: number) => {
    canonical[i] = [x, yy, 0];
  };
  set(0, 0.0, 0.30); // wrist
  set(1, -0.06, 0.22); set(2, -0.08, 0.16); set(3, -0.07, 0.12);
  set(4, thumb[0], thumb[1]); // thumb tip
  const cols = [-0.06, 0.0, 0.06, 0.12];
  [5, 9, 13, 17].forEach((mcp, k) => {
    set(mcp, cols[k], 0.0);
    set(mcp + 1, cols[k], 0.03);
    set(mcp + 2, cols[k], 0.06);
    set(mcp + 3, cols[k], 0.08); // tip below its knuckle = curled
  });
  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);
  return canonical.map(([x, yy]) => {
    const mx = mirror ? -x : x;
    return [
      origin[0] + scale * (mx * cos - yy * sin),
      origin[1] + scale * (mx * sin + yy * cos),
      0,
    ];
  });
}

// Two real fists, because they fail for different reasons. Folded across the
// fingers, the thumb lands near the index tip and the PINCH branch claims it;
// tucked alongside, it is far from every fingertip and the THUMB_UP branch
// claims it. A single pose would leave half the defect untested — which is how
// the original fist fixture passed while both branches were broken.
const FIST_THUMB: [number, number] = [-0.03, 0.10];
const FIST_THUMB_SIDE: [number, number] = [0.10, 0.02];
const FIST_THUMBS: Array<[string, [number, number]]> = [
  ["folded across the fingers", FIST_THUMB],
  ["tucked alongside", FIST_THUMB_SIDE],
];
// Held clear of the fist, well past the knuckle line.
const UP_THUMB: [number, number] = [-0.02, -0.22];

// A real pinch: the index reaches out past the knuckles and the thumb meets it
// there. The repo had no pinch fixture at all, so "a valid pinch is still a
// pinch" was never actually asserted — only "a fist is not one".
function builtPinch(opts: { scale?: number; origin?: [number, number]; mirror?: boolean } = {}): number[][] {
  const { scale = 1, origin = [0.5, 0.6], mirror = false } = opts;
  const lm = builtHand({ thumb: [-0.02, -0.11], scale, origin, mirror });
  const place = (x: number, yy: number): number[] => [
    origin[0] + scale * (mirror ? -x : x),
    origin[1] + scale * yy,
    0,
  ];
  lm[5] = place(-0.06, 0.0);
  lm[6] = place(-0.05, -0.05);
  lm[7] = place(-0.045, -0.09);
  lm[8] = place(-0.04, -0.12); // index tip, out in front of the knuckles
  return lm;
}

function nameOf(lm: number[][]): string {
  return gestureName(new GestureClassifier().classify(lm).gestureType);
}

describe("a raised fist is not a thumbs-up", () => {
  it("1. a genuine thumbs-up is still confirm", () => {
    expect(nameOf(builtHand({ thumb: UP_THUMB, origin: [0.5, 0.6] }))).toBe("confirm");
  });

  it.each(FIST_THUMBS)("2. a raised fist (%s) is no recognized gesture", (_label, thumb) => {
    expect(nameOf(builtHand({ thumb, origin: [0.5, 0.6] }))).toBe("none");
  });

  it("3. a rotated and translated raised fist is still no gesture", () => {
    for (const [label, thumb] of FIST_THUMBS) {
      for (const rotation of [-0.6, -0.3, 0.3, 0.6]) {
        const lm = builtHand({ thumb, origin: [0.35, 0.55], rotation });
        expect(nameOf(lm), `${label} at rotation ${rotation}`).toBe("none");
      }
    }
  });

  it("4. a fist is no gesture at any size", () => {
    for (const [label, thumb] of FIST_THUMBS) {
      for (const scale of [0.35, 0.7, 1, 1.8, 3]) {
        expect(nameOf(builtHand({ thumb, origin: [0.5, 0.6], scale })), `${label} at scale ${scale}`).toBe("none");
      }
    }
    // and the real thumbs-up survives the same range
    for (const scale of [0.35, 0.7, 1, 1.8, 3]) {
      expect(nameOf(builtHand({ thumb: UP_THUMB, origin: [0.5, 0.6], scale })), `scale ${scale}`).toBe("confirm");
    }
  });

  it("5. a genuine pinch is still cancel, at any size and on either hand", () => {
    expect(nameOf(builtPinch())).toBe("cancel");
    for (const scale of [0.4, 1, 2.5]) {
      expect(nameOf(builtPinch({ scale })), `scale ${scale}`).toBe("cancel");
    }
    expect(nameOf(builtPinch({ mirror: true }))).toBe("cancel");
  });

  it("6. a point is still point", () => {
    expect(nameOf(point())).toBe("point");
  });

  it("7. an open hand is still stop", () => {
    expect(nameOf(openPalm())).toBe("stop");
  });

  it("8. both hands read the same", () => {
    for (const mirror of [false, true]) {
      for (const [label, thumb] of FIST_THUMBS) {
        expect(nameOf(builtHand({ thumb, origin: [0.5, 0.6], mirror })), `${label} mirror=${mirror}`).toBe("none");
      }
      expect(nameOf(builtHand({ thumb: UP_THUMB, origin: [0.5, 0.6], mirror })), `up mirror=${mirror}`).toBe("confirm");
    }
  });

  it("9. the verdict turns over at the documented boundary, not before", () => {
    // Knuckle line is 1.0 hand-lengths from the wrist; the threshold is 1.25.
    const below = builtHand({ thumb: [-0.02, -0.06], origin: [0.5, 0.6] }); // ~1.2
    const above = builtHand({ thumb: [-0.02, -0.12], origin: [0.5, 0.6] }); // ~1.4
    expect(nameOf(below)).toBe("none");
    expect(nameOf(above)).toBe("confirm");
  });

  it("10. a hand with missing or non-finite landmarks is never a gesture", () => {
    const nan = builtHand({ thumb: UP_THUMB, origin: [0.5, 0.6] });
    nan[4] = [Number.NaN, Number.NaN, 0];
    expect(nameOf(nan)).toBe("none");

    const short = builtHand({ thumb: UP_THUMB, origin: [0.5, 0.6] }).slice(0, 20);
    expect(nameOf(short)).toBe("none");

    const degenerate = Array.from({ length: 21 }, () => [0.5, 0.5, 0]);
    expect(nameOf(degenerate)).toBe("none");
  });
});
