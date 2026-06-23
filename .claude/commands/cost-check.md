---
description: Audit TrackingMore credit usage — detect runaway tracking creates
---
Audit TrackingMore usage for a cost spike, using the `TRACKINGMORE_API_KEY` (Render env).

1. `GET https://api.trackingmore.com/v4/trackings/get` with no params (returns the ~200 most-recent trackings; pagination params 400).
2. Group by `tracking_number`. **Flag any number created under MULTIPLE `courier_code`s** — that's the signature of the realtime-enrich cost bug (the same number under takesend/sfcservice/yunexpress/4px/cainiao = a separate billable create each).
3. Bucket `created_at` by day; report creates/day, the count of multi-courier "wasted" creates, and the multiplier (total creates ÷ distinct numbers).

Reminders: TM bills per unique tracking CREATED (reads are free). The China-leg enrich (`CHINA_LEG_ENRICH_ENABLED`) must stay OFF. Conclude whether usage looks organic or like a bug, and if a bug, where it's coming from.
