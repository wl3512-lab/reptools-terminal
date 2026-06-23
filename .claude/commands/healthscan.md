---
description: Run an on-demand health scan of rep.tools (endpoints, Postgres, tracking)
argument-hint: "[minutes] (default 10)"
---
Run a health scan of rep.tools for `$ARGUMENTS` minutes (default 10 if no number given). Run it as a background bash loop so it doesn't block. Every ~60s check:

- HTTP status + latency of `/`, `/products`, `/tools`, `/tutorial` (expect 200, well under 1s)
- Postgres reachable + table counts stable or growing (`tracking_subscriptions`, `clicks`, `products`) — connect with the `DATABASE_URL` value (Render env; Supabase pooled, port 6543)
- A cached `/api/track` (e.g. `EB860397246CN`) returns valid data — no new TM cost (it's cached, and the China-leg enrich is disabled)

At the end report a summary: total checks, any non-200 / errors / slow (>3s), Postgres reachability, baseline→final row counts, and a clear **HEALTHY ✓ / ISSUES** verdict listing any incidents.
