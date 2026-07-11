# Archived documentation

**These documents are finished or superseded. They are kept for history — not as current
guidance.** For how ARIA works today, see [`../architecture.md`](../architecture.md),
[`../decisions.md`](../decisions.md), and the [root README](../../README.md).

Much of this material describes the **server-side perception era** — when the camera and
microphone were opened on the server and frames moved over a gRPC `PerceptionService` and a
NATS bus. That architecture has been retired in favor of browser-side perception (see
[`../plans/2026-07-11-a2-browser-perception-design.md`](../plans/2026-07-11-a2-browser-perception-design.md)).

## Contents

| File | What it was |
|------|-------------|
| [roadmap-weekly.md](roadmap-weekly.md) | The v1–v3 weekly improvement roadmap (gRPC, NATS, CoreML/ANE). Superseded by the restructure design. |
| [naming-audit-2026-04.md](naming-audit-2026-04.md) | The April 2026 cross-layer naming audit. |
| [known-issues-v3.md](known-issues-v3.md) | The v3.0.0 known-issues snapshot. |
| [plans/2026-03-26-grpc-transport-layer.md](plans/2026-03-26-grpc-transport-layer.md) | Completed plan: gRPC transport (retired). |
| [plans/2026-03-30-ane-acceleration.md](plans/2026-03-30-ane-acceleration.md) | Completed plan: CoreML / Apple Neural Engine acceleration. |
| [plans/2026-03-30-grpc-priority-interrupt.md](plans/2026-03-30-grpc-priority-interrupt.md) | Completed plan: gRPC priority interrupt (moved browser-side). |
| [plans/2026-07-10-phase-3-data-layer.md](plans/2026-07-10-phase-3-data-layer.md) | Completed: Phase 3 data layer. |
| [plans/2026-07-10-phase-4-auth-security.md](plans/2026-07-10-phase-4-auth-security.md) | Completed: Phase 4 auth + security (Clerk). |
| [plans/2026-07-10-phase-5-deploy.md](plans/2026-07-10-phase-5-deploy.md) | Completed: Phase 5 deploy. The living runbook is [`../DEPLOY.md`](../DEPLOY.md). |
| [plans/2026-07-10-phase-6-reliability.md](plans/2026-07-10-phase-6-reliability.md) | Completed: Phase 6 reliability. |
</content>
