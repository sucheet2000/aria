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

function thumbUp(lm: Landmarks): number {
  if (y(lm, THUMB_TIP) >= y(lm, WRIST)) return 0.0;

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
  const curled = [
    isCurled(lm, MIDDLE_TIP, MIDDLE_MCP),
    isCurled(lm, RING_TIP, RING_MCP),
    isCurled(lm, PINKY_TIP, PINKY_MCP),
  ].filter(Boolean).length;
  if (curled < 2) return 0.0;
  return 0.5 + 0.5 * (curled / 3);
}

function fist(lm: Landmarks): number {
  const curled = [
    isCurled(lm, INDEX_TIP, INDEX_MCP),
    isCurled(lm, MIDDLE_TIP, MIDDLE_MCP),
    isCurled(lm, RING_TIP, RING_MCP),
    isCurled(lm, PINKY_TIP, PINKY_MCP),
  ].filter(Boolean).length;
  if (curled < 3) return 0.0;
  return 0.5 + 0.5 * (curled / 4);
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
    if (landmarks.length !== 21) {
      return { gestureType: HAND_GESTURE_UNSPECIFIED, confidence: 0.0, pointingVector: null };
    }

    const candidates: Array<[number, number]> = [
      [HAND_GESTURE_THUMB_UP, thumbUp(landmarks)],
      [HAND_GESTURE_OPEN_PALM, openPalm(landmarks)],
      [HAND_GESTURE_POINT, pointGesture(landmarks)],
      [HAND_GESTURE_PINCH, fist(landmarks)],
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
