// Centralized backend endpoint configuration.
// Override at build/deploy time via NEXT_PUBLIC_* env vars; the defaults
// target the local Go server used in development.

export function deriveWsUrl(apiBase: string): string {
  const base = apiBase.replace(/\/+$/, "");
  const wsBase = base
    .replace(/^https:\/\//, "wss://")
    .replace(/^http:\/\//, "ws://");
  return `${wsBase}/ws`;
}

// The browser mic stream (A.2b) targets a dedicated endpoint on the same host
// as the main WS: /ws/audio. Derived from WS_URL so it inherits ws/wss + host.
export function deriveAudioWsUrl(wsUrl: string): string {
  return `${wsUrl.replace(/\/+$/, "")}/audio`;
}

export const API_BASE: string =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

export const WS_URL: string =
  process.env.NEXT_PUBLIC_WS_URL ?? deriveWsUrl(API_BASE);

export const AUDIO_WS_URL: string =
  process.env.NEXT_PUBLIC_AUDIO_WS_URL ?? deriveAudioWsUrl(WS_URL);

function pointsAtLocalhost(apiBase: string): boolean {
  try {
    const host = new URL(apiBase).hostname.toLowerCase();
    return host === "localhost" || host === "127.0.0.1" || host === "0.0.0.0";
  } catch {
    return false;
  }
}

// True only in the real deployed-misconfig case: the page is served over https
// but the resolved backend base still points at localhost/127.0.0.1. There the
// browser blocks ws://localhost as mixed content, so the mic/chat silently fail.
// Local http dev (http://localhost) and a real https backend both return false.
export function isBackendMisconfigured(apiBase: string, protocol: string): boolean {
  if (protocol !== "https:") return false;
  return pointsAtLocalhost(apiBase);
}

// Resolved once at load. On the server (no window) we assume it is fine; in the
// browser we detect the deployed-misconfig case and log a loud one-liner so the
// silent failure becomes visible.
export const backendConfigured: boolean = (() => {
  if (typeof window === "undefined") return true;
  if (isBackendMisconfigured(API_BASE, window.location.protocol)) {
    console.error(
      `[aria] Backend not configured: NEXT_PUBLIC_API_BASE is "${API_BASE}" on an ` +
        "https deployment. The browser blocks ws://localhost as mixed content, so " +
        "voice and chat will silently fail. Set NEXT_PUBLIC_API_BASE to your backend URL.",
    );
    return false;
  }
  return true;
})();
