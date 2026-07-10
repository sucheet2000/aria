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

export const API_BASE: string =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

export const WS_URL: string =
  process.env.NEXT_PUBLIC_WS_URL ?? deriveWsUrl(API_BASE);
