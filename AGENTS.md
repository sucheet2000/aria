# ARIA — Agent Ruleset (canonical, cross-tool)

This is the shared rule file for all agent tools (Cursor, Windsurf, Gemini symlink here). Claude
Code has richer context in `CLAUDE.md`. **Edit `AGENTS.md` only** — the others are symlinks.

## Engineering Standards — Binding (read `docs/STANDARDS.md`)
Every change must satisfy `docs/STANDARDS.md`. Pre-existing violations are tracked in
`docs/STANDARDS_DEBT.md` (the ratchet — new code meets the bar; old debt doesn't block unrelated
work). Rule IDs like `DATA-1` reference `docs/STANDARDS.md`.

### Non-negotiables (a PR that breaks any of these does not merge)
- **No secret in a URL** — Clerk/internal tokens go in headers or a WS auth frame, never `?token=` (SEC-1).
- **Fail closed** — any process trusting `X-Aria-Owner`/`X-Internal-Auth` refuses to boot without
  `INTERNAL_AUTH_SECRET` when `ENV != local` (SEC-2). gRPC binds `127.0.0.1` only.
- **Owner-scope every data access** at the query layer, from the verified identity — never a body field (SEC-3, DATA-6).
- **No durable state on ephemeral FS** — every persist path is env-driven via `DATA_DIR`; no hardcoded `/app`/`./data` (DATA-1).
- **No server-side physical camera/mic capture** — banned in cloud paths; capture is browser-side (SCALE-1).
- **Every declared import is in the lockfile, pinned + hashed** — including `webrtcvad` (DEP-1, DEP-2).
- **Every third-party call has a timeout + bounded retry**; guard `response.content[0]` (REL-2).
- **Advertised retention is enforced by deletion**, not read-time filtering (DATA-3).
- **Contracts change in one source of truth**, versioned — never hand-edit one of proto/Go/pydantic/TS alone (API-1, API-2).
- **Never commit `backend/.env`; never hardcode API keys; never `git push` without an explicit instruction.**

### Before you finish any change
1. Plan file-by-file, get explicit "go" before code. 2. TDD red→green→refactor. 3. `make check`
green (pytest + go -race + vitest + lint + type-check). 4. Owner-scoping + fail-closed intact.
5. New deps pinned+hashed+declared. 6. Show the plain-English commit message; wait for approval.
7. PR to `integration` only.

---

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
|------|----------|
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
