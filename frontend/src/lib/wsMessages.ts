import type { PerceptionFrame } from "@/store/ariaStore";

export interface TranscriptPayload {
  is_final?: boolean;
  transcript?: string;
  confidence?: number;
}

export type AriaWsMessage =
  | { type: "aria_sleep" }
  | { type: "wake_word" }
  | { type: "vision_state"; frame: PerceptionFrame }
  | { type: "aria_interrupt"; sessionId: string }
  | { type: "transcript"; payload: TranscriptPayload }
  | { type: "anchor_registered"; anchor: Record<string, unknown> };

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isString(v: unknown): v is string {
  return typeof v === "string";
}

function isNumber(v: unknown): v is number {
  return typeof v === "number";
}

function isPerceptionFrame(v: unknown): v is PerceptionFrame {
  return (
    isObject(v) &&
    Array.isArray(v.face_landmarks) &&
    Array.isArray(v.hand_landmarks) &&
    isObject(v.head_pose) &&
    isString(v.emotion) &&
    isNumber(v.timestamp)
  );
}

// Metadata-only drop log. NEVER pass the parsed payload, transcript text,
// landmark data, or the raw frame string here — those are the user's raw
// speech / PII. Coerce the discriminator to a string tag only.
function logDrop(type: unknown, reason: string): void {
  const tag = typeof type === "string" ? type : typeof type;
  console.warn("[wsMessages] dropped frame", { type: tag, reason });
}

export function parseWsFrame(raw: string): AriaWsMessage | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    logDrop(undefined, "invalid-json");
    return null;
  }

  if (!isObject(parsed)) {
    logDrop(undefined, "not-an-object");
    return null;
  }

  const type = parsed.type;

  if (type === "aria_sleep") {
    return { type: "aria_sleep" };
  }

  if (type === "wake_word") {
    return { type: "wake_word" };
  }

  if (type === "vision_state" || !type) {
    const content = parsed.payload ?? parsed;
    if (!isPerceptionFrame(content)) {
      logDrop(type, "invalid-vision-frame");
      return null;
    }
    return { type: "vision_state", frame: content };
  }

  if (type === "aria_interrupt") {
    if (!isString(parsed.session_id)) {
      logDrop(type, "invalid-interrupt");
      return null;
    }
    return { type: "aria_interrupt", sessionId: parsed.session_id };
  }

  if (type === "transcript") {
    if (!isObject(parsed.payload)) {
      logDrop(type, "invalid-transcript");
      return null;
    }
    return { type: "transcript", payload: parsed.payload as TranscriptPayload };
  }

  if (type === "anchor_registered") {
    const content = parsed.payload ?? parsed;
    if (!isObject(content)) {
      logDrop(type, "invalid-anchor");
      return null;
    }
    return { type: "anchor_registered", anchor: content };
  }

  logDrop(type, "unknown-type");
  return null;
}
