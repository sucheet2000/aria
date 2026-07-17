# Phase 4 — Auth (Clerk) + Security Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Put ARIA behind real authentication (Clerk) and close the launch-blocking audit findings — so nothing reaches the backend, the WebSocket, or the paid endpoints without a valid signed-in user, and one user can never receive another's live feed.

**Architecture — Go is the single auth boundary.** The browser authenticates with Clerk and attaches a Clerk-issued JWT to every backend call. The **Go server verifies that JWT once** (Clerk JWKS), extracts the Clerk user id, and treats it as the `owner`. The **Python FastAPI service stays internal** (127.0.0.1, never public) and trusts an `X-Aria-Owner` header that Go sets *after* verification — so `get_current_owner()` (the Phase-3 seam) reads that header instead of a constant. This means only ONE service verifies tokens, and the frontend routes **all** calls through Go (removing the direct `:8000` MemoryPanel call).

**Tech Stack:** Clerk (`@clerk/nextjs` frontend; `clerk-sdk-go/v2` for JWT verification in Go), Go 1.26 (chi middleware, gorilla/websocket), Python 3.13 FastAPI, Next.js 14. Verify current Clerk API via context7/Clerk docs during implementation.

**Risk:** HIGH — auth on the critical path; a wrong check locks you out or leaves a hole. Every task is TDD. Verify-twice before merge. Fully reversible (feature-flagged by presence of Clerk env keys — see rollback).

---

## Prerequisite (you, ~10 min, before 4a lands)

Create a Clerk application and provide its keys — I can't do this for you:
1. Sign up at clerk.com → create an application (Email + Google, or your choice).
2. Copy: **Publishable Key**, **Secret Key**, and the **JWKS/Issuer URL** (Clerk dashboard → API Keys / JWT).
3. Set them as env: locally in `frontend/.env.local` (`NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`) and `backend/.env` (`CLERK_SECRET_KEY`, `CLERK_JWT_ISSUER`); in Phase 5, as Vercel + Railway secrets.

**Dependencies added (flagged per your rules):** `@clerk/nextjs` (frontend), `github.com/clerk/clerk-sdk-go/v2` (Go). **No new Python dependency** (it trusts Go's header). I'll pin the Go dep in `go.mod` and note the frontend dep in `package.json` — you approve at the commit.

---

## Sub-phase 4a — Auth gate (nothing reaches the backend unauthenticated)

Own PR. This is the core; 4b/4c build on it.

- **Frontend (Clerk):** wrap `app/layout.tsx` in `<ClerkProvider>`, add `clerkMiddleware` (`middleware.ts`), a sign-in page, and gate the app. In the API hooks (`useCognition`, `useTTS`, `useAnchorHydration`, `deleteAnchorFn`, `MemoryPanel`) attach the Clerk JWT via `Authorization: Bearer <getToken()>`. **Route MemoryPanel through Go** (`:8080`) instead of `:8000`.
- **Go auth middleware:** new `internal/auth` package — `Middleware` that reads `Authorization: Bearer`, verifies the Clerk JWT (`clerk-sdk-go` JWKS, cached), extracts `sub` (user id), stores it in request context, and returns 401 on missing/invalid. Apply to the whole `/api` group. On the proxied calls to Python, set `X-Aria-Owner: <userid>`.
- **Python:** change `get_current_owner()` to read `request.headers["X-Aria-Owner"]`, falling back to `DEFAULT_OWNER` only when absent (local dev without Go in front). Bind Python to `127.0.0.1`.
- **TDD:** Go — table tests for the middleware (valid token → owner in ctx + 200; missing/expired/wrong-issuer → 401) using a locally-signed test JWT + a stub JWKS. Python — `get_current_owner` returns the header value; falls back to default when absent. Frontend — build/type-check green with Clerk wired.
- **Verify:** `/api/*` returns 401 without a token; 200 with a valid Clerk session; the owner flows Clerk → Go → Python → the Phase-3 owner-scoped data.

## Sub-phase 4b — WebSocket auth + per-session broadcast scoping (fixes audit H1)

Own PR.

- **WS auth:** browser WebSockets can't set `Authorization`, so the frontend passes the Clerk JWT as a query param (`ws://…/ws?token=<jwt>`); `ServeWs` verifies it (same verifier as 4a) **before** upgrading, and binds the authenticated user/session to the `Client`. Replace `CheckOrigin: true` with the origin allow-list.
- **Per-session scoping:** the hub currently fans **every** frame (live mic transcript + face/hand landmarks) to **all** clients. Change `Hub.Broadcast` → deliver only to the client(s) of the owning session/user. This closes the covert-surveillance leak (H1).
- **TDD:** Go — WS upgrade rejected without/with-bad token; a broadcast reaches only the owning session's client, not others.
- **Verify:** two authenticated sessions don't see each other's transcript/vision frames; unauthenticated WS is rejected.

## Sub-phase 4c — Rate limiting + CORS allow-list + bind (fixes H2, H3, M-S2)

Own PR.

- **Rate limiting (H2):** per-user (from the verified owner) token-bucket + a global ceiling on the paid endpoints (`/api/cognition`, `/api/tts`); 429 on exceed. Go middleware (`golang.org/x/time/rate`).
- **CORS (H3):** replace `Access-Control-Allow-Origin: *` with a strict allow-list from env (the Vercel frontend origin).
- **Bind/body caps:** default `HOST=127.0.0.1`; `http.MaxBytesReader` on the paid endpoints; note Railway fronts Go with TLS in Phase 5.
- **TDD:** Go — Nth request over the limit → 429; disallowed Origin → no ACAO; oversized body → 413.

---

## Verification strategy (each sub-phase)

1. Backend gate: `make lint-go && make test-go` (Go, with -race); `ruff && mypy && pytest` (Python). Frontend `lint/type-check/build`.
2. Manual + Playwright verify-twice: sign in via Clerk → app works; sign out → 401/redirect; open a second browser/user → no cross-user WS feed; hammer `/api/cognition` → 429.

## Rollback / safety

- **Feature-flagged by config:** if `CLERK_JWT_ISSUER` is unset (local dev), the Go middleware is bypassed and Python's `get_current_owner` falls back to `DEFAULT_OWNER` — so the app still runs locally without Clerk, and a revert is clean.
- Auth is additive middleware; no data migration. Reverting the PR removes the gate without touching data.

## Out of scope → Phase 5

Actual Railway + Vercel deploy, secrets wiring, `wss`/https, and the Dockerfiles (deferred here) all land in Phase 5.

## Security-review follow-ups (tracked)

From the 4a adversarial review (`aria-security-reviewer`):
- **[Phase 5 deploy invariant]** Python trusts `X-Aria-Owner` unconditionally, so **Python `:8000` must never be internet-reachable** — bind loopback / private network only Go can reach; never publicly map the port on Railway. Defense-in-depth: a shared `X-Internal-Auth` secret header Go sets and Python requires, so an accidental exposure doesn't grant header forgery.
- **[Multi-tenant data-partitioning]** Go's in-memory working/episodic caches (`internal/memory`, cognition client) are process-global, not owner-scoped — no leak while single-user, but must be keyed by owner (or the Go-side `/api/memory/working` dropped in favor of the owner-scoped Python path) before real multi-tenancy is enabled.
- **[Done in 4a]** Fail-open flag fixed (fail-closed on non-loopback bind without a secret); issuer enforced via `CLERK_JWT_ISSUER`.
