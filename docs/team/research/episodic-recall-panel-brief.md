# Research Brief — Episodic memory recall panel

## Idea
- **Title:** Episodic memory recall panel
- **Slug:** `episodic-recall-panel`
- **Tag:** product
- **Pitch:** Add a third sidebar panel that lists the user's recent episodic
  memories by consuming the already-live, owner-scoped `GET /api/memory/episodic`,
  reusing the existing sidebar/panel pattern and `MemoryPanel`'s Clerk-bearer
  fetch. Pitched as a "frontend-only wire-up of an orphaned backend endpoint."

## Fit
**What already exists (all cited):**
- The Python endpoint is live and owner-scoped:
  `backend/app/api/cognition_route.py:150-161` — `GET /api/memory/episodic`
  returns `{"facts": [...], "count": N}` filtered by the verified `owner`
  (`Depends(get_current_owner)`), same shape as the profile endpoint at
  `cognition_route.py:141-147`.
- The frontend panel pattern is proven: `frontend/src/components/MemoryPanel.tsx`
  fetches `${API_BASE}/api/memory/profile` with a Clerk bearer token and renders
  a simple list. A new episodic panel is close to a copy with a different URL and
  label.
- Sidebar wiring lives in one file: `frontend/src/app/page.tsx` — the panel union
  type (`page.tsx:21` `type SidebarPanel = "chat" | "memory"`), the sidebar item
  list (`page.tsx:75-78`), `togglePanel` (`page.tsx:104-106`), and the render
  blocks (`page.tsx:364-374`). Adding a third panel is a small, localized edit.
- Episodic storage is real and retained-by-deletion: entries land in the
  `aria_episodic` ChromaDB collection from behavioral/visual inference with a
  30-day TTL swept by deletion (`backend/app/cognition/memory.py:157-163,
  219-228`).

**What actually has to change (the correction to the pitch):**
The pitch calls this "frontend-only." It is not. The browser talks to the **Go
server**, not Python — `API_BASE` defaults to the Go server on `:8080`
(`frontend/src/lib/config.ts`), and in cloud the Python service is internal-only
behind the Go trust boundary. The Go edge proxies `/api/memory/profile`,
`/api/anchors`, and `DELETE /api/anchors/{id}` — and **nothing for episodic**
(`backend/internal/server/server.go:99-115`; grep for `episodic` in
`internal/server/*.go` returns nothing). So the endpoint is orphaned in **two**
layers, and the build must:
1. **Go** — add `handleMemoryEpisodicProxy` (a 3-line handler mirroring
   `handleMemoryProfileProxy` at `server.go:167-169`) and register
   `r.Get("/memory/episodic", ...)` in the `/api` group (`server.go:112`); add a
   test case to the existing table at `backend/internal/server/proxy_test.go:140-165`.
2. **Frontend** — new `EpisodicPanel.tsx` (copy `MemoryPanel.tsx`, swap URL +
   label), extend the `SidebarPanel` union, add a sidebar item + icon, add a
   render block in `page.tsx`, and a vitest test (pattern:
   `frontend/src/components/ChatPanel.test.tsx`).

Files touched: `backend/internal/server/server.go`,
`backend/internal/server/proxy_test.go`, `frontend/src/app/page.tsx`,
`frontend/src/components/EpisodicPanel.tsx` (new) + its test. No Python change,
no proto/contract change (the endpoint and its JSON shape already exist).

## Prior art
This is an internal orphaned-endpoint wire-up; there is nothing external to
borrow and therefore no third-party licences to clear. The authoritative prior
art is **in-repo**: `MemoryPanel.tsx` (list panel with Clerk-bearer fetch) and
`handleMemoryProfileProxy` (`server.go:167-169`) with its owner-header proxy
(`proxyToPython`, `server.go:184-199`). The build should copy these two patterns
verbatim rather than invent anything.

## Dependencies
**None.** Contract list is empty. Frontend uses React + `@clerk/nextjs` (already
present, used by `MemoryPanel.tsx`); Go uses `chi` + `net/http` (already present).
No new library may be added under this brief (PROTOCOL Authority §5).

## Effort & risks
**Effort: S.** Each edit is small and follows an existing pattern exactly. The
only reason it is not XS is that it spans **two subsystems** (Go edge + frontend)
plus their tests, not the single frontend layer the pitch implies.

**Risks (highest first):**
1. **The selection rationale is factually wrong on two points.** The idea was
   picked this cycle as "frontend-only... no shared files with the A2 backend
   observability build." Both are false: it needs a Go edge route, and it edits
   `backend/internal/server/server.go` + `proxy_test.go` — exactly the files a
   backend-observability build (metrics/logging on the router) is most likely to
   touch. This is a real parallel-build collision risk with A2 and must be
   sequenced or overlap-checked by the Lead before building alongside A2.
