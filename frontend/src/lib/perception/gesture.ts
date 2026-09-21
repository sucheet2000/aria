// TS port of backend/app/pipeline/gesture_classifier.py (single-hand path only;
// the vestigial two-hand classifier is intentionally dropped). Input is 21
// MediaPipe hand landmarks as number[][] ([x, y, z], y increases downward).

export const HAND_GESTURE_UNSPECIFIED = 0;
export const HAND_GESTURE_NONE = 1;
export const HAND_GESTURE_THUMB_UP = 2;
export const HAND_GESTURE_OPEN_PALM = 3;
export const HAND_GESTURE_PINCH = 4;
export const HAND_GESTURE_POINT = 5;

export interface HandGesture {
  gestureType: number;
  confidence: number;
  pointingVector: [number, number, number] | null;
}

type Landmarks = readonly number[][];

const WRIST = 0;
const THUMB_TIP = 4;
const INDEX_MCP = 5;
const INDEX_TIP = 8;
const MIDDLE_MCP = 9;
const MIDDLE_TIP = 12;
const RING_MCP = 13;
const RING_TIP = 16;
const PINKY_MCP = 17;
const PINKY_TIP = 20;

const GESTURE_NAMES: Record<number, string> = {
  [HAND_GESTURE_UNSPECIFIED]: "none",
  [HAND_GESTURE_NONE]: "none",
  [HAND_GESTURE_THUMB_UP]: "confirm",
  [HAND_GESTURE_OPEN_PALM]: "stop",
  [HAND_GESTURE_PINCH]: "cancel",
  [HAND_GESTURE_POINT]: "point",
};

export function gestureName(gestureType: number): string {
  return GESTURE_NAMES[gestureType] ?? "none";
}

function y(lm: Landmarks, i: number): number {
  return lm[i][1];
}

function isExtended(lm: Landmarks, tip: number, mcp: number, margin = 0.02): boolean {
  return y(lm, tip) < y(lm, mcp) - margin;
}

function isCurled(lm: Landmarks, tip: number, mcp: number, margin = 0.02): boolean {
  return y(lm, tip) > y(lm, mcp) + margin;
}

// A thumbs-up is the thumb held CLEAR OF THE FIST, and "clear" is the whole
// difference: in a fist the thumb lies ON the curled fingers, in a thumbs-up it
// touches nothing. So that is what is measured — the gap from the thumb tip to
// the nearest finger BONE, in hand-lengths.
//
// Two earlier rules failed here and are worth recording. Counting curled
// fingers and checking the thumb sat above the wrist is true of every raised
// fist, so a resting closed hand was reported as "confirm". Measuring how far
// the thumb reached along the palm axis failed the other way: an adversarial
// review built hands from published segment geometry and found a real thumb
// reaches only 1.10-1.30 hand-lengths while a folded one reaches up to 1.15 —
// the two overlap, so no threshold on reach can separate them. The rule that
// shipped briefly kept 3.2% of real thumbs-up and dropped a webcam-facing one
// outright, because it normalised by handScale twice and amplified MediaPipe's
// worst-estimated axis.
//
// Clearance was measured against the same model across 172,800 thumbs-up and
// 116,208 fist poses, over 36 camera orientations and four depth-noise regimes.
// It is the only candidate that is flat under z jitter (12.4% -> 12.8% error),
// because it is a distance between two points rather than a ratio of them.
// At 0.21 it keeps ~85% of thumbs-up for ~5% fist false-accepts; the knee is
// asymmetric in that direction, so it is priced deliberately toward not
// claiming a fist is a gesture.
const THUMB_CLEARANCE_MIN = 0.21;

// The twelve finger bones: three per finger, excluding the thumb's own and the
// palm. Distance to a SEGMENT, not to a joint — a thumb resting mid-shaft
// between two knuckles is touching the hand, and measuring only to landmarks
// misses that (7 percentage points of error).
const FINGER_BONES: ReadonlyArray<readonly [number, number]> = [
  [INDEX_MCP, 6], [6, 7], [7, INDEX_TIP],
  [MIDDLE_MCP, 10], [10, 11], [11, MIDDLE_TIP],
  [RING_MCP, 14], [14, 15], [15, RING_TIP],
  [PINKY_MCP, 18], [18, 19], [19, PINKY_TIP],
];

