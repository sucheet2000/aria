# Security Policy

ARIA is a real-time multimodal AI voice companion. It handles a live camera
and microphone in the browser, streams audio to a server for transcription,
and talks to paid third-party APIs (Claude, ElevenLabs). Because of that, we
take security reports seriously and ask that they be disclosed privately.

## Supported versions

ARIA is under active development and ships from the `main` branch. Security
fixes are applied to the latest `main`; there is no long-term-support branch
today. Please always test against the current `main` before reporting.

## Reporting a vulnerability

**Please do not open a public GitHub issue for a security problem.**

Report privately through one of these channels:

1. **GitHub Private Vulnerability Reporting (preferred).** Go to the
   repository's **Security** tab and choose **Report a vulnerability**. This
   opens a private advisory visible only to the maintainer.
2. **Email.** If you cannot use GitHub, email the maintainer at
   **sucheet2000@gmail.com** with the subject line `ARIA SECURITY`.

Please include, as far as you can:

- A description of the issue and the component it affects (Go server, Python
  FastAPI pipeline, or Next.js frontend).
- Steps to reproduce, or a proof-of-concept.
- The impact you believe it has (data exposure, unauthorized spend on a paid
  API, remote code execution, etc.).
- Any suggested remediation.

### What to expect

- We aim to acknowledge a report within **5 business days**.
- We will confirm the issue, keep you updated on remediation progress, and
  credit you in the release notes if you would like.
- Please give us a reasonable window to ship a fix before any public
  disclosure. We follow a coordinated-disclosure approach.

## Security posture (important context for reviewers)

ARIA is currently a **single-user** application. Authentication is being
hardened as the project moves to a cloud deployment (Railway backend + Vercel
frontend), and the data model is being migrated to a **multi-user-ready**
shape keyed by an `owner` / `user_id`. Until that work lands, assume:

- The service is intended for a single trusted operator, not open multi-tenant
  use.
- Some endpoints and the WebSocket stream may not yet enforce per-user
  authorization.
- Secrets (Claude / ElevenLabs API keys) are supplied via environment
  variables and must never be committed.

If you find a gap in this transition — for example a data path that is not
`owner`-scoped, an unauthenticated money-spending endpoint, or a secret that
leaks into logs or a URL — that is exactly the kind of report we want.

## Out of scope

- Reports that require a compromised operator machine or physical access.
- Denial-of-service from unrealistic request volumes against a local dev
  instance.
- Findings in third-party dependencies that already have a public advisory and
  a pending Dependabot update.

Thank you for helping keep ARIA and its users safe.