2. **"Recent" ordering is not implemented.** The endpoint uses
   `memory._episodic.get(where={"owner": owner}, limit=20)`
   (`cognition_route.py:158`), which returns up to 20 rows in ChromaDB's default
   order, not recency-sorted, and — unlike `query_relevant`
   (`memory.py:206-208`) — does **not** re-filter expired-but-unswept entries.
   The panel should be labelled "episodic memory," not "recent recalls," or the
   endpoint needs a small ordering/filter change (which would pull Python into
   scope and raise effort).
3. **Modest user value / possibly sparse.** Episodic entries come only from
   behavioral/visual inference with a 30-day TTL (`memory.py:157-160`); for a
   single user the panel may often be near-empty. This is likely why it was a
   cycle-1 runner-up, not a winner.
4. **Trust-boundary change requires full security review.** A new authenticated
   data-exposing route means the build cannot skip the build-time
   `aria-security-team` / `aria-security-reviewer` pass, even though the risk is
   low.

## Security pre-check
*(aria-security-team Engagement-1 threat-model note. The Agent/Task spawn tool is
not available in this research run, so this was produced inline against the cited
code in the aria-security-team format rather than by a separate agent process.)*

New attack surface: one new authenticated `GET` proxy route on the Go edge,
mirroring the existing profile proxy — no new inbound surface beyond the
already-authenticated `/api` group (`server.go:99-101`, `RequireAuth`). Data/PII:
it exposes the caller's **own** episodic memory (behavioral/visual inferences
about them) to their own browser; there is no cross-owner exposure **provided**
the owner is taken from the verified identity, not a body/query field —
`proxyToPython` already attaches `X-Aria-Owner` from context via `setOwnerHeader`
(`server.go:190`) and the Python side owner-scopes the query
(`cognition_route.py:153,158`). Money paths: none (no Claude/ElevenLabs call).
Rules the build must satisfy: **SEC-3 / DATA-6** owner-scope from verified
identity (satisfied by reusing `proxyToPython`); **SEC-1** no secret in URL
(internal-auth stays a header); **DATA-3** retention enforced by deletion (the
episodic TTL sweep already does this — the endpoint must not become a read-time-
only filter as the sole mechanism; it currently is not); **FE-1** a11y on the new
panel (label, contrast, focus, reduced-motion). Must still pass the full
build-time security review because it touches the trust boundary and a data path.

## Red-team verdict
*(Adversarial pass prompted to KILL the idea. Run inline in this research run —
no separate Opus sub-agent process was available — but argued in good faith
against the idea.)*

- **Hidden complexity (lands a hit):** The pitch's headline — "frontend-only
  wire-up of a live endpoint" — is false. The endpoint is unreachable from the
  browser because there is no Go edge route (`server.go:99-115`). So this is a
  Go + frontend change needing a Go test, a security review, and QA — not the
  near-zero-risk frontend patch that got it selected.
- **Wrong priority / better alternative:** Episodic data is sparse
  behavioral/visual inference on a 30-day TTL; a dedicated new sidebar slot for
  it is a lot of surface for thin, often-empty content. The cheaper alternative
  is a second section/tab inside the existing `MemoryPanel` — but that still
  needs the Go route, so it does not rescue the "frontend-only" claim.
- **Conflicts with the parallel cycle:** It edits the exact backend files
  (`server.go`, `proxy_test.go`) that the already-approved A2 backend
  observability build is most likely to touch, directly contradicting the
  "non-overlapping with A2" reason it was chosen for a parallel slot.

**Verdict:** Does not fully kill the idea — the endpoint genuinely exists and the
work is genuinely small — but it strongly downgrades it: the two facts that
justified selecting it this cycle (frontend-only, no A2 overlap) are both wrong,
and its user value is modest. It should not run in parallel with A2 as-pitched.

## Recommendation
**Park.** This is a small, feasible, low-risk piece of work and worth doing
eventually — but not this cycle and not on the rationale it was selected under.
Two of the three reasons it was picked are factually wrong: it is not
frontend-only (it needs a new Go edge proxy route, because the browser reaches
Python only through the Go server, `config.ts` + `server.go:99-115`), and it
therefore shares files with the A2 backend observability build (`server.go`,
`proxy_test.go`), which is exactly what the "run it in parallel with A2" plan was
trying to avoid. On top of that, episodic memory is sparse, TTL'd inference data,
so the panel's day-one value is modest. The clean path: park it, let A2 land its
`server.go` changes first (removing the collision), then pick this up next cycle
re-scoped honestly as a small Go-route + frontend-panel change with a security
review — or fold episodic into the existing `MemoryPanel` as a second section.
Rejecting it would be wrong (it is useful and cheap); building it as-pitched this
cycle would be building on a broken premise.
