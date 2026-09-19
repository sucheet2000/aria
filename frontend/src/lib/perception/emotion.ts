// TS port of backend/app/pipeline/emotion.py — action-units + rule-scored 7
// emotions with 5-frame majority smoothing. Landmarks are MediaPipe normalized
// coords ([x, y, z], y increases downward) as number[][], matching the store's
// PerceptionFrame.face_landmarks.

export interface ActionUnits {
  browRaise: number;
  browLower: number;
  smile: number;
  lipDepress: number;
  jawDrop: number;
  lipStretch: number;
  cheekRaise: number;
}

export interface EmotionResult {
  emotion: string;
  // Heuristic score in [0, 1], rounded to 3 dp: the winning weighted
  // action-unit score; 1 - bestScore for neutral; a constant 0.5 when the
  // 5-frame majority overrides the raw frame. Higher means stronger geometric
  // evidence. NOT a calibrated probability.
  confidence: number;
}

type Landmarks = readonly number[][];

const HISTORY_SIZE = 5;
const EMOTIONS = ["neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"];

const BROW_UPPER_INDICES = [70, 63, 105, 66, 107, 336, 296, 334, 293, 300];
const BROW_LOWER_INDICES = [46, 53, 52, 65, 276, 283, 282, 295];
const EYE_INDICES = [159, 386];

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

function round3(v: number): number {
  return Math.round(v * 1000) / 1000;
}

function px(lm: Landmarks, i: number): number {
  return lm[i][0];
}

function py(lm: Landmarks, i: number): number {
  return lm[i][1];
}

function dist(lm: Landmarks, a: number, b: number): number {
  const dx = px(lm, a) - px(lm, b);
  const dy = py(lm, a) - py(lm, b);
  return Math.sqrt(dx * dx + dy * dy);
}

function avgY(lm: Landmarks, indices: number[]): number {
  let sum = 0;
  for (const i of indices) sum += py(lm, i);
  return sum / indices.length;
}

export function computeActionUnits(landmarks: Landmarks): ActionUnits {
  const zero: ActionUnits = {
    browRaise: 0,
    browLower: 0,
    smile: 0,
    lipDepress: 0,
    jawDrop: 0,
    lipStretch: 0,
    cheekRaise: 0,
  };

  const fh = dist(landmarks, 10, 152); // forehead (10) to chin (152)
  if (fh < 1e-6) return zero;

  const browUpperY = avgY(landmarks, BROW_UPPER_INDICES);
  const eyeY = avgY(landmarks, EYE_INDICES);
  const browEyeGap = (eyeY - browUpperY) / fh;
  const browRaise = clamp01((browEyeGap - 0.05) / 0.1);

  const browLowerY = avgY(landmarks, BROW_LOWER_INDICES);
  const lowerGap = (eyeY - browLowerY) / fh;
  const browLower = clamp01(1.0 - lowerGap / 0.08);

  const leftCornerX = px(landmarks, 61);
  const rightCornerX = px(landmarks, 291);
  const mouthWidth = Math.abs(rightCornerX - leftCornerX);
  const mouthWidthNorm = mouthWidth / fh;
  const smile = clamp01((mouthWidthNorm - 0.3) / 0.12);

  const upperLipY = py(landmarks, 13);
  const cornerYAvg = (py(landmarks, 61) + py(landmarks, 291)) / 2.0;
  const lipDepDiff = (cornerYAvg - upperLipY) / fh;
  const lipDepress = clamp01(lipDepDiff / 0.04);

  const lowerLipY = py(landmarks, 14);
  const mouthOpen = (lowerLipY - upperLipY) / fh;
  const jawDrop = clamp01(mouthOpen / 0.08);

  const mouthHeightRaw = Math.abs(lowerLipY - upperLipY);
  const ratio = mouthWidth / (mouthHeightRaw + 1e-6);
  const lipStretch = clamp01((ratio - 2.0) / 8.0);

  const cheekY = (py(landmarks, 116) + py(landmarks, 345)) / 2.0;
  const cheekDiff = (cornerYAvg - cheekY) / fh;
  const cheekRaise = clamp01(cheekDiff / 0.15);

  return { browRaise, browLower, smile, lipDepress, jawDrop, lipStretch, cheekRaise };
}

export class EmotionClassifier {
  static readonly EMOTIONS = EMOTIONS;

  private history: string[] = [];

  classify(landmarks: Landmarks): EmotionResult {
    const au = computeActionUnits(landmarks);

    // Insertion order matches emotion.py so that ties resolve identically
    // (first maximal score wins).
    const scored: Array<[string, number]> = [
      ["happy", au.smile * 0.5 + au.cheekRaise * 0.3 + (1.0 - au.lipDepress) * 0.2],
      ["sad", au.lipDepress * 0.5 + au.browLower * 0.3 + (1.0 - au.smile) * 0.2],
      ["angry", au.browLower * 0.6 + (1.0 - au.smile) * 0.2 + au.lipDepress * 0.2],
      ["surprised", au.browRaise * 0.4 + au.jawDrop * 0.4 + (1.0 - au.browLower) * 0.2],
      [
        "fearful",
        au.browRaise * 0.3 + au.lipStretch * 0.4 + au.jawDrop * 0.2 + (1.0 - au.smile) * 0.1,
      ],
      [
        "disgusted",
        au.lipDepress * 0.3 + au.browLower * 0.3 + (1.0 - au.smile) * 0.2 + au.cheekRaise * 0.2,
      ],
    ];

    const thresholds: Record<string, number> = {
      happy: 0.45,
      sad: 0.4,
      angry: 0.45,
      surprised: 0.4,
      fearful: 0.38,
      disgusted: 0.38,
    };

    const scores: Record<string, number> = Object.fromEntries(scored);

    // Disambiguate disgusted vs angry: require brow_lower > 0.6 for angry.
    if (scores.angry > thresholds.angry && au.browLower <= 0.6) {
      scores.angry = 0.0;
    }

    let bestEmotion = scored[0][0];
    let bestScore = scores[bestEmotion];
    for (const [emotion] of scored) {
      if (scores[emotion] > bestScore) {
        bestScore = scores[emotion];
        bestEmotion = emotion;
      }
    }

    let rawEmotion: string;
    let rawConfidence: number;
    if (bestScore < thresholds[bestEmotion]) {
      rawEmotion = "neutral";
      rawConfidence = 1.0 - bestScore;
    } else {
      rawEmotion = bestEmotion;
      rawConfidence = bestScore;
    }

    this.history.push(rawEmotion);
    if (this.history.length > HISTORY_SIZE) this.history.shift();

    const smoothed = this.majority();
    const confidence = smoothed === rawEmotion ? rawConfidence : 0.5;

    return { emotion: smoothed, confidence: round3(confidence) };
  }

  reset(): void {
    this.history = [];
  }

  private majority(): string {
    const counts = new Map<string, number>();
    let best = this.history[0];
    let bestCount = 0;
    for (const emotion of this.history) {
      const next = (counts.get(emotion) ?? 0) + 1;
      counts.set(emotion, next);
      if (next > bestCount) {
        bestCount = next;
        best = emotion;
      }
    }
    return best;
  }
}
