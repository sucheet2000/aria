import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock("@clerk/nextjs", () => ({
  ClerkProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SignedIn: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SignedOut: () => null,
  SignIn: () => null,
  UserButton: () => null,
  useAuth: () => ({ getToken: () => Promise.resolve("test-token") }),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  useWebSocket: () => undefined,
}));

// page.tsx mounts SkullAvatar, not Avatar3D. Mocking the wrong component left
// the real avatar rendering inside an accessibility test that believed it was
// stubbed — so the test neither exercised the real thing deliberately nor
// isolated the page as intended.
vi.mock("@/components/SkullAvatar", () => ({
  default: () => <div data-testid="avatar" />,
}));

vi.mock("@/spatial/SpatialCanvas", () => ({
  SpatialCanvas: () => <div data-testid="spatial" />,
}));

import Home from "./page";

describe("main page — icon-only controls have accessible names", () => {
  afterEach(() => {
    cleanup();
  });

  it("exposes an accessible name on the chat toggle button", () => {
    render(<Home />);
    expect(screen.getByRole("button", { name: /chat/i })).toBeTruthy();
  });

  it("exposes an accessible name on the memory toggle button", () => {
    render(<Home />);
    expect(screen.getByRole("button", { name: /memory/i })).toBeTruthy();
  });

  it("exposes an accessible name on the spatial toggle button", () => {
    render(<Home />);
    expect(screen.getByRole("button", { name: /spatial/i })).toBeTruthy();
  });

  it("exposes an accessible name on the episodic memory toggle button", () => {
    render(<Home />);
    expect(screen.getByRole("button", { name: /episodic/i })).toBeTruthy();
  });

  it("exposes an accessible name on the microphone toggle button", () => {
    render(<Home />);
    expect(screen.getByRole("button", { name: /microphone/i })).toBeTruthy();
  });

  it("labels the perception (Sense) group so the camera/mic controls are findable", () => {
    render(<Home />);
    expect(screen.getByText(/sense/i)).toBeTruthy();
  });
});