function segmentDistance(lm: Landmarks, p: number, a: number, b: number): number {
  const ax = lm[a][0], ay = lm[a][1], az = lm[a][2] ?? 0;
  const bx = lm[b][0] - ax, by = lm[b][1] - ay, bz = (lm[b][2] ?? 0) - az;
  const px = lm[p][0] - ax, py = lm[p][1] - ay, pz = (lm[p][2] ?? 0) - az;
  const bb = bx * bx + by * by + bz * bz;
  // Clamped, so a thumb beyond either end measures to that end, not past it.
  const t = bb > 1e-12 ? Math.min(1, Math.max(0, (px * bx + py * by + pz * bz) / bb)) : 0;
  const dx = px - t * bx, dy = py - t * by, dz = pz - t * bz;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

// The smallest gap between the thumb tip and any finger bone, in hand-lengths.
// Zero when the hand has no measurable size, so a degenerate frame reads as
// "touching" and never as a thumbs-up.
function thumbClearance(lm: Landmarks): number {
  const scale = handScale(lm);
  if (!(scale > 1e-6)) return 0.0;
  let nearest = Number.POSITIVE_INFINITY;
  for (const [a, b] of FINGER_BONES) {
    const d = segmentDistance(lm, THUMB_TIP, a, b);
    if (d < nearest) nearest = d;
  }
  return nearest / scale;
}

function thumbUp(lm: Landmarks): number {
  if (y(lm, THUMB_TIP) >= y(lm, WRIST)) return 0.0;
  // A pinch satisfies this test too — thumb above wrist, fingers curled — and
  // scores a flat 0.875 here, which outranked a pinch at any gap wider than a
  // sixteenth of a palm. The closer, more specific relationship wins.
  if (pinchRatio(lm) < PINCH_MAX_RATIO) return 0.0;
  // The thumb has to be clear of the fingers, not merely somewhere above the
  // wrist. In a fist it is resting on them.
  if (thumbClearance(lm) < THUMB_CLEARANCE_MIN) return 0.0;

  const curls = [
    isCurled(lm, INDEX_TIP, INDEX_MCP),
    isCurled(lm, MIDDLE_TIP, MIDDLE_MCP),
    isCurled(lm, RING_TIP, RING_MCP),
    isCurled(lm, PINKY_TIP, PINKY_MCP),
  ].filter(Boolean).length;

  if (curls < 3) return 0.0;

  const heightRatio = Math.min(1.0, (y(lm, WRIST) - y(lm, THUMB_TIP)) * 4);
  return 0.5 + 0.5 * (curls / 4) * heightRatio;
}

function openPalm(lm: Landmarks): number {
  const fingers: Array<[number, number]> = [
    [THUMB_TIP, 2],
    [INDEX_TIP, INDEX_MCP],
    [MIDDLE_TIP, MIDDLE_MCP],
    [RING_TIP, RING_MCP],
    [PINKY_TIP, PINKY_MCP],
  ];
  const extended = fingers.filter(([tip, mcp]) => isExtended(lm, tip, mcp)).length;
  if (extended < 4) return 0.0;
  return 0.5 + 0.5 * (extended / 5);
}

function pointGesture(lm: Landmarks): number {
  if (!isExtended(lm, INDEX_TIP, INDEX_MCP)) return 0.0;
  // Bringing the thumb to the extended index tip is a pinch, not a point; the
  // two poses are otherwise identical from the curled fingers alone.
  if (pinchRatio(lm) < PINCH_MAX_RATIO) return 0.0;
  const curled = [
    isCurled(lm, MIDDLE_TIP, MIDDLE_MCP),
    isCurled(lm, RING_TIP, RING_MCP),
    isCurled(lm, PINKY_TIP, PINKY_MCP),
  ].filter(Boolean).length;
  if (curled < 2) return 0.0;
  return 0.5 + 0.5 * (curled / 3);
}

// A pinch is a relationship between two fingertips, so that is what is
// measured: thumb tip to index tip. PINCH used to be scored by a curled-finger
// count that never looked at the thumb, which made a closed fist score as a
// pinch — reported to the user as "cancel".
//
// The distance is normalized by the hand's own size (wrist to middle knuckle)
// so the verdict holds at any distance from the camera, for either hand, and
// anywhere in frame. A raw pixel threshold would only work at one depth.
const PINCH_MAX_RATIO = 0.25;

function distance(lm: Landmarks, a: number, b: number): number {
  const dx = lm[a][0] - lm[b][0];
  const dy = lm[a][1] - lm[b][1];
  const dz = (lm[a][2] ?? 0) - (lm[b][2] ?? 0);
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

// Wrist to middle knuckle: roughly constant for a given hand regardless of
// which fingers are curled, so it survives the very poses being classified.
function handScale(lm: Landmarks): number {
  return distance(lm, WRIST, MIDDLE_MCP);
}

// Fingertip gap as a fraction of hand size. Infinity when the hand has no
// measurable size, so a degenerate frame can never read as a pinch.
function pinchRatio(lm: Landmarks): number {
  const scale = handScale(lm);
  if (!(scale > 1e-6)) return Number.POSITIVE_INFINITY;
  return distance(lm, THUMB_TIP, INDEX_TIP) / scale;
}

// A pinch is made with the index finger OUT, meeting the thumb in front of the
// hand. In a fist the index is folded back into the palm and the thumb rests
// across it — a small thumb-to-index gap too, which is why the gap test alone
// reported an ordinary resting fist as "cancel"; on its own it lets through
// 30.5% of fists.
//
// What separates them is how STRAIGHT the index is: the direct knuckle-to-tip
// distance over the length of the three bones it travels. A pinching index is
// extended and curving gently (0.58-0.92); a fist's is folded back on itself
// (0.30-0.66). Measuring how far the index reached instead — which is what
// shipped briefly — cannot work: a review measured genuine pinches spanning
// 0.84-1.47 hand-lengths with a median of 1.137, so the 1.15 threshold sat
// above the median and rejected about half of all real pinches.
//
// A ratio of distances within one finger, so it survives the hand being at any
// size, distance or angle, and degrades gently under depth noise. AND'd with
// the existing gap test this keeps 84-91% of pinches while false-accepting
// 1.5-2.7% of fists.
const PINCH_INDEX_STRAIGHT_MIN = 0.6;

// Direct span over path length. 1.0 is a perfectly straight finger; a fist's
// index folds back and scores low. Zero when the bones have no length, so a
// degenerate hand is never a pinch.
function indexStraightness(lm: Landmarks): number {
  const bones =
    distance(lm, INDEX_MCP, 6) + distance(lm, 6, 7) + distance(lm, 7, INDEX_TIP);
  if (!(bones > 1e-6)) return 0.0;
  return distance(lm, INDEX_MCP, INDEX_TIP) / bones;
}

function pinchGesture(lm: Landmarks): number {
  const ratio = pinchRatio(lm);
  if (!(ratio < PINCH_MAX_RATIO)) return 0.0;
  if (indexStraightness(lm) < PINCH_INDEX_STRAIGHT_MIN) return 0.0;
  // Touching scores highest, easing to the floor at the threshold.
  return 0.5 + 0.5 * (1 - ratio / PINCH_MAX_RATIO);
}

// Every coordinate must be a real number. MediaPipe can emit NaN for a hand it
// half-lost, and comparisons against NaN are all false, which would otherwise
// silently read as "no gesture" in some branches and a confident one in others.
function landmarksAreFinite(lm: Landmarks): boolean {
  for (const p of lm) {
    if (p.length < 2) return false;
    for (let i = 0; i < 3; i += 1) {
      const v = p[i] ?? 0;
      if (!Number.isFinite(v)) return false;
    }
  }
  return true;
}

function pointingVector(lm: Landmarks): [number, number, number] {
  const mcp = lm[INDEX_MCP];
  const tip = lm[INDEX_TIP];
  const dx = tip[0] - mcp[0];
  const dy = tip[1] - mcp[1];
  const dz = (tip[2] ?? 0) - (mcp[2] ?? 0);
  const mag = Math.sqrt(dx * dx + dy * dy + dz * dz);
  if (mag < 1e-6) return [0.0, 0.0, 0.0];
  return [dx / mag, dy / mag, dz / mag];
}

function round3(v: number): number {
  return Math.round(v * 1000) / 1000;
}

export class GestureClassifier {
  classify(landmarks: Landmarks): HandGesture {
    if (landmarks.length !== 21 || !landmarksAreFinite(landmarks)) {
      return { gestureType: HAND_GESTURE_UNSPECIFIED, confidence: 0.0, pointingVector: null };
    }

    const candidates: Array<[number, number]> = [
      [HAND_GESTURE_THUMB_UP, thumbUp(landmarks)],
      [HAND_GESTURE_OPEN_PALM, openPalm(landmarks)],
      [HAND_GESTURE_POINT, pointGesture(landmarks)],
      [HAND_GESTURE_PINCH, pinchGesture(landmarks)],
    ];

    let bestType = HAND_GESTURE_UNSPECIFIED;
    let bestConf = 0.0;
    for (const [gType, conf] of candidates) {
      if (conf > bestConf) {
        bestConf = conf;
        bestType = gType;
      }
    }

    let vector: [number, number, number] | null = null;
    if (bestType === HAND_GESTURE_POINT && bestConf > 0) {
      vector = pointingVector(landmarks);
    }

    if (bestConf < 0.5) {
      return { gestureType: HAND_GESTURE_UNSPECIFIED, confidence: 0.0, pointingVector: null };
    }

    return { gestureType: bestType, confidence: round3(bestConf), pointingVector: vector };
  }
}
