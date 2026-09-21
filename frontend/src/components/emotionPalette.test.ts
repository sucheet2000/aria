// Workstream N — the renderer looked its emotion up in a palette table and
// fell back to `idle` on a miss. The vocabulary has seven emotions; the table
// had four of them. So "sad", "angry" and "disgusted" rendered as the same
// calm blue as no emotion at all, silently, because a missing key and a
// deliberate neutral were indistinguishable.
import { describe, it, expect } from "vitest";
import { EMOTION_PALETTE_KEY, STATE_PALETTES } from "./SkullAvatar";
import { EmotionClassifier } from "@/lib/perception/emotion";

// The full vocabulary, plus the extra labels cognition has been observed to
// emit beyond the vision classifier's set.
const EMITTED = [...EmotionClassifier.EMOTIONS, "frustrated", "distressed"];

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
