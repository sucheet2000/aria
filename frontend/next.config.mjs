/** @type {import('next').NextConfig} */

// ---------------------------------------------------------------------------
// Content-Security-Policy
//
// Applied to every route via headers(). The allowlist is derived from what the
// app actually loads/connects to so a wrong entry can't silently take down auth
// or the avatar. Group ownership of each source is documented inline.
// ---------------------------------------------------------------------------

// Clerk's frontend API (FAPI) host. clerk-js and every auth request come from
// here. It is encoded in the publishable key (pk_test_<base64(host)$>), so we
// derive it from env and fall back to the known dev instance — this stays
// correct if the Clerk instance changes without a manual CSP edit.
const CLERK_FAPI_FALLBACK = "learning-stork-27.clerk.accounts.dev";

function clerkFapiHost() {
  const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;
  if (!key) return CLERK_FAPI_FALLBACK;
  try {
    const encoded = key.replace(/^pk_(test|live)_/, "");
    const host = Buffer.from(encoded, "base64")
      .toString("utf8")
      .replace(/\$+$/, "")
      .trim();
    return /^[a-zA-Z0-9.-]+$/.test(host) ? host : CLERK_FAPI_FALLBACK;
  } catch {
    return CLERK_FAPI_FALLBACK;
  }
}

// Backend origins the browser talks to: HTTP (cognition/tts/memory/anchors)
// and WS (main + audio). Derived from NEXT_PUBLIC_* so local dev (localhost:8080)
// keeps working under the app-wide CSP; the Railway prod host is always pinned.
function backendOrigins() {
  const origins = new Set();
  const add = (u) => {
    try {
      origins.add(new URL(u).origin);
    } catch {
      /* ignore malformed env */
    }
  };
  const apiBase = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8080";
  add(apiBase);
  add(apiBase.replace(/^http:\/\//, "ws://").replace(/^https:\/\//, "wss://"));
  if (process.env.NEXT_PUBLIC_WS_URL) add(process.env.NEXT_PUBLIC_WS_URL);
  if (process.env.NEXT_PUBLIC_AUDIO_WS_URL)
    add(process.env.NEXT_PUBLIC_AUDIO_WS_URL);
  add("https://aria-production-5ec8.up.railway.app");
  add("wss://aria-production-5ec8.up.railway.app");
  return [...origins];
}

function buildCsp() {
  const isDev = process.env.NODE_ENV !== "production";
  const clerk = `https://${clerkFapiHost()}`;

  const directives = {
    "default-src": ["'self'"],
    "script-src": [
      "'self'",
      // Next.js App Router injects inline bootstrap + hydration scripts; Clerk's
      // non-nonce CSP also requires it. (Nonce-based strict CSP is a follow-up.)
      "'unsafe-inline'",
      // MediaPipe compiles the tasks-vision WASM module.
      "'wasm-unsafe-eval'",
      // Next dev/HMR (React Refresh) evals in development only — never in prod.
      ...(isDev ? ["'unsafe-eval'"] : []),
      // MediaPipe wasm glue JS.
      "https://cdn.jsdelivr.net",
      // Clerk (clerk-js is served from the dev instance's FAPI host).
      clerk,
      // Clerk Turnstile bot-protection widget.
      "https://challenges.cloudflare.com",
    ],
    "connect-src": [
      "'self'",
      // API + WebSocket backend (dev localhost + prod Railway).
      ...backendOrigins(),
      // MediaPipe .wasm binary fetch.
      "https://cdn.jsdelivr.net",
      // MediaPipe .task model files.
      "https://storage.googleapis.com",
      // Clerk auth API.
      clerk,
      // Clerk telemetry.
      "https://clerk-telemetry.com",
    ],
    // Clerk avatars (img.clerk.com), MediaPipe canvas snapshots, user images.
    "img-src": ["'self'", "data:", "https:"],
    // Next / Tailwind / Clerk inject inline styles (and SSR'd style attributes).
    "style-src": ["'self'", "'unsafe-inline'"],
    "font-src": ["'self'", "data:"],
    // TTS plays the fetched MP3 via a blob: URL.
    "media-src": ["'self'", "blob:"],
    // MediaPipe threaded WASM spins up workers from blob: URLs.
    "worker-src": ["'self'", "blob:"],
    // Clerk (session iframe) + Turnstile challenge iframe.
    "frame-src": ["'self'", clerk, "https://challenges.cloudflare.com"],
    // Only this origin may frame the app — blocks clickjacking (no X-Frame-Options).
    "frame-ancestors": ["'self'"],
    "form-action": ["'self'"],
    "base-uri": ["'self'"],
    "object-src": ["'none'"],
  };

  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.join(" ")}`)
    .join("; ");
}

const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Content-Security-Policy",
            value: buildCsp(),
          },
          // ARIA's premise is browser cam/mic — scope both to same-origin so a
          // framed/injected context can't reach them; geolocation is unused.
          {
            key: "Permissions-Policy",
            value: "camera=(self), microphone=(self), geolocation=()",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
