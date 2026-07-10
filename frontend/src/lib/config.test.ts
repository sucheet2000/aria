import { describe, it, expect } from "vitest";
import { deriveWsUrl, API_BASE, WS_URL } from "./config";

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

describe("config defaults", () => {
  it("defaults API_BASE to the local Go server", () => {
    expect(API_BASE).toBe("http://localhost:8080");
  });

  it("derives WS_URL from the default API_BASE", () => {
    expect(WS_URL).toBe("ws://localhost:8080/ws");
  });
});
