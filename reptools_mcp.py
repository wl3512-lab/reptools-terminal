"""
RepTools ops MCP server (optional, for Claude Code).

Exposes a few READ-ONLY tools so Claude can inspect the live system without
hand-writing scripts each time. Secrets come from env vars (never hardcoded):
  DATABASE_URL           - Supabase pooled connection (port 6543)
  RENDER_API_KEY         - Render API token
  TRACKINGMORE_API_KEY   - TrackingMore key
  RENDER_SERVICE_ID      - defaults to the reptools service

Enable by adding this to .mcp.json (see bottom of this file) and:
  pip install mcp psycopg2-binary
It is intentionally read-only — no writes, no deploys, no deletes.
"""
import os
import json
import urllib.request
from collections import defaultdict

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("reptools-ops")

RENDER_KEY = os.environ.get("RENDER_API_KEY", "")
TM_KEY = os.environ.get("TRACKINGMORE_API_KEY", "")
SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "srv-d60os5vgi27c73apl3p0")


@mcp.tool()
def db_query(sql: str, limit: int = 100) -> str:
    """Run a READ-ONLY SQL query against the rep.tools Postgres DB and return rows
    as JSON. Only SELECT is allowed. Use for inspecting subscriptions, clicks,
    products, tracking_reports, etc."""
    import psycopg2
    import psycopg2.extras
    s = sql.strip().rstrip(";")
    low = s.lower()
    if not low.startswith("select") or any(k in low for k in
            (" insert ", " update ", " delete ", " drop ", " alter ", " truncate ", " create ")):
        return "ERROR: only a single SELECT statement is allowed."
    dsn = os.environ.get("DATABASE_URL", "")
    if not dsn:
        return "ERROR: DATABASE_URL not set."
    if " limit " not in low:
        s += f" LIMIT {int(limit)}"
    conn = psycopg2.connect(dsn, connect_timeout=15)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(s)
        rows = [dict(r) for r in cur.fetchall()]
        return json.dumps(rows, default=str, indent=1)
    finally:
        conn.close()


@mcp.tool()
def render_status() -> str:
    """Return the latest Render deploy's status + commit for the rep.tools service."""
    if not RENDER_KEY:
        return "ERROR: RENDER_API_KEY not set."
    req = urllib.request.Request(
        f"https://api.render.com/v1/services/{SERVICE_ID}/deploys?limit=3",
        headers={"Authorization": "Bearer " + RENDER_KEY})
    data = json.loads(urllib.request.urlopen(req, timeout=20).read())
    out = []
    for it in data:
        d = it.get("deploy", it)
        out.append({"status": d.get("status"),
                    "finishedAt": d.get("finishedAt"),
                    "commit": (d.get("commit") or {}).get("message", "")[:60]})
    return json.dumps(out, indent=1)


@mcp.tool()
def tm_cost_check() -> str:
    """Audit TrackingMore for the realtime-enrich cost bug: pull recent trackings and
    flag any number created under multiple courier_codes (each is a separate charge)."""
    if not TM_KEY:
        return "ERROR: TRACKINGMORE_API_KEY not set."
    req = urllib.request.Request(
        "https://api.trackingmore.com/v4/trackings/get",
        headers={"Content-Type": "application/json", "Tracking-Api-Key": TM_KEY})
    items = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("data") or []
    by_num = defaultdict(set)
    for t in items:
        by_num[t.get("tracking_number")].add(t.get("courier_code"))
    multi = {n: sorted(cs) for n, cs in by_num.items() if len(cs) > 1}
    distinct = len(by_num)
    total = len(items)
    return json.dumps({
        "window_total_trackings": total,
        "distinct_numbers": distinct,
        "extra_creates": total - distinct,
        "multiplier": round(total / distinct, 2) if distinct else 0,
        "numbers_under_multiple_couriers": multi,
        "note": "multi-courier numbers = the realtime-enrich cost bug signature; enrich should be OFF",
    }, indent=1)


if __name__ == "__main__":
    mcp.run()

# --- To enable, add to .mcp.json in the project root: -------------------------
# {
#   "mcpServers": {
#     "reptools-ops": {
#       "command": "python",
#       "args": ["reptools_mcp.py"],
#       "env": {
#         "DATABASE_URL": "<supabase pooled url>",
#         "RENDER_API_KEY": "<render key>",
#         "TRACKINGMORE_API_KEY": "<tm key>"
#       }
#     }
#   }
# }
# Keep .mcp.json out of git (it holds secrets) — it's gitignored below.
