import { describe, it, expect } from "vitest";
import { EmotionClassifier, computeActionUnits, scoreEmotions } from "./emotion";

// Ported from backend/tests/test_vision.py emotion cases + faithful action-unit
// checks. MediaPipe normalized coords: x,y in [0,1], y increases downward.

function base(count = 478, p: [number, number, number] = [0.5, 0.5, 0.0]): number[][] {
  return Array.from({ length: count }, () => [...p]);
}

// Index groups the classifier reads (mirrors emotion.py).
const BROW_UPPER = [70, 63, 105, 66, 107, 336, 296, 334, 293, 300];
const BROW_LOWER = [46, 53, 52, 65, 276, 283, 282, 295];
const EYES = [159, 386];

function setY(lm: number[][], indices: number[], y: number): void {
  for (const i of indices) lm[i] = [lm[i][0], y, 0.0];
}

function set(lm: number[][], i: number, x: number, y: number): void {
  lm[i] = [x, y, 0.0];
}

// A face whose dominant action units make "happy" the clear winner:
// wide mouth (smile≈1), raised cheeks (cheek_raise≈1), no lip depression.
function happyFace(): number[][] {
  const lm = base();
  set(lm, 10, 0.5, 0.1); // forehead
  set(lm, 152, 0.5, 0.9); // chin  -> face height 0.8
  setY(lm, EYES, 0.45);
  setY(lm, BROW_UPPER, 0.42); // small brow-eye gap -> brow_raise≈0
  setY(lm, BROW_LOWER, 0.35); // large gap -> brow_lower≈0
  set(lm, 61, 0.1, 0.6); // left mouth corner
  set(lm, 291, 0.9, 0.6); // right mouth corner -> width 0.8, norm 1.0
  set(lm, 13, 0.5, 0.6); // upper lip center -> lip_depress 0
  set(lm, 14, 0.5, 0.6); // lower lip bottom
  set(lm, 116, 0.35, 0.4); // left cheek
  set(lm, 345, 0.65, 0.4); // right cheek -> cheek_raise 1
  return lm;
}

// A face with raised brows + dropped jaw -> "surprised".
function surprisedFace(): number[][] {
  const lm = base();
  set(lm, 10, 0.5, 0.1);
  set(lm, 152, 0.5, 0.9);
  setY(lm, EYES, 0.45);
  setY(lm, BROW_UPPER, 0.25); // big brow-eye gap -> brow_raise 1
  setY(lm, BROW_LOWER, 0.3); // large gap -> brow_lower 0
  set(lm, 61, 0.4, 0.5);
  set(lm, 291, 0.6, 0.5); // narrow mouth -> smile 0
  set(lm, 13, 0.5, 0.5);
  set(lm, 14, 0.5, 0.62); // open mouth -> jaw_drop 1, lip_stretch 0
  set(lm, 116, 0.4, 0.5);
  set(lm, 345, 0.6, 0.5);
  return lm;
}

describe("computeActionUnits", () => {
  it("returns all-zero action units when the face has no height", () => {
    const au = computeActionUnits(base()); // all points identical -> fh ~ 0
    expect(au.browRaise).toBe(0);
    expect(au.browLower).toBe(0);
    expect(au.smile).toBe(0);
    expect(au.lipDepress).toBe(0);
    expect(au.jawDrop).toBe(0);
    expect(au.lipStretch).toBe(0);
    expect(au.cheekRaise).toBe(0);
  });

  it("clamps every action unit to [0, 1]", () => {
    const au = computeActionUnits(happyFace());
    for (const v of Object.values(au)) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(1);
    }
  });
});

describe("EmotionClassifier", () => {
  it("returns neutral for uniform landmarks", () => {
    const clf = new EmotionClassifier();
    const { emotion, confidence } = clf.classify(base());
    expect(emotion).toBe("neutral");
    expect(confidence).toBeGreaterThanOrEqual(0);
    expect(confidence).toBeLessThanOrEqual(1);
  });

  it("only ever emits a known emotion label", () => {
    const clf = new EmotionClassifier();
    const { emotion } = clf.classify(base());
    expect(EmotionClassifier.EMOTIONS).toContain(emotion);
  });

  it("classifies a wide-smile, raised-cheek face as happy", () => {
    const clf = new EmotionClassifier();
    const { emotion } = clf.classify(happyFace());
    expect(emotion).toBe("happy");
  });

  it("classifies a raised-brow, dropped-jaw face as surprised", () => {
    const clf = new EmotionClassifier();
    const { emotion } = clf.classify(surprisedFace());
    expect(emotion).toBe("surprised");
  });

  it("is deterministic across resets for identical input", () => {
    const clf = new EmotionClassifier();
    const a = clf.classify(happyFace());
    clf.reset();
    const b = clf.classify(happyFace());
    expect(a).toEqual(b);
  });

  it("smooths single-frame outliers via the 5-frame majority", () => {
    const clf = new EmotionClassifier();
    clf.classify(happyFace());
    clf.classify(happyFace());
    clf.classify(happyFace());
    // one surprised frame should not flip the smoothed majority
    const { emotion } = clf.classify(surprisedFace());
    expect(emotion).toBe("happy");
  });

  it("reports a heuristic confidence in [0, 1] that clears the happy threshold", () => {
    const clf = new EmotionClassifier();
    const { emotion, confidence } = clf.classify(happyFace());
    expect(emotion).toBe("happy");
    expect(confidence).toBeGreaterThanOrEqual(0.45);
    expect(confidence).toBeLessThanOrEqual(1);

    const neutral = new EmotionClassifier().classify(base());
    expect(neutral.emotion).toBe("neutral");
    expect(neutral.confidence).toBeGreaterThanOrEqual(0);
    expect(neutral.confidence).toBeLessThanOrEqual(1);
  });

  it("rounds confidence to 3 decimal places", () => {
    const clf = new EmotionClassifier();
    const { confidence } = clf.classify(happyFace());
    expect(Number.isFinite(confidence)).toBe(true);
    expect(confidence).toBe(Number(confidence.toFixed(3)));
  });
});

// The vocabulary the server accepts is a restatement of this file's labels
// (backend/app/models/schemas.py PERCEPTION_EMOTIONS, checked by
// backend/tests/test_input_contracts.py). That Python test can only watch what
// this module exports, so what it exports has to BE what the classifier emits.
// Previously EMOTIONS was hand-written beside the scoring: adding a label to
// the scoring and not to the list left both sides silent, and every frame
// carrying the new label was downgraded to "neutral" by the server forever.
describe("the exported vocabulary is the one the classifier can actually emit", () => {
  const zeroAU = {
    smile: 0, cheekRaise: 0, lipDepress: 0, browLower: 0,
    browRaise: 0, jawDrop: 0, lipStretch: 0,
  };

  it("every scored label is in EMOTIONS", () => {
    for (const [label] of scoreEmotions(zeroAU)) {
      expect(EmotionClassifier.EMOTIONS).toContain(label);
    }
  });

  it("EMOTIONS contains nothing the classifier cannot produce", () => {
    const scoredLabels = scoreEmotions(zeroAU).map(([label]) => label);
    // "neutral" is the below-threshold fallback, not a scored label.
    expect([...EmotionClassifier.EMOTIONS].sort()).toEqual(
      ["neutral", ...scoredLabels].sort(),
    );
  });
});
