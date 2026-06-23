---
description: Deploy rep.tools safely — pre-checks, push, monitor for zero-downtime, verify
---
Deploy the current rep.tools changes safely. Do every step:

1. Show `git status --short` and `git diff --stat` so the user can confirm what's shipping. Only stage the intended tracked files — never the `_*` / `_fqc_*` / `email_*` scratch files.
2. Compile-check changed Python: `python -m py_compile app.py database.py` (and any other edited `.py`).
3. **If the change touches the DB or a paid API (TrackingMore): STOP and state the billing/cost impact before continuing.** TM bills per unique tracking CREATED; `create`/`v3 realtime` bill, reads are free, and the same number under a different courier_code is a separate charge. Never re-enable the multi-probe China-leg enrich.
4. Commit with a clear message + the `Co-Authored-By: Claude Opus 4.8 (1M context)` trailer, then `git push origin main`.
5. Confirm the deploy landed: poll `GET https://api.render.com/v1/services/srv-d60os5vgi27c73apl3p0/deploys?limit=1` until status is `live` for this commit (trigger manually with `POST .../deploys` body `{}` if auto-deploy doesn't fire).
6. Verify zero-downtime: poll `https://rep.tools/` every 2s for ~2 min and report any non-200 (there should be 0 — deploys are zero-downtime).
7. Smoke-test and report: `/` , `/products` (expect 6,900+ items from the DB), `/tools`, and a cached `/api/track`.

Never re-add a persistent disk to render.yaml — it brings back the deploy downtime.
