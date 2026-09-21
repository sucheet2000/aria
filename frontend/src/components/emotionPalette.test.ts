// Workstream N — the renderer looked its emotion up in a palette table and
// fell back to `idle` on a miss. The vocabulary has seven emotions; the table
// had four of them. So "sad", "angry" and "disgusted" rendered as the same
// calm blue as no emotion at all, silently, because a missing key and a
// deliberate neutral were indistinguishable.
import { describe, it, expect } from "vitest";
import { EMOTION_PALETTE_KEY, STATE_PALETTES } from "./SkullAvatar";

// The vocabulary the AVATAR actually receives. avatarEmotion is written by
// cognition, never by browser perception (ariaStore says so explicitly), so the
// authority is Go's suggestAvatarEmotion in internal/cognition/client.go — not
// the vision classifier's list.
//
// The first version of this suite watched EmotionClassifier.EMOTIONS, and the
// final code review showed why that was wrong: it added a ninth return value to
// the Go emitter, both suites passed, and it rendered as idle — the exact bug
// this file exists to prevent. That list only appeared to work because it
// happens to be a superset today.
//
// Keep this in step with suggestAvatarEmotion. docs/STANDARDS_DEBT.md tracks
// the wider duplication as ARCH-3.
const EMITTED_BY_COGNITION = [
  "neutral",
  "happy",
  "sad",
  "angry",
  "surprised",
  "fearful",
  "disgusted",
  "frustrated",
  "distressed",
];
const EMITTED = EMITTED_BY_COGNITION;

describe("every emitted emotion has a deliberate visual state", () => {
  it("maps each one to a palette that exists", () => {
    const unmapped: string[] = [];
    for (const emotion of EMITTED) {
      const key = EMOTION_PALETTE_KEY[emotion];
      if (key === undefined || STATE_PALETTES[key] === undefined) {
        unmapped.push(emotion);
      }
    }
    expect(unmapped).toEqual([]);
  });

  it("does not quietly render a real emotion as idle", () => {
    // `neutral` is legitimately calm. Everything else must look like something.
    const renderedAsIdle = EMITTED.filter(
      (e) => e !== "neutral" && EMOTION_PALETTE_KEY[e] === "idle",
    );
    expect(renderedAsIdle).toEqual([]);
  });

  it("gives the negative emotions a visibly different palette from neutral", () => {
    const neutral = STATE_PALETTES[EMOTION_PALETTE_KEY.neutral];
    for (const e of ["sad", "angry", "disgusted", "frustrated"]) {
      const pal = STATE_PALETTES[EMOTION_PALETTE_KEY[e]];
      expect(pal.iris, `${e} is indistinguishable from neutral`).not.toBe(neutral.iris);
    }
  });

  it("an unknown label still renders rather than crashing", () => {
    expect(EMOTION_PALETTE_KEY["not-an-emotion"]).toBeUndefined();
  });
});
