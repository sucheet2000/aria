# deploy/

Platform configuration for shipping ARIA. Full runbook: [`../docs/DEPLOY.md`](../docs/DEPLOY.md).

## `railway.json`

Backend deploy config for [Railway](https://railway.com). It builds the single
backend image from `backend/Dockerfile` (Go server + Python FastAPI + workers in
one container) and health-checks the Go server on `/health`.

`dockerfilePath` is resolved relative to the service **Root Directory**, so set
the Railway service Root Directory to `backend`. Point the service's
"Config-as-code" file at this `deploy/railway.json` (or copy it to
`backend/railway.json`) if you want the settings applied from the repo instead of
the dashboard.

The frontend deploys separately on Vercel — see [`../frontend/vercel.json`](../frontend/vercel.json).

## Two invariants (do not break)

1. **Python stays private.** Only the Go port (`$PORT`) is public. The FastAPI
   service listens on `127.0.0.1:8000` inside the container and is never mapped or
   routed publicly. Go is the only auth boundary.
2. **Set `INTERNAL_AUTH_SECRET`.** Defense-in-depth shared secret so an accidental
   exposure of `:8000` cannot forge the `X-Aria-Owner` identity header.

Required environment variables are listed in `../docs/DEPLOY.md`.
