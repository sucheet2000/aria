import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

import ChatPanel from "./ChatPanel";

describe("ChatPanel — accessible names", () => {
  beforeEach(() => {
    // jsdom does not implement scrollIntoView — stub it for the auto-scroll effect.
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    cleanup();
  });

  it("labels the message input for assistive tech", () => {
    render(<ChatPanel />);
    expect(screen.getByRole("textbox", { name: /message/i })).toBeTruthy();
  });

  it("exposes an accessible name on the send button", () => {
    render(<ChatPanel />);
    expect(screen.getByRole("button", { name: /send/i })).toBeTruthy();
  });
});
