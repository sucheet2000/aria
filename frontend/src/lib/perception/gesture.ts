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

// A thumbs-up is the thumb held CLEAR OF THE FIST. The two tests that used to
// stand for that — thumb tip above the wrist, three or more fingers curled —
// are both true of every raised fist, so a resting closed hand was reported as
// "confirm" (and, where the folded thumb happened to sit near the index tip,
// as "cancel"). The fixture that was supposed to catch it placed the thumb
// BELOW the wrist, which no raised fist has, so it passed on an accident.
//
// The evidence that actually separates the two poses is how far the thumb
// reaches along the hand's own axis. Measured from the wrist towards the middle
// knuckle and divided by that same length, the knuckle line sits at 1.0: a
// folded thumb lies short of it, an extended one reaches well past. Because
// both the measurement and its unit come from the hand, this holds at any size,
// any distance, either hand, and any rotation — unlike a rule written in image
// coordinates, which a tilted fist defeats.
const THUMB_EXTENSION_MIN = 1.25;

// How far a fingertip reaches along the hand's own axis, in hand-lengths from
// the wrist. The knuckle line is 1.0 by construction, so this reads directly:
// below 1 the tip is inside the palm, above 1 it is out past the knuckles.
function reachAlongPalm(lm: Landmarks, tip: number): number {
  const scale = handScale(lm);
  if (!(scale > 1e-6)) return 0.0;
  const ax = (lm[MIDDLE_MCP][0] - lm[WRIST][0]) / scale;
  const ay = (lm[MIDDLE_MCP][1] - lm[WRIST][1]) / scale;
  const az = ((lm[MIDDLE_MCP][2] ?? 0) - (lm[WRIST][2] ?? 0)) / scale;
  const tx = lm[tip][0] - lm[WRIST][0];
  const ty = lm[tip][1] - lm[WRIST][1];
  const tz = (lm[tip][2] ?? 0) - (lm[WRIST][2] ?? 0);
  return (tx * ax + ty * ay + tz * az) / scale;
}

function thumbExtension(lm: Landmarks): number {
  return reachAlongPalm(lm, THUMB_TIP);
}

function thumbUp(lm: Landmarks): number {
  if (y(lm, THUMB_TIP) >= y(lm, WRIST)) return 0.0;
  // A pinch satisfies this test too — thumb above wrist, fingers curled — and
  // scores a flat 0.875 here, which outranked a pinch at any gap wider than a
  // sixteenth of a palm. The closer, more specific relationship wins.
  if (pinchRatio(lm) < PINCH_MAX_RATIO) return 0.0;
  // The thumb has to be out of the fist, not merely somewhere above the wrist.
  if (thumbExtension(lm) < THUMB_EXTENSION_MIN) return 0.0;

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
// across it — a small thumb-to-index gap too, which is why gap alone reported
// an ordinary resting fist as "cancel". Requiring the index to be clear of the
// knuckles separates the two without the classifier needing to know what a
// fist is, which matters because the contract has no value for one.
const PINCH_INDEX_OUT_MIN = 1.15;

function pinchGesture(lm: Landmarks): number {
  const ratio = pinchRatio(lm);
  if (!(ratio < PINCH_MAX_RATIO)) return 0.0;
  if (reachAlongPalm(lm, INDEX_TIP) < PINCH_INDEX_OUT_MIN) return 0.0;
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
