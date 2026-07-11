<!-- ARIA PR template. The checklist maps to docs/STANDARDS.md rule IDs. -->

## What & why
<!-- One or two plain-English sentences: what this changes and why. -->

## How verified
<!-- Commands run + result. Screenshots for any UI change. -->

## Definition of Done (docs/STANDARDS.md)
- [ ] Tests written first; `make check` green (pytest + go -race + vitest + lint + type-check)
- [ ] No new MUST-rule violation; grandfathered items in `docs/STANDARDS_DEBT.md` untouched or reduced
- [ ] Secrets & persist paths env-driven; fail-closed guards intact (SEC-2, DATA-1, FE-4)
- [ ] Owner-scoping preserved on all data paths (SEC-3, DATA-6)
- [ ] New deps pinned + hashed + declared + audited (DEP-1..5)
- [ ] New routes: structured JSON log + error metric + request-id + response_model (OBS/API)
- [ ] Contract changes in one source of truth, versioned (API-1, API-2)
- [ ] a11y checked on any UI change: label, contrast, focus, reduced-motion (FE-1)
- [ ] No secret in a URL / no `token=` in a WS URL (SEC-1)

## Debt burned down (if any)
<!-- If this PR fixes a docs/STANDARDS_DEBT.md row: name the rule ID, delete the row, and flip its
     CI check to gating in this same PR. -->
