import { describe, it, expect, vi, afterEach } from "vitest";
// Import the real Next.js config so we assert on the exact header the app ships.
import nextConfig from "../../next.config.mjs";

async function resolveHeaders(): Promise<Record<string, string>> {
  const headers = await nextConfig.headers!();
  const rule = headers.find((h) => h.source === "/:path*");
  expect(rule, "expected a headers() rule for /:path*").toBeTruthy();
  const map: Record<string, string> = {};
  for (const h of rule!.headers) {
    map[h.key] = h.value;
  }
  return map;
}

async function resolveCsp(): Promise<Record<string, string[]>> {
  const all = await resolveHeaders();
  const value = all["Content-Security-Policy"];
  expect(value, "expected a Content-Security-Policy header").toBeTruthy();
  const map: Record<string, string[]> = {};
  for (const part of value.split(";")) {
    const tokens = part.trim().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) continue;
    map[tokens[0]] = tokens.slice(1);
  }
  return map;
}

describe("Content-Security-Policy header", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("locks the document base and forbids plugins/objects", async () => {
    const csp = await resolveCsp();
    expect(csp["default-src"]).toEqual(["'self'"]);
    expect(csp["base-uri"]).toEqual(["'self'"]);
    expect(csp["object-src"]).toEqual(["'none'"]);
  });

  it("allows MediaPipe WASM + CDN in script-src", async () => {
    const csp = await resolveCsp();
    expect(csp["script-src"]).toContain("'wasm-unsafe-eval'");
    expect(csp["script-src"]).toContain("https://cdn.jsdelivr.net");
    // Next.js App Router injects inline bootstrap/hydration scripts.
    expect(csp["script-src"]).toContain("'unsafe-inline'");
  });

  it("allows the Clerk frontend API + Turnstile in script-src", async () => {
    const csp = await resolveCsp();
    expect(csp["script-src"]).toContain(
      "https://learning-stork-27.clerk.accounts.dev",
    );
    expect(csp["script-src"]).toContain("https://challenges.cloudflare.com");
  });

  it("allows MediaPipe fetches, the backend, and Clerk in connect-src", async () => {
    const csp = await resolveCsp();
    // MediaPipe wasm binary + models.
    expect(csp["connect-src"]).toContain("https://cdn.jsdelivr.net");
    expect(csp["connect-src"]).toContain("https://storage.googleapis.com");
    // Clerk auth API + telemetry.
    expect(csp["connect-src"]).toContain(
      "https://learning-stork-27.clerk.accounts.dev",
    );
    expect(csp["connect-src"]).toContain("https://clerk-telemetry.com");
    // Production backend (Railway) over both HTTP and WS.
    expect(csp["connect-src"]).toContain(
      "https://aria-production-5ec8.up.railway.app",
    );
    expect(csp["connect-src"]).toContain(
      "wss://aria-production-5ec8.up.railway.app",
    );
    // Local dev backend must not be blocked by the app-wide CSP.
    expect(csp["connect-src"]).toContain("http://localhost:8080");
    expect(csp["connect-src"]).toContain("ws://localhost:8080");
  });

  it("permits blob: media (TTS) and blob: workers (MediaPipe)", async () => {
    const csp = await resolveCsp();
    // TTS plays the fetched MP3 through a blob: URL.
    expect(csp["media-src"]).toContain("'self'");
    expect(csp["media-src"]).toContain("blob:");
    // MediaPipe threaded WASM spins up workers from blob: URLs.
    expect(csp["worker-src"]).toContain("'self'");
    expect(csp["worker-src"]).toContain("blob:");
  });

  it("permits Clerk avatars/inline styles/fonts and frames Turnstile", async () => {
    const csp = await resolveCsp();
    expect(csp["img-src"]).toEqual(
      expect.arrayContaining(["'self'", "data:", "https:"]),
    );
    expect(csp["style-src"]).toContain("'unsafe-inline'");
    expect(csp["font-src"]).toEqual(
      expect.arrayContaining(["'self'", "data:"]),
    );
    expect(csp["frame-src"]).toContain("https://challenges.cloudflare.com");
    expect(csp["form-action"]).toContain("'self'");
  });

  it("gates 'unsafe-eval' to non-production only", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const prod = await resolveCsp();
    expect(prod["script-src"]).not.toContain("'unsafe-eval'");
    expect(prod["script-src"]).toContain("'wasm-unsafe-eval'");
  });

  it("forbids framing the app to block clickjacking", async () => {
    const csp = await resolveCsp();
    expect(csp["frame-ancestors"]).toEqual(["'self'"]);
  });
});

describe("companion security response headers", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("scopes camera/mic to same-origin and denies geolocation", async () => {
    const headers = await resolveHeaders();
    expect(headers["Permissions-Policy"]).toBe(
      "camera=(self), microphone=(self), geolocation=()",
    );
  });

  it("blocks MIME sniffing", async () => {
    const headers = await resolveHeaders();
    expect(headers["X-Content-Type-Options"]).toBe("nosniff");
  });

  it("limits referrer leakage across origins", async () => {
    const headers = await resolveHeaders();
    expect(headers["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
  });
});
