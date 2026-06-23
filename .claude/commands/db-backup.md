---
description: Back up the rep.tools Postgres tables to a local JSON file
---
Back up the rep.tools Postgres database to a local JSON file.

- Connect via the `DATABASE_URL` value (Render env; Supabase pooled, port 6543, `sslmode=require`).
- Dump every table: `tracking_subscriptions`, `tracking_reports`, `clicks`, `daily_stats`, `email_log`, `email_suppression`, `products`, `categories`, `site_orders`.
- Write to `~/reptools_pg_backup_<date>.json` (use a date passed in or stamp it after) with `json.dump(..., default=str)`.
- Report the file path and per-table row counts.

This includes the owner's email subscriber list — handle carefully: never print the full contents or the DB password to the chat.
