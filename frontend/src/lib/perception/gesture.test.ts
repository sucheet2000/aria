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
// These build hands from enforced anatomy: segment lengths are fractions of
// palm length taken from published measurements, and the builder throws if a
// pose would need a thumb longer than a thumb. The first version of these
// fixtures did not do that, and its "genuine thumbs-up" had a tip bone 4.6x
// too long — which is what a threshold then got calibrated against.

// Segment lengths as fractions of palm length (wrist -> middle MCP), from
// published adult hand anthropometry. The builder enforces them, because the
// previous fixtures did not: their "genuine thumbs-up" had a thumb distal
// phalanx of 1.146 palm-lengths against a real 0.25 — a tip bone longer than
// the whole hand — and a threshold was calibrated against it. A fixture that
// cannot exist will agree with any rule you like.
const THUMB_MC1 = 0.46;
const THUMB_PP = 0.32;
const THUMB_DP = 0.25;
const THUMB_CHAIN = THUMB_MC1 + THUMB_PP + THUMB_DP;
const THUMB_CMC_ALONG = 0.18; // how far up the palm the thumb starts
const THUMB_CMC_LATERAL = -0.28;

interface HandOpts {
  /** Where the thumb tip goes, in palm-lengths [lateral, along]. */
  thumb: [number, number];
  scale?: number;
  origin?: [number, number];
  rotation?: number;
  mirror?: boolean;
  thumbZ?: number;
}

function builtHand({
  thumb, scale = 1, origin = [0.5, 0.6], rotation = 0, mirror = false, thumbZ = 0,
}: HandOpts): number[][] {
  const PALM = 0.3; // palm length in image units before `scale`
  const cmc: [number, number] = [THUMB_CMC_LATERAL, -THUMB_CMC_ALONG];
  const span = Math.hypot(thumb[0] - cmc[0], thumb[1] - cmc[1]);
  if (span > THUMB_CHAIN) {
    throw new Error(
      `thumb tip is ${span.toFixed(3)} palm-lengths from its CMC but a thumb ` +
      `chain is only ${THUMB_CHAIN}; this hand cannot exist`,
    );
  }

  const canonical: number[][] = [];
  const set = (i: number, x: number, y: number, z = 0) => {
    canonical[i] = [x, y, z];
  };
  set(0, 0, 0); // wrist; the palm runs in -y, so the knuckle line is at -PALM

  // Thumb: joints placed along the CMC -> tip line at their real proportions,
  // so a folded thumb is short in projection and a straight one is not.
  const fracs = [0, THUMB_MC1 / THUMB_CHAIN, (THUMB_MC1 + THUMB_PP) / THUMB_CHAIN, 1];
  const reach = span / THUMB_CHAIN; // <1 when the thumb is bent
  [1, 2, 3, 4].forEach((idx, k) => {
    const f = fracs[k] * (reach > 0 ? 1 : 0);
    set(idx, cmc[0] + (thumb[0] - cmc[0]) * f, cmc[1] + (thumb[1] - cmc[1]) * f,
        k === 3 ? thumbZ : thumbZ * f);
  });

  // Four curled fingers: knuckles on the knuckle line, tips folded back toward
  // the palm, which is what makes a fist a fist.
  const cols = [-0.2, 0, 0.2, 0.4];
  [5, 9, 13, 17].forEach((mcp, k) => {
    set(mcp, cols[k], -1.0);
    set(mcp + 1, cols[k], -0.75);
    set(mcp + 2, cols[k], -0.55);
    set(mcp + 3, cols[k], -0.45);
  });

  const cos = Math.cos(rotation);
  const sin = Math.sin(rotation);
  return canonical.map(([x, y, z]) => {
    const mx = mirror ? -x : x;
    return [
      origin[0] + scale * PALM * (mx * cos - y * sin),
      origin[1] + scale * PALM * (mx * sin + y * cos),
      scale * PALM * z,
    ];
  });
}

