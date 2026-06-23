# Email Notifications — Go-Live Checklist

The code is **done and deployed**. It already captures every "Notify Me" signup and
receives status changes. It just won't *send* until you do the 3 steps below.
Until then it safely logs "would send" (no errors, nothing lost).

## What's already built
- `/api/subscribe-tracking` — stores signups in SQLite (idempotent, no more errors)
- `/api/tm-webhook` — receives TrackingMore status pushes (free), emails subscribers once per milestone
- `/internal/recheck` — backstop that re-reads subscribed packages (free) in case a webhook is missed
- `/api/email-webhook` — auto-suppresses bounced/complained addresses
- `/u/<token>` — one-click unsubscribe
- `/admin/subscriptions` — dashboard JSON: signup + send counts (admin login required)

## Step 1 — Resend account (email sender) — ~10 min
1. Sign up at https://resend.com (free tier 3k/mo; Pro $20/mo = 50k if you grow).
2. Add & verify a sending domain — use a **subdomain**: `mail.rep.tools`.
   Resend gives you SPF + DKIM DNS records; add them at your domain registrar.
   (Subdomain keeps any deliverability issue away from your root domain.)
3. Add a DMARC record on `rep.tools`: TXT `_dmarc` = `v=DMARC1; p=none; rua=mailto:you@rep.tools`
   (start at p=none, raise to quarantine later).
4. Copy your Resend **API key**.

## Step 2 — Render environment variables
Service → Environment → add:
- `RESEND_API_KEY` = (your Resend key)  ← this is the switch that turns sending ON
- `EMAIL_FROM` = `RepTools <updates@mail.rep.tools>`
- `TM_WEBHOOK_TOKEN` = (any random string, e.g. from `openssl rand -hex 16`)
- `EMAIL_PHYSICAL_ADDRESS` = your business mailing address (CAN-SPAM requirement)
- optional `EMAIL_REPLY_TO`, `INTERNAL_TOKEN`, `SITE_BASE_URL`

## Step 3 — TrackingMore webhook
TrackingMore dashboard → Developer → Webhooks:
- URL: `https://rep.tools/api/tm-webhook?token=<your TM_WEBHOOK_TOKEN>`
- **Version: V4** (must match — we create trackings via v4)
- Enable statuses: In Transit, Out for Delivery, Delivered, Failed Attempt, Exception

## Step 4 (optional) — backstop cron
Free cron at https://cron-job.org → GET `https://rep.tools/internal/recheck?token=<TM_WEBHOOK_TOKEN>`
every 6–12h. Catches any webhook TrackingMore failed to deliver. (Render's own cron
can't read the disk, so use an external pinger — this route is built for it.)

## Step 5 (optional) — Resend event webhook for bounces
Resend dashboard → Webhooks → `https://rep.tools/api/email-webhook?token=<TM_WEBHOOK_TOKEN>`
→ enable bounced + complained. Auto-adds bad addresses to the suppression list.

## Verify it's live
- Visit `/admin/subscriptions` (logged in) → `provider_configured: true` once the key is set.
- Subscribe to one of your own packages, then watch counts climb as it moves.

## Cost
- Sending: ~$1–2/mo (Resend free tier likely covers it; $20/mo only at high volume).
- Checking for updates: **$0** — re-tracking is free; only creating a tracking costs a credit, and that already happened on first lookup.
