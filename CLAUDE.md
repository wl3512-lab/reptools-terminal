# RepTools — CLAUDE.md

## Project Overview
RepTools (rep.tools / reptools.org / reptools.net) is a replica-fashion content site: product listings, package tracking, QC photo scraping, an agent **link converter**, calculators, and affiliate-link tracking. Flask, hosted on Render. Solo-operated by the owner (Lude5 on GitHub).

## Tech Stack
- **Backend:** Flask (Python), gunicorn (2 workers, --timeout 300)
- **Database:** **Postgres (Supabase)** in production via `DATABASE_URL`; SQLite fallback locally. (Migrated off SQLite-on-disk June 2026.)
- **Frontend:** Vanilla HTML/CSS/JS, Jinja2 templates, Syne + Space Mono fonts
- **Hosting:** Render (Oregon, standard plan). **No persistent disk** (removed June 2026 → zero-downtime deploys).
- **Theme:** Dark mode (#0a0a0b), cyan (#22d3ee) + purple (#a855f7) accents

## Key Files
- `app.py` — Main Flask app, all routes
- `database.py` — **Dual-dialect DB module.** Postgres (psycopg2) when `DATABASE_URL` is set, else SQLite. `_PgConn` adapts the sqlite3-style `db.execute(sql, params)` API (`?`→`%s`, RealDict rows). PG schema uses SERIAL / ON CONFLICT / `::date`.
- `bg_remover.py` — rembg background removal (3 per batch to avoid timeouts)
- `discord_webhook.py` — Discord notifications
- `email_template.py` — tracking-email templates
- `static/products.json` — product data (~6,900 items)
- `templates/` — home, products, tools, tutorial, admin_*

## Database (Postgres)
- All persistent data is in Postgres: `products`, `categories`, `clicks`, `daily_stats`, `tracking_subscriptions`, `email_log`, `email_suppression`, `site_orders`, `tracking_reports`.
- `DATABASE_URL` (Render env, sync:false) = Supabase **pooled/transaction connection (port 6543)**, NOT the direct `db.<ref>.supabase.co:5432` one (IPv6-only, won't connect from Render).
- Schema + one-time data migrations run in `init_db()` on boot, advisory-locked (`pg_advisory_xact_lock`) so 2 workers don't double-insert. All idempotent.
- `init_db()` is called at module import (per worker). Products auto-import from products.json when the table is empty.
- Local backup of prod data: `~/reptools_pg_backup.json`.

## Deployment — now ZERO-DOWNTIME
- **Deploy = `git push origin main`** (Render auto-deploys; service `srv-d60os5vgi27c73apl3p0`).
- Auto-deploy is sometimes flaky / doesn't fire on env-var changes → trigger manually: `POST https://api.render.com/v1/services/srv-d60os5vgi27c73apl3p0/deploys` body `{}` (needs the Render API key).
- Deploys are **zero-downtime** (no disk + `healthCheckPath: /`). Verified 0 blips through a live deploy. Do NOT re-add a persistent disk — it forces stop-start deploys (the old ~20-30s 502).
- `requirements.txt` must list all deps (incl. `psycopg2-binary`, `rembg[cpu]`).
- Repo is CRLF; commits show a LF→CRLF warning — harmless.

## ⚠️ Cost & paid APIs — READ BEFORE TOUCHING TRACKING
- **TrackingMore bills per unique tracking CREATED.** Reads/`get` are free, but `v3/trackings/realtime` and `create` BILL, and **the same number under a different `courier_code` is a separate charge.** A June 2026 bug probed 5 forwarder couriers per lookup via realtime → ~5-8x credit spike. The China-leg "enrich" is now **disabled** behind env `CHINA_LEG_ENRICH_ENABLED` (off). Do NOT re-enable the multi-probe version.
- **Before telling the owner a change is "safe," check the BILLING/usage impact of any paid API it touches — not just whether the site stays up.**

## Affiliate model
- **KakoBuy affiliate code: `thelude`.** This is the money. The link converter and product links use it.
- Other agents' links in the converter are stripped of affiliate codes (don't hand competitors commission).
- **NEVER risk the KakoBuy affiliate account** (no scraping/automation that could get it banned).

## Working rules (owner preferences — important)
- **NEVER change billing or make purchases without explicit approval.**
- **Don't change VISIBLE branding** (hero/H1/slogans) for SEO or otherwise without asking — SEO goes in invisible metadata only.
- **Keep solutions simple — no over-engineering.** Match the existing dark theme; mobile-responsive matters.
- Don't add unnecessary comments/docstrings/type-annotations to unchanged code.
- For the sizing/measurement tools: **ignore shoes**; the size chart is the reliable source.
- **Be honest** — admit mistakes plainly, report failures with the real output, don't claim "done/safe" without verifying the relevant dimension. The owner values this highly.

## When to use multi-agent / parallelism
- **Subagents / parallel workflows / git worktrees:** use for LARGE one-off jobs — security/bug audits, big migrations, batch content. Not for everyday edits.
- For risky DB/infra changes: validate against the real DB first, deploy behind a reversible step, verify, THEN commit the irreversible part (this is how the Postgres migration was done safely).

## Architecture patterns
- **Safe imports:** optional modules (database, discord_webhook, bg_remover) use try/except stub fallbacks so the app boots even if a dep is missing.
- **Admin:** login at `/admin` (ADMIN_PASSWORD env), analytics at `/admin/analytics`, reports `/admin/reports`, orders `/admin/orders`.
- Caches (tracking cache, image cache) are ephemeral/local — fine to lose on deploy.