// Poses, in palm-lengths [lateral, along-the-palm]. The knuckle line is -1.0.
//
// A thumbs-up: the thumb out to the side and up, clear of every finger bone.
const UP_THUMB: [number, number] = [-0.62, -0.85];
// Two fists, because they fail through different branches. Folded across, the
// thumb lies on the curled fingers near the index tip; tucked alongside, it
// rests against the index bones further down. Both are in CONTACT with the
// hand, which is what "fist" means and what separates them from a thumbs-up.
const FIST_THUMB: [number, number] = [-0.12, -0.46];
const FIST_THUMB_SIDE: [number, number] = [-0.21, -0.72];
const FIST_THUMBS: Array<[string, [number, number]]> = [
  ["folded across the fingers", FIST_THUMB],
  ["tucked alongside", FIST_THUMB_SIDE],
];

// A genuine pinch: the index reaches out and the thumb meets it in front of
// the palm. Where they meet is constrained by anatomy — the thumb chain is
// 1.03 palm-lengths, so the contact point cannot be far past the knuckles,
// which is exactly why index-reach cannot tell this pose from a fist.
//
// (frontend/src/lib/perception/pinch.test.ts already has a pinch factory with
// mirrored/scaled/translated variants; an earlier comment here claimed the repo
// had none, which was wrong. This one exists to exercise the thumbs-up branch
// against a pinch, not to duplicate that coverage.)
const PINCH_CONTACT: [number, number] = [-0.5, -1.15];

function builtPinch(opts: { scale?: number; origin?: [number, number]; mirror?: boolean } = {}): number[][] {
  const { scale = 1, origin = [0.5, 0.6], mirror = false } = opts;
  const lm = builtHand({ thumb: PINCH_CONTACT, scale, origin, mirror });
  const PALM = 0.3;
  const place = (x: number, y: number): number[] => [
    origin[0] + scale * PALM * (mirror ? -x : x),
    origin[1] + scale * PALM * y,
    0,
  ];
  // Index chain from its knuckle out to the contact point.
  const mcp: [number, number] = [-0.2, -1.0];
  [0.35, 0.7, 1].forEach((f, k) => {
    lm[6 + k] = place(
      mcp[0] + (PINCH_CONTACT[0] - mcp[0]) * f,
      mcp[1] + (PINCH_CONTACT[1] - mcp[1]) * f,
    );
  });
  return lm;
}

function nameOf(lm: number[][]): string {
  return gestureName(new GestureClassifier().classify(lm).gestureType);
}

describe("a raised fist is not a thumbs-up", () => {
  it("1. a genuine thumbs-up is still confirm", () => {
    expect(nameOf(builtHand({ thumb: UP_THUMB, origin: [0.5, 0.6] }))).toBe("confirm");
  });

  it.each(FIST_THUMBS)("2. a raised fist (%s) is no recognized gesture", (_label, thumb: [number, number]) => {
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

  it("9. the verdict turns over at the documented clearance, not before", () => {
    // The index bones run down x = -0.2, so a thumb tip at x = -0.2 - c sits
    // exactly c palm-lengths clear of them. The threshold is 0.21.
    const clearanceOf = (c: number) =>
      builtHand({ thumb: [-0.2 - c, -0.7], origin: [0.5, 0.6] });
    expect(nameOf(clearanceOf(0.18))).toBe("none");
    expect(nameOf(clearanceOf(0.26))).toBe("confirm");
  });

  it("11. a thumb resting mid-bone is touching the hand, not clear of it", () => {
    // Against the joints alone this thumb looks 0.22 palm-lengths away — past
    // the threshold — because the nearest KNUCKLES are at the ends of the bone
    // it is lying against. Measured to the bone itself it is 0.18 and touching.
    // Point-to-landmark would call this a thumbs-up.
    const restingOnTheShaft = builtHand({ thumb: [-0.38, -0.875], origin: [0.5, 0.6] });
    expect(nameOf(restingOnTheShaft)).toBe("none");
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
