import { describe, it, expect } from "vitest";
import {
  deriveWsUrl,
  deriveAudioWsUrl,
  API_BASE,
  WS_URL,
  AUDIO_WS_URL,
} from "./config";

describe("deriveWsUrl", () => {
  it("maps http to ws and appends /ws", () => {
    expect(deriveWsUrl("http://localhost:8080")).toBe("ws://localhost:8080/ws");
  });

  it("maps https to wss and appends /ws", () => {
    expect(deriveWsUrl("https://api.example.com")).toBe(
      "wss://api.example.com/ws"
    );
  });

  it("strips trailing slashes before appending /ws", () => {
    expect(deriveWsUrl("http://localhost:8080/")).toBe(
      "ws://localhost:8080/ws"
    );
  });
});

describe("deriveAudioWsUrl", () => {
  it("appends /audio to the base WS URL", () => {
    expect(deriveAudioWsUrl("ws://localhost:8080/ws")).toBe(
      "ws://localhost:8080/ws/audio"
    );
  });

  it("strips trailing slashes before appending /audio", () => {
    expect(deriveAudioWsUrl("wss://api.example.com/ws/")).toBe(
      "wss://api.example.com/ws/audio"
    );
  });
});

describe("config defaults", () => {
  it("defaults API_BASE to the local Go server", () => {
    expect(API_BASE).toBe("http://localhost:8080");
  });

  it("derives WS_URL from the default API_BASE", () => {
    expect(WS_URL).toBe("ws://localhost:8080/ws");
  });

  it("derives AUDIO_WS_URL as the /ws/audio path on the same host", () => {
    expect(AUDIO_WS_URL).toBe("ws://localhost:8080/ws/audio");
  });
});
