import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import type { PerceptionFrame } from "@/store/ariaStore";
import { parseWsFrame } from "./wsMessages";

const validFrame: PerceptionFrame = {
  face_landmarks: [[0, 0, 0]],
  emotion: "neutral",
  head_pose: { pitch: 0, yaw: 0, roll: 0 },
  hand_landmarks: [],
  timestamp: 123,
};

function frame(msg: unknown): string {
  return JSON.stringify(msg);
}

describe("parseWsFrame", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  describe("happy path narrowing", () => {
    it("narrows aria_sleep", () => {
      expect(parseWsFrame(frame({ type: "aria_sleep" }))).toEqual({
        type: "aria_sleep",
      });
    });

    it("narrows wake_word", () => {
      expect(parseWsFrame(frame({ type: "wake_word" }))).toEqual({
        type: "wake_word",
      });
    });

    it("narrows vision_state with a nested payload", () => {
      const result = parseWsFrame(
        frame({ type: "vision_state", payload: validFrame })
      );
      expect(result).toEqual({ type: "vision_state", frame: validFrame });
    });

    it("narrows a bare perception frame with no type field", () => {
      const result = parseWsFrame(frame(validFrame));
      expect(result).toEqual({ type: "vision_state", frame: validFrame });
    });

    it("narrows aria_interrupt and lifts session_id from the top level", () => {
      const result = parseWsFrame(
        frame({ type: "aria_interrupt", session_id: "sess-123" })
      );
      expect(result).toEqual({
        type: "aria_interrupt",
        sessionId: "sess-123",
      });
    });

    it("narrows transcript and passes the payload through", () => {
      const payload = { is_final: true, transcript: "hello", confidence: 0.9 };
      const result = parseWsFrame(frame({ type: "transcript", payload }));
      expect(result).toEqual({ type: "transcript", payload });
    });

    it("keeps an interim transcript (is_final:false) rather than dropping it", () => {
      const payload = { is_final: false, transcript: "partial" };
      const result = parseWsFrame(frame({ type: "transcript", payload }));
      expect(result).toEqual({ type: "transcript", payload });
    });

    it("narrows anchor_registered with a nested payload", () => {
      const result = parseWsFrame(
        frame({ type: "anchor_registered", payload: { anchor_id: "a1" } })
      );
      expect(result).toEqual({
        type: "anchor_registered",
        anchor: { anchor_id: "a1" },
      });
    });

    it("narrows anchor_registered when the frame itself is the payload", () => {
      const result = parseWsFrame(
        frame({ type: "anchor_registered", anchor_id: "a1" })
      );
      expect(result).toEqual({
        type: "anchor_registered",
        anchor: { type: "anchor_registered", anchor_id: "a1" },
      });
    });
  });

  describe("drop path returns null", () => {
    it("drops invalid JSON", () => {
      expect(parseWsFrame("{not json")).toBeNull();
    });

    it("drops JSON null", () => {
      expect(parseWsFrame("null")).toBeNull();
    });

    it("drops a bare number", () => {
      expect(parseWsFrame("42")).toBeNull();
    });

    it("drops a bare string", () => {
      expect(parseWsFrame('"hello"')).toBeNull();
    });

    it("drops an array", () => {
      expect(parseWsFrame("[1,2,3]")).toBeNull();
    });

    it("drops an unknown type", () => {
      expect(parseWsFrame(frame({ type: "aria_response" }))).toBeNull();
    });

    it("drops a transcript missing its payload", () => {
      expect(parseWsFrame(frame({ type: "transcript" }))).toBeNull();
    });

    it("drops a transcript whose payload is not an object", () => {
      expect(
        parseWsFrame(frame({ type: "transcript", payload: "oops" }))
      ).toBeNull();
    });

    it("drops a vision_state missing required keys", () => {
      expect(
        parseWsFrame(
          frame({ type: "vision_state", payload: { emotion: "neutral" } })
        )
      ).toBeNull();
    });

    it("drops aria_interrupt with a non-string session_id", () => {
      expect(
        parseWsFrame(frame({ type: "aria_interrupt", session_id: 42 }))
      ).toBeNull();
    });

    it("drops aria_interrupt with an absent session_id", () => {
      expect(parseWsFrame(frame({ type: "aria_interrupt" }))).toBeNull();
    });
  });

  describe("logging (metadata only, never payload)", () => {
    it("warns on a drop with the reason and type but no payload contents", () => {
      const result = parseWsFrame(
        frame({ type: "aria_response", payload: { transcript: "SECRET_PII_XYZ" } })
      );

      expect(result).toBeNull();
      expect(warnSpy).toHaveBeenCalled();

      const serialized = JSON.stringify(warnSpy.mock.calls);
      expect(serialized).toContain("unknown-type");
      expect(serialized).toContain("aria_response");
      expect(serialized).not.toContain("SECRET_PII_XYZ");
    });

    it("never logs the raw string on an invalid-json drop", () => {
      parseWsFrame("SECRET_PII_XYZ{not json");

      const serialized = JSON.stringify(warnSpy.mock.calls);
      expect(serialized).toContain("invalid-json");
      expect(serialized).not.toContain("SECRET_PII_XYZ");
    });

    it("does not warn on a valid frame", () => {
      parseWsFrame(frame({ type: "aria_sleep" }));
      expect(warnSpy).not.toHaveBeenCalled();
    });
  });
});
