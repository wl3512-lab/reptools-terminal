"""
KakoBuy Tools - Web Application
A comprehensive tool for tracking packages, scraping QC photos, and reverse image search.
"""

from flask import Flask, render_template, request, jsonify, session, redirect, make_response
from flask_cors import CORS
try:
    from flask_compress import Compress
    COMPRESS_AVAILABLE = True
except ImportError:
    COMPRESS_AVAILABLE = False
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    LIMITER_AVAILABLE = True
except ImportError:
    LIMITER_AVAILABLE = False
import asyncio
import aiohttp
import re
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
import hashlib
import time
import requests as http_requests

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv()

# Database & Discord webhook modules
try:
    from database import (
        init_db, import_hardcoded_products, import_products_from_json,
        get_all_products as db_get_all_products, get_category_products as db_get_category_products,
        search_products as db_search_products, add_product as db_add_product,
        delete_product as db_delete_product, track_click, get_click_stats,
        get_product_clicks
    )
    DB_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Database module not available: {e}")
    DB_AVAILABLE = False
    def init_db(): pass
    def import_hardcoded_products(*a): return 0
    def import_products_from_json(*a): return 0
    def db_get_all_products(): return {}
    def db_get_category_products(c): return None
    def db_search_products(q, c=None, l=20): return []
    def db_add_product(p): return True
    def db_delete_product(p): return True
    def track_click(**kw): pass
    def get_click_stats(d=30): return {}
    def get_product_clicks(p): return 0

# Email-notification subscription helpers (separate import so older database.py still boots)
try:
    from database import (
        add_subscription, get_active_subscriptions, claim_notification,
        log_email, is_suppressed, add_suppression, unsubscribe_by_token,
        get_due_recheck_subscriptions,
    )
    SUBS_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] Subscription DB helpers not available: {e}")
    SUBS_AVAILABLE = False
    def add_subscription(*a, **k): return None
    def get_active_subscriptions(*a, **k): return []
    def claim_notification(*a, **k): return False
    def log_email(*a, **k): pass
    def is_suppressed(*a, **k): return False
    def add_suppression(*a, **k): pass
    def unsubscribe_by_token(*a, **k): return None
    def get_due_recheck_subscriptions(*a, **k): return []

try:
    from discord_webhook import notify_new_product, notify_bulk_products, notify_daily_stats
except ImportError:
    print("[WARNING] Discord webhook module not available")
    def notify_new_product(*a): return False
    def notify_bulk_products(*a): return False
    def notify_daily_stats(*a): return False

try:
    from bg_remover import process_and_upload, remove_bg_from_url, bulk_process_products
    BG_REMOVER_AVAILABLE = True
except ImportError:
    print("[WARNING] Background remover not available (pip install rembg)")
    BG_REMOVER_AVAILABLE = False
    def process_and_upload(url): return url
    def bulk_process_products(d): return d

try:
    from ai_tools import qc_score, visual_search, build_product_index, get_index_status, load_product_index
    from ai_tools import _get_image_from_url, _get_image_from_bytes, read_measurements, read_size_chart, estimate_qc
    from ai_tools import weidian_chart_image_urls, weidian_id_from_link
    AI_TOOLS_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] AI tools not available: {e}")
    AI_TOOLS_AVAILABLE = False

# API Keys
DHL_API_KEY = os.getenv("DHL_API_KEY", "")
CANADA_POST_API_USER = os.getenv("CANADA_POST_API_USER", "")
CANADA_POST_API_PASS = os.getenv("CANADA_POST_API_PASS", "")

# Email notifications (Phase 1). Drop in RESEND_API_KEY to go live; until then the
# system stores subscriptions + receives webhooks and just LOGS what it would send.
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "RepTools <updates@rep.tools>")
EMAIL_REPLY_TO = os.getenv("EMAIL_REPLY_TO", "")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://rep.tools")
TM_WEBHOOK_TOKEN = os.getenv("TM_WEBHOOK_TOKEN", "")  # optional shared-secret in the webhook URL query
EMAIL_PHYSICAL_ADDRESS = os.getenv("EMAIL_PHYSICAL_ADDRESS", "")  # CAN-SPAM: a real postal address in the footer
if RESEND_API_KEY and not TM_WEBHOOK_TOKEN:
    print("[APP] WARNING: RESEND_API_KEY is set but TM_WEBHOOK_TOKEN is empty -> the "
          "TrackingMore + Resend webhooks fail-closed (403); status emails and bounce "
          "suppression will NOT fire until TM_WEBHOOK_TOKEN is set + in the webhook URLs.")

# TrackingMore delivery_status -> (milestone_key, subject, headline). Only these fire emails.
EMAIL_MILESTONES = {
    "transit":      ("in_transit",      "📦 Your package is on the move",        "It's in transit!"),
    "pickup":       ("out_for_delivery", "🚚 Out for delivery",                  "Out for delivery today"),
    "delivered":    ("delivered",       "✅ Delivered",                          "Your package was delivered"),
    "undelivered":  ("failed",          "⚠️ Delivery attempt failed",            "A delivery attempt failed"),
    "exception":    ("exception",       "⚠️ There's an issue with your package", "Your package needs attention"),
}

# Professional tracking-email template (falls back to the basic _email_html if absent).
try:
    from email_template import build_tracking_email
    EMAIL_TEMPLATE_AVAILABLE = True
except Exception as _eterr:
    EMAIL_TEMPLATE_AVAILABLE = False
    print(f"[APP] email_template unavailable, using basic email body: {_eterr}")

_COUNTRY_NAMES = {
    "CN": "China", "HK": "Hong Kong", "TW": "Taiwan", "US": "United States",
    "GB": "United Kingdom", "UK": "United Kingdom", "DE": "Germany", "FR": "France",
    "CA": "Canada", "AU": "Australia", "NL": "Netherlands", "PL": "Poland",
    "IT": "Italy", "ES": "Spain", "SE": "Sweden", "NO": "Norway", "DK": "Denmark",
    "FI": "Finland", "IE": "Ireland", "BE": "Belgium", "AT": "Austria",
    "CH": "Switzerland", "PT": "Portugal", "NZ": "New Zealand", "SG": "Singapore",
    "JP": "Japan", "KR": "South Korea", "MX": "Mexico", "BR": "Brazil",
    "CZ": "Czechia", "RO": "Romania", "HU": "Hungary", "GR": "Greece",
}


def _iso_country(iso):
    """ISO-2 country code -> (name, flag emoji). ('', '') if not a valid 2-letter code."""
    iso = (iso or "").strip().upper()
    if len(iso) != 2 or not iso.isalpha():
        return "", ""
    flag = "".join(chr(0x1F1E6 + ord(c) - 65) for c in iso)
    return _COUNTRY_NAMES.get(iso, iso), flag


def _clean_carrier(code):
    return (code or "").replace("-", " ").replace("_", " ").title()


def _email_data_from_tm(tracking_number, courier_code, tm_obj):
    """Best-effort rich email fields pulled from a TrackingMore tracking object."""
    tm_obj = tm_obj or {}
    o_name, o_flag = _iso_country(tm_obj.get("origin_country") or tm_obj.get("tracking_origin_country"))
    d_name, d_flag = _iso_country(tm_obj.get("destination_country") or tm_obj.get("tracking_destination_country"))
    carrier = _clean_carrier(courier_code or tm_obj.get("courier_code") or "")
    transit = tm_obj.get("transit_time")
    data = {"tracking_number": tracking_number, "eta": "soon"}
    if carrier:
        data["origin_carrier"] = carrier
        data["dest_carrier"] = carrier
    if o_name:
        data["origin_country"] = o_name
    if o_flag:
        data["origin_flag"] = o_flag
    if d_name:
        data["dest_country"] = d_name
    if d_flag:
        data["dest_flag"] = d_flag
    if isinstance(transit, int) and transit > 0:
        data["transit_days"] = str(transit)
    return data


_STATUS_TEXT = {
    "in_transit": "Good news — your package has started moving toward you. We'll email you at the next big step.",
    "out_for_delivery": "It's on the truck for delivery today. Keep an eye out!",
    "delivered": "Your package was delivered. Enjoy your haul!",
    "failed": "The carrier tried to deliver but couldn't. Check the tracking page for what to do next.",
    "exception": "The carrier flagged an issue (often customs or an address problem). Open the tracking page for details.",
    "customs_hold": "There may be a customs/duty charge to pay before delivery. Pay only via the carrier's official site.",
}


def _send_email(to_addr, subject, html, unsubscribe_url=None, idempotency_key=None):
    """Send one email via Resend if configured, else log it. Returns (ok, provider_id|reason)."""
    if not to_addr:
        return False, "no recipient"
    if is_suppressed(to_addr):
        return False, "suppressed"
    if not RESEND_API_KEY:
        # Ascii-safe log (subjects contain emoji; some consoles are cp1252)
        print("[EMAIL] (no provider key) would send to " + to_addr)
        return False, "no_provider"
    try:
        payload = {"from": EMAIL_FROM, "to": [to_addr], "subject": subject, "html": html}
        if EMAIL_REPLY_TO:
            payload["reply_to"] = EMAIL_REPLY_TO
        if unsubscribe_url:
            # RFC 8058 one-click unsubscribe — required by Gmail/Yahoo for good deliverability
            payload["headers"] = {
                "List-Unsubscribe": f"<{unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }
        req_headers = {
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            # Resend is behind Cloudflare, which can 403 a bare default user-agent
            "User-Agent": "Mozilla/5.0 (compatible; RepToolsMailer/1.0; +https://rep.tools)",
            "Accept": "application/json",
        }
        if idempotency_key:
            # Resend dedupes sends with the same key (24h) -> no duplicate even if the
            # webhook and recheck fire concurrently for the same milestone.
            req_headers["Idempotency-Key"] = idempotency_key
        r = http_requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=req_headers,
            timeout=15,
        )
        if r.status_code in (200, 201):
            pid = ""
            try:
                pid = (r.json() or {}).get("id", "")
            except Exception:
                pass
            return True, pid
        print(f"[EMAIL] Resend error {r.status_code}: {r.text[:200]}")
        return False, f"http_{r.status_code}"
    except Exception as e:
        print(f"[EMAIL] send exception: {e}")
        return False, "exception"


def _email_html(tracking_number, carrier, headline, status_text, unsubscribe_token):
    """Branded, mobile-friendly notification email body with one-click unsubscribe + address."""
    import html as _h
    unsub = f"{SITE_BASE_URL}/u/{unsubscribe_token}"
    track_url = f"{SITE_BASE_URL}/tools#track"
    tracking_number = _h.escape(str(tracking_number))
    carrier = _h.escape(str(carrier))
    headline = _h.escape(str(headline))
    status_text = _h.escape(str(status_text))
    return f"""<!DOCTYPE html><html><body style="margin:0;background:#0a0a0b;font-family:Arial,Helvetica,sans-serif;color:#fafafa;">
<div style="max-width:480px;margin:0 auto;padding:28px 22px;">
  <div style="font-size:22px;font-weight:800;background:linear-gradient(135deg,#22d3ee,#a855f7);-webkit-background-clip:text;background-clip:text;color:#22d3ee;">RepTools</div>
  <div style="margin-top:22px;padding:22px;background:#18181b;border:1px solid #27272a;border-radius:14px;">
    <div style="font-size:18px;font-weight:700;color:#fff;">{headline}</div>
    <div style="margin-top:6px;color:#a1a1aa;font-size:14px;">{carrier} · {tracking_number}</div>
    <div style="margin-top:14px;color:#fafafa;font-size:15px;line-height:1.5;">{status_text}</div>
    <a href="{track_url}" style="display:inline-block;margin-top:18px;padding:11px 20px;background:linear-gradient(135deg,#22d3ee,#a855f7);color:#0a0a0b;text-decoration:none;border-radius:9px;font-weight:700;font-size:14px;">View full tracking →</a>
  </div>
  <div style="margin-top:18px;color:#71717a;font-size:11px;line-height:1.6;text-align:center;">
    You're getting this because you asked RepTools to notify you about this package.<br>
    <a href="{unsub}" style="color:#71717a;">Unsubscribe</a> · RepTools, rep.tools{(' · ' + EMAIL_PHYSICAL_ADDRESS) if EMAIL_PHYSICAL_ADDRESS else ''}
  </div>
</div></body></html>"""


def _notify_subscribers(tracking_number, courier_code, delivery_status, tm_obj=None):
    """Core fan-out: for a tracking's new status, email each active subscriber once.
    Used by both the webhook receiver and the periodic re-check backstop. tm_obj is
    the full TrackingMore tracking object (when available) used to enrich the email."""
    ds = (delivery_status or "").lower()
    if ds not in EMAIL_MILESTONES:
        return 0
    dedup_milestone, subject_fallback, headline = EMAIL_MILESTONES[ds]
    # Exceptions are very often a customs/duty charge in 2026 — show the clearer
    # anti-scam customs copy when the carrier text says so. The dedup key stays
    # 'exception', so this never double-sends vs. the seeded baseline.
    render_milestone = dedup_milestone
    if dedup_milestone == "exception" and tm_obj:
        blob = (str(tm_obj.get("latest_event") or "") + " " + str(tm_obj.get("substatus") or "")).lower()
        if any(w in blob for w in ("customs", "duty", "vat", "import charge", " tax")):
            render_milestone = "customs_hold"
    base_data = _email_data_from_tm(tracking_number, courier_code, tm_obj)
    carrier_name = base_data.get("dest_carrier") or "Carrier"
    sent = 0
    for sub in get_active_subscriptions(tracking_number):
        # Send-first, then mark-done — so a transient failure (provider down, domain
        # not verified yet, 5xx) is NEVER silently lost: the milestone stays unclaimed
        # and the next webhook/recheck retries it. We only mark done on success (or a
        # permanent 'suppressed'). Snapshot dedup skips milestones already handled.
        try:
            if (sub.get("last_notified_status") or "") == dedup_milestone:
                continue
            token = sub.get("unsubscribe_token", "")
            unsub_url = f"{SITE_BASE_URL}/u/{token}" if token else None
            subject, html = subject_fallback, None
            if EMAIL_TEMPLATE_AVAILABLE:
                try:
                    data = dict(base_data)
                    data["view_url"] = f"{SITE_BASE_URL}/tools#track"
                    data["unsubscribe_url"] = unsub_url or f"{SITE_BASE_URL}/tools"
                    data["physical_address"] = EMAIL_PHYSICAL_ADDRESS
                    subject, _pre, html = build_tracking_email(render_milestone, data)
                except Exception as _terr:
                    print("[EMAIL] template render error, using basic body: " + str(_terr)[:120])
                    html = None
            if html is None:
                subject = subject_fallback
                html = _email_html(tracking_number, carrier_name, headline,
                                   _STATUS_TEXT.get(render_milestone, "Your package status changed."), token)
            ok, pid = _send_email(sub["email"], subject, html, unsubscribe_url=unsub_url,
                                  idempotency_key=f"{sub['id']}-{dedup_milestone}")
            if ok or pid == "suppressed":
                claim_notification(sub["id"], dedup_milestone)  # durable mark only once handled
            if pid != "no_provider":  # don't grow email_log every cycle in log-only mode
                try:
                    log_email(sub["email"], tracking_number, dedup_milestone, pid, "sent" if ok else pid)
                except Exception:
                    pass
            if ok:
                sent += 1
        except Exception as e:
            print("[EMAIL] subscriber send error: " + str(e)[:120])
    return sent

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32).hex()

# Behind Render's proxy: trust 1 X-Forwarded-For hop so get_remote_address (rate
# limiting + click-tracking IP) keys on the REAL client IP, not the shared proxy IP.
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Google Analytics — set GA_MEASUREMENT_ID env var (G-XXXXXXXXXX) on Render to enable
GA_MEASUREMENT_ID = os.environ.get('GA_MEASUREMENT_ID', '').strip()


@app.context_processor
def _inject_ga():
    """Inject {{ ga_snippet|safe }} into every template.

    Renders a tiny fixed corner link to /privacy and /terms on every page, and —
    only when GA_MEASUREMENT_ID is set — a non-blocking dark-theme cookie-consent
    banner that GATES Google Analytics: gtag is NEVER loaded until the visitor clicks
    Accept (rt_consent=granted cookie). Decline (rt_consent=denied) blocks GA forever.
    No static gtag <script src> is emitted, so GA cannot fire before consent.
    """
    links_html = (
        '<style>\n'
        '#rt-legal-corner{position:fixed;right:10px;bottom:8px;z-index:2147483646;'
        'font-family:"Space Mono",ui-monospace,monospace;font-size:11px;line-height:1;'
        'opacity:.55;transition:opacity .15s;}\n'
        '#rt-legal-corner:hover{opacity:1;}\n'
        '#rt-legal-corner a{color:#a1a1aa;text-decoration:none;padding:0 5px;}\n'
        '#rt-legal-corner a:hover{color:#22d3ee;}\n'
        '#rt-legal-corner span{color:#3f3f46;}\n'
        '@media print{#rt-legal-corner{display:none;}}\n'
        '</style>\n'
        '<div id="rt-legal-corner">'
        '<a href="/privacy">Privacy</a><span>|</span><a href="/terms">Terms</a>'
        '</div>'
    )
    if not GA_MEASUREMENT_ID:
        # No analytics configured -> only essential session cookies exist, so no
        # consent banner is required. Still render the corner legal links.
        return {'ga_snippet': links_html}
    ga_block = r'''<!-- Google Analytics (consent-gated, ePrivacy/GDPR) -->
<script>
(function(){
  var GA_ID = "__GA_ID__";
  var COOKIE = "rt_consent";
  function readConsent(){
    var m = document.cookie.match(/(?:^|;\s*)rt_consent=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }
  function writeConsent(v){
    var oneYear = 60*60*24*365;
    var secure = (location.protocol === "https:") ? "; Secure" : "";
    document.cookie = COOKIE + "=" + v + "; Max-Age=" + oneYear +
      "; Path=/; SameSite=Lax" + secure;
  }
  var gaLoaded = false;
  function loadGA(){
    if (gaLoaded) return;
    gaLoaded = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = function(){ dataLayer.push(arguments); };
    gtag("js", new Date());
    gtag("config", GA_ID, { anonymize_ip: true });
    var s = document.createElement("script");
    s.async = true;
    s.src = "https://www.googletagmanager.com/gtag/js?id=" + GA_ID;
    (document.head || document.documentElement).appendChild(s);
  }
  function hideBanner(){
    var b = document.getElementById("rt-consent");
    if (b && b.parentNode) b.parentNode.removeChild(b);
  }
  function decide(v){
    writeConsent(v);
    hideBanner();
    if (v === "granted") loadGA();
  }
  function showBanner(){
    if (document.getElementById("rt-consent")) return;
    var wrap = document.createElement("div");
    wrap.id = "rt-consent";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("aria-label", "Cookie consent");
    wrap.innerHTML =
      '<div class="rt-consent-inner">' +
        '<p class="rt-consent-txt">We use a Google Analytics cookie to understand site usage. ' +
        'A strictly-necessary cookie just remembers your choice here. ' +
        '<a href="/privacy">Learn more</a>.</p>' +
        '<div class="rt-consent-btns">' +
          '<button type="button" id="rt-decline" class="rt-btn rt-btn-ghost">Decline</button>' +
          '<button type="button" id="rt-accept" class="rt-btn rt-btn-primary">Accept</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(wrap);
    document.getElementById("rt-accept").addEventListener("click", function(){ decide("granted"); });
    document.getElementById("rt-decline").addEventListener("click", function(){ decide("denied"); });
  }
  function init(){
    var c = readConsent();
    if (c === "granted") { loadGA(); return; }
    if (c === "denied") { return; }
    showBanner();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
</script>
<style>
#rt-consent{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;
  background:rgba(15,15,17,0.97);border-top:1px solid rgba(34,211,238,0.25);
  box-shadow:0 -8px 30px rgba(0,0,0,0.45);backdrop-filter:blur(8px);
  -webkit-backdrop-filter:blur(8px);color:#e6edf6;
  font-family:"Space Mono",ui-monospace,SFMono-Regular,monospace;}
#rt-consent .rt-consent-inner{max-width:1100px;margin:0 auto;padding:14px 18px;
  display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;}
#rt-consent .rt-consent-txt{margin:0;font-size:12.5px;line-height:1.55;color:#c9d1dc;flex:1 1 320px;}
#rt-consent .rt-consent-txt a{color:#22d3ee;text-decoration:none;}
#rt-consent .rt-consent-txt a:hover{text-decoration:underline;}
#rt-consent .rt-consent-btns{display:flex;gap:10px;flex:0 0 auto;}
#rt-consent .rt-btn{cursor:pointer;border-radius:9px;padding:9px 18px;font-size:12px;font-weight:700;
  letter-spacing:.4px;font-family:inherit;transition:transform .12s,box-shadow .12s,background .15s;}
#rt-consent .rt-btn:active{transform:translateY(1px);}
#rt-consent .rt-btn-primary{border:none;color:#06141c;
  background:linear-gradient(135deg,#22d3ee,#a855f7);box-shadow:0 4px 16px rgba(34,211,238,0.3);}
#rt-consent .rt-btn-primary:hover{box-shadow:0 6px 22px rgba(168,85,247,0.4);}
#rt-consent .rt-btn-ghost{background:transparent;border:1px solid rgba(255,255,255,0.22);color:#c9d1dc;}
#rt-consent .rt-btn-ghost:hover{border-color:#22d3ee;color:#fff;}
@media (max-width:560px){#rt-consent .rt-consent-inner{flex-direction:column;align-items:stretch;}
  #rt-consent .rt-consent-btns{justify-content:flex-end;}}
</style>'''.replace('__GA_ID__', GA_MEASUREMENT_ID)
    return {'ga_snippet': links_html + '\n' + ga_block}

# Session security
from datetime import timedelta
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
)

# CORS — only allow our own domains
CORS(app, origins=[
    "https://rep.tools", "https://www.rep.tools",
    "https://reptools.net", "https://www.reptools.net",
    "https://reptools.org", "https://www.reptools.org",
    "https://reptoolssssss.onrender.com",
])

# Gzip compression (70-90% size reduction on text responses)
if COMPRESS_AVAILABLE:
    app.config['COMPRESS_MIN_SIZE'] = 500
    app.config['COMPRESS_LEVEL'] = 6
    Compress(app)
    print("[APP] Flask-Compress enabled")

# Rate limiting to prevent API abuse / credit draining
if LIMITER_AVAILABLE:
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["500 per hour"],
        storage_uri="memory://",
    )
    print("[APP] Flask-Limiter enabled")
else:
    limiter = None


def _rl(spec):
    """Boot-safe rate-limit decorator: enforces when Flask-Limiter is available,
    no-op otherwise (keeps the app booting if the optional dep is missing)."""
    return limiter.limit(spec) if limiter else (lambda f: f)


# Cache headers for static assets
@app.after_request
def add_cache_headers(response):
    if request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'public, max-age=604800, immutable'
    elif request.path in ('/robots.txt', '/sitemap.xml'):
        response.headers['Cache-Control'] = 'public, max-age=3600'
    elif request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    if request.headers.get('X-Forwarded-Proto') == 'https' or request.is_secure:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000')
    return response

@app.before_request
def _canonical_host_redirect():
    """301 duplicate domains to the canonical host to consolidate SEO + the brand
    entity. HTTP-only — does NOT touch reptools.net email (that's DNS/SMTP)."""
    host = (request.host or '').split(':')[0].lower()
    if host in ('reptools.org', 'www.reptools.org', 'reptools.net',
                'www.reptools.net', 'www.rep.tools'):
        return redirect('https://rep.tools' + request.full_path.rstrip('?'), code=301)

@app.route('/health')
def health_check():
    return jsonify({"status": "ok"}), 200

# Initialize database on startup
init_db()
print(f"[APP] DB_AVAILABLE={DB_AVAILABLE}, BG_REMOVER_AVAILABLE={BG_REMOVER_AVAILABLE}")

# Load AI product index if available
if AI_TOOLS_AVAILABLE:
    try:
        load_product_index()
    except Exception as e:
        print(f"[APP] AI index not loaded: {e}")
    print(f"[APP] AI_TOOLS_AVAILABLE={AI_TOOLS_AVAILABLE}")

# ============== PRODUCT DATA ==============

PRODUCTS = {
    "shoes": {
        "name": "Shoes",
        "icon": "👟",
        "description": "Sneakers, boots, and slides",
        "items": [
            {"id": "sh1", "name": "Jordan 1 High", "price": "$56.92", "seller": "Various", "rating": 4.7},
            {"id": "sh2", "name": "Jordan 1 High Top", "price": "$84.62", "seller": "Various", "rating": 4.7},
            {"id": "sh3", "name": "Jordan 1 Low", "price": "$58.15", "seller": "Various", "rating": 4.7},
            {"id": "sh4", "name": "Jordan 1 Low Top", "price": "$69.23", "seller": "Various", "rating": 4.7},
            {"id": "sh5", "name": "Jordan 3", "price": "$56.92", "seller": "Various", "rating": 4.7},
            {"id": "sh6", "name": "Jordan 312", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh7", "name": "Jordan 4", "price": "$36.92", "seller": "Various", "rating": 4.7},
            {"id": "sh8", "name": "Air Jordan 5", "price": "$55.38", "seller": "Various", "rating": 4.7},
            {"id": "sh9", "name": "Jordan 6 Top", "price": "$55.38", "seller": "Various", "rating": 4.7},
            {"id": "sh10", "name": "Jordan 11 Hight", "price": "$44.31", "seller": "Various", "rating": 4.7},
            {"id": "sh11", "name": "Jordan 11", "price": "$44.31", "seller": "Various", "rating": 4.7},
            {"id": "sh12", "name": "Jordan 12", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh13", "name": "Jordan 13", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh14", "name": "Jordan 1 Low x Travis Scott", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh15", "name": "LV Trainers", "price": "$87.38", "seller": "Various", "rating": 4.7},
            {"id": "sh16", "name": "LV Skate Top", "price": "$94.92", "seller": "Various", "rating": 4.7},
            {"id": "sh17", "name": "LV Sneakers", "price": "$84.62", "seller": "Various", "rating": 4.7},
            {"id": "sh18", "name": "LV Trainer Maxi", "price": "$97.38", "seller": "Various", "rating": 4.7},
            {"id": "sh19", "name": "LV Casual", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh20", "name": "LV Abbesses", "price": "$54.62", "seller": "Various", "rating": 4.7},
            {"id": "sh21", "name": "LV Shoes", "price": "$49.23", "seller": "Various", "rating": 4.7},
            {"id": "sh22", "name": "LV Trainer", "price": "$87.38", "seller": "Various", "rating": 4.7},
            {"id": "sh23", "name": "LV Pearl Style", "price": "$96.77", "seller": "Various", "rating": 4.7},
            {"id": "sh24", "name": "LV Pudding", "price": "$96.77", "seller": "Various", "rating": 4.7},
            {"id": "sh25", "name": "LV Velcro", "price": "$86.31", "seller": "Various", "rating": 4.7},
            {"id": "sh26", "name": "LV Classic Sneakers", "price": "$91.54", "seller": "Various", "rating": 4.7},
            {"id": "sh27", "name": "LV Skate Sneakers", "price": "$88.92", "seller": "Various", "rating": 4.7},
            {"id": "sh28", "name": "LV Trainer Sneakers", "price": "$88.92", "seller": "Various", "rating": 4.7},
            {"id": "sh29", "name": "LV x Nike Shoes", "price": "$52.31", "seller": "Various", "rating": 4.7},
            {"id": "sh30", "name": "LV x Nike", "price": "$52.31", "seller": "Various", "rating": 4.7},
            {"id": "sh31", "name": "LV Slippers", "price": "$49.23", "seller": "Various", "rating": 4.7},
            {"id": "sh32", "name": "Air Force 1", "price": "$22.15", "seller": "Various", "rating": 4.7},
            {"id": "sh33", "name": "Air Force1 AY Batch", "price": "$49.23", "seller": "Various", "rating": 4.7},
            {"id": "sh34", "name": "Air Force 1 × LV", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh35", "name": "Unique Air Force 1", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh36", "name": "Nike Wmns Air Force 1 Shadow", "price": "$36.92", "seller": "Various", "rating": 4.7},
            {"id": "sh37", "name": "Nocta Hot Step 2", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh38", "name": "Nike Dunk Low", "price": "$40.31", "seller": "Various", "rating": 4.7},
            {"id": "sh39", "name": "Nike Dunk M Batch", "price": "$64.62", "seller": "Various", "rating": 4.7},
            {"id": "sh40", "name": "Nike Dunk", "price": "$40.31", "seller": "Various", "rating": 4.7},
            {"id": "sh41", "name": "Nike Dunk GX Batch", "price": "$38.46", "seller": "Various", "rating": 4.7},
            {"id": "sh42", "name": "Nike Shoes", "price": "$52.31", "seller": "Various", "rating": 4.7},
            {"id": "sh43", "name": "Nike ACG Air Zoom Gaiadome GoreTex", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh44", "name": "Nike Air Max Plus", "price": "$40.00", "seller": "Various", "rating": 4.7},
            {"id": "sh45", "name": "Nike Tn", "price": "$40.00", "seller": "Various", "rating": 4.7},
            {"id": "sh46", "name": "Nike Air", "price": "$40.00", "seller": "Various", "rating": 4.7},
            {"id": "sh47", "name": "Nike Air Max 90", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh48", "name": "Nike Air Max 95", "price": "$35.38", "seller": "Various", "rating": 4.7},
            {"id": "sh49", "name": "Nike Air Max 97", "price": "$64.15", "seller": "Various", "rating": 4.7},
            {"id": "sh50", "name": "Nike Air Max", "price": "$40.00", "seller": "Various", "rating": 4.7},
            {"id": "sh51", "name": "Nike Air Max 1", "price": "$40.00", "seller": "Various", "rating": 4.7},
            {"id": "sh52", "name": "Nike Air Max Portal", "price": "$36.92", "seller": "Various", "rating": 4.7},
            {"id": "sh53", "name": "NIike Sacai", "price": "$55.38", "seller": "Various", "rating": 4.7},
            {"id": "sh54", "name": "Nike Air Humara QS \"\"Faded Spruce\"\"\"", "price": "$58.92", "seller": "Various", "rating": 4.7},
            {"id": "sh55", "name": "Nike SB Force 58 Shoes", "price": "$33.85", "seller": "Various", "rating": 4.7},
            {"id": "sh56", "name": "Nike Shox TL", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh57", "name": "Nike P-6000", "price": "$42.77", "seller": "Various", "rating": 4.7},
            {"id": "sh58", "name": "Nike Court Borough", "price": "$34.62", "seller": "Various", "rating": 4.7},
            {"id": "sh59", "name": "Nike Air Zoom GT Cut", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh60", "name": "Nike X Kobe Bryant", "price": "$69.23", "seller": "Various", "rating": 4.7},
            {"id": "sh61", "name": "Nike Foamposite One", "price": "$104.62", "seller": "Various", "rating": 4.7},
            {"id": "sh62", "name": "Nike Air Max Tn", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh63", "name": "Nike Slippers", "price": "$16.92", "seller": "Various", "rating": 4.7},
            {"id": "sh64", "name": "Nike Air Zoom Vomero", "price": "$47.69", "seller": "Various", "rating": 4.7},
            {"id": "sh65", "name": "Dior B30 Top", "price": "$72.00", "seller": "Various", "rating": 4.7},
            {"id": "sh66", "name": "Stone Island×B30", "price": "$88.62", "seller": "Various", "rating": 4.7},
            {"id": "sh67", "name": "Diro B30 Good", "price": "$49.23", "seller": "Various", "rating": 4.7},
            {"id": "sh68", "name": "Dior B22 Top", "price": "$72.00", "seller": "Various", "rating": 4.7},
            {"id": "sh69", "name": "Dior B22 Good", "price": "$59.38", "seller": "Various", "rating": 4.7},
            {"id": "sh70", "name": "Dior B28", "price": "$55.38", "seller": "Various", "rating": 4.7},
            {"id": "sh71", "name": "Dior B27", "price": "$76.92", "seller": "Various", "rating": 4.7},
            {"id": "sh72", "name": "Dior B25", "price": "$64.62", "seller": "Various", "rating": 4.7},
            {"id": "sh73", "name": "Dior B23", "price": "$69.23", "seller": "Various", "rating": 4.7},
            {"id": "sh74", "name": "B 23 Low / High", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh75", "name": "Dior Shoes", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh76", "name": "Dior x Nike", "price": "$83.69", "seller": "Various", "rating": 4.7},
            {"id": "sh77", "name": "Dior B01 Matchpoint", "price": "$41.85", "seller": "Various", "rating": 4.7},
            {"id": "sh78", "name": "Dior B30 Countdown", "price": "$52.31", "seller": "Various", "rating": 4.7},
            {"id": "sh79", "name": "Dior B80", "price": "$47.08", "seller": "Various", "rating": 4.7},
            {"id": "sh80", "name": "Dior Slippers", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh81", "name": "Adidas Gazelle x Gucci Good", "price": "$36.92", "seller": "Various", "rating": 4.7},
            {"id": "sh82", "name": "Adidas Gazelle", "price": "$36.92", "seller": "Various", "rating": 4.7},
            {"id": "sh83", "name": "Adidas Spezial", "price": "$43.54", "seller": "Various", "rating": 4.7},
            {"id": "sh84", "name": "Adidas Samba", "price": "$33.85", "seller": "Various", "rating": 4.7},
            {"id": "sh85", "name": "Adidas Samba Good", "price": "$26.92", "seller": "Various", "rating": 4.7},
            {"id": "sh86", "name": "Adidas Campus", "price": "$37.69", "seller": "Various", "rating": 4.7},
            {"id": "sh87", "name": "Adidas x Gucci", "price": "$73.08", "seller": "Various", "rating": 4.7},
            {"id": "sh88", "name": "Adidas Yeezy 350", "price": "$43.54", "seller": "Various", "rating": 4.7},
            {"id": "sh89", "name": "Adidas Yeezy 700", "price": "$45.38", "seller": "Various", "rating": 4.7},
            {"id": "sh90", "name": "Yeezy 500", "price": "$84.62", "seller": "Various", "rating": 4.7},
            {"id": "sh91", "name": "Yeezy 700", "price": "$45.38", "seller": "Various", "rating": 4.7},
            {"id": "sh92", "name": "Adidas Ultra Boost", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh93", "name": "Adidas Originals Superstar", "price": "$36.92", "seller": "Various", "rating": 4.7},
            {"id": "sh94", "name": "Adidas Shoes", "price": "$38.46", "seller": "Various", "rating": 4.7},
            {"id": "sh95", "name": "Adidas Forum HK Batch", "price": "$64.62", "seller": "Various", "rating": 4.7},
            {"id": "sh96", "name": "Adidas XLG Runner Deluxe", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh97", "name": "Adidas Forum 84", "price": "$36.92", "seller": "Various", "rating": 4.7},
            {"id": "sh98", "name": "Adidas Futro Mixr Neo", "price": "$33.85", "seller": "Various", "rating": 4.7},
            {"id": "sh99", "name": "Adidas Slides", "price": "$13.54", "seller": "Various", "rating": 4.7},
            {"id": "sh100", "name": "Yeezy Foam", "price": "$27.69", "seller": "Various", "rating": 4.7},
            {"id": "sh101", "name": "Gucci Mac80", "price": "$55.38", "seller": "Various", "rating": 4.7},
            {"id": "sh102", "name": "Gucci Shoes", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh103", "name": "Gucci x Nike Shoes", "price": "$52.31", "seller": "Various", "rating": 4.7},
            {"id": "sh104", "name": "Gucci Slippers", "price": "$29.23", "seller": "Various", "rating": 4.7},
            {"id": "sh105", "name": "New Balance 9060", "price": "$58.15", "seller": "Various", "rating": 4.7},
            {"id": "sh106", "name": "New Balance MR993", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh107", "name": "New Balance 530", "price": "$40.62", "seller": "Various", "rating": 4.7},
            {"id": "sh108", "name": "New Balance 550", "price": "$43.54", "seller": "Various", "rating": 4.7},
            {"id": "sh109", "name": "New Balance U574", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh110", "name": "New Balance 1000", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh111", "name": "New Balance 1906R", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh112", "name": "New Balance 2002R", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh113", "name": "New Balance 610T", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh114", "name": "Stone Island X New Balance U574", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh115", "name": "MiuMiu x New Balance", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh116", "name": "New Balance 327", "price": "$30.46", "seller": "Various", "rating": 4.7},
            {"id": "sh117", "name": "New Balance 991v2", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh118", "name": "Prada Shoes", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh119", "name": "Prada High Heel", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh120", "name": "Off -White", "price": "$73.85", "seller": "Various", "rating": 4.7},
            {"id": "sh121", "name": "Off White Shoes", "price": "$100.00", "seller": "Various", "rating": 4.7},
            {"id": "sh122", "name": "Off White Ow Be Right Back", "price": "$92.31", "seller": "Various", "rating": 4.7},
            {"id": "sh123", "name": "Burberry Shoes", "price": "$51.23", "seller": "Various", "rating": 4.7},
            {"id": "sh124", "name": "Burberry", "price": "$51.23", "seller": "Various", "rating": 4.7},
            {"id": "sh125", "name": "Burberry Slippers", "price": "$21.54", "seller": "Various", "rating": 4.7},
            {"id": "sh126", "name": "Puma LX Court", "price": "$33.85", "seller": "Various", "rating": 4.7},
            {"id": "sh127", "name": "Puma Shoes", "price": "$33.85", "seller": "Various", "rating": 4.7},
            {"id": "sh128", "name": "Balenciaga Track", "price": "$89.23", "seller": "Various", "rating": 4.7},
            {"id": "sh129", "name": "Balenciaga Track Led", "price": "$112.31", "seller": "Various", "rating": 4.7},
            {"id": "sh130", "name": "Balenciaga Runner", "price": "$118.46", "seller": "Various", "rating": 4.7},
            {"id": "sh131", "name": "Balenciaga Speed Trainer", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh132", "name": "Balenciaga 3XL", "price": "$76.15", "seller": "Various", "rating": 4.7},
            {"id": "sh133", "name": "Balenciaga Defender", "price": "$93.08", "seller": "Various", "rating": 4.7},
            {"id": "sh134", "name": "Balenciaga TripleS", "price": "$98.15", "seller": "Various", "rating": 4.7},
            {"id": "sh135", "name": "Balenciaga X-pander", "price": "$118.46", "seller": "Various", "rating": 4.7},
            {"id": "sh136", "name": "Balenciaga Cargo", "price": "$93.08", "seller": "Various", "rating": 4.7},
            {"id": "sh137", "name": "Balenciaga Shoes", "price": "$82.00", "seller": "Various", "rating": 4.7},
            {"id": "sh138", "name": "Balenciaga Slippers", "price": "$30.46", "seller": "Various", "rating": 4.7},
            {"id": "sh139", "name": "Balenciaga Foam", "price": "$33.85", "seller": "Various", "rating": 4.7},
            {"id": "sh140", "name": "Alexander McQueen Shoes", "price": "$60.00", "seller": "Various", "rating": 4.7},
            {"id": "sh141", "name": "Alexander McQueen", "price": "$60.00", "seller": "Various", "rating": 4.7},
            {"id": "sh142", "name": "Valentino Shoes", "price": "$61.08", "seller": "Various", "rating": 4.7},
            {"id": "sh143", "name": "Golden Goose Shoes", "price": "$74.31", "seller": "Various", "rating": 4.7},
            {"id": "sh144", "name": "Golden Goose Low", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh145", "name": "Dolce＆Gabbana", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh146", "name": "Lanvin Shoes", "price": "$74.31", "seller": "Various", "rating": 4.7},
            {"id": "sh147", "name": "UGG Snow BootsTop", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh148", "name": "UGG Snow Boots", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh149", "name": "Loro Piana Shoes", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh150", "name": "Loro Piana", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh151", "name": "Loro Piana One kick", "price": "$44.46", "seller": "Various", "rating": 4.7},
            {"id": "sh152", "name": "Versace Chain Shoes", "price": "$81.54", "seller": "Various", "rating": 4.7},
            {"id": "sh153", "name": "Versace Shoes", "price": "$44.46", "seller": "Various", "rating": 4.7},
            {"id": "sh154", "name": "Versace Slippers", "price": "$23.54", "seller": "Various", "rating": 4.7},
            {"id": "sh155", "name": "Chanel Shoes", "price": "$69.23", "seller": "Various", "rating": 4.7},
            {"id": "sh156", "name": "Asics Gel Kajana 8", "price": "$39.23", "seller": "Various", "rating": 4.7},
            {"id": "sh157", "name": "Asics Gel 1130", "price": "$43.54", "seller": "Various", "rating": 4.7},
            {"id": "sh158", "name": "Asics Gel", "price": "$39.23", "seller": "Various", "rating": 4.7},
            {"id": "sh159", "name": "Asics Shoes", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh160", "name": "Vintage Asics", "price": "$29.23", "seller": "Various", "rating": 4.7},
            {"id": "sh161", "name": "Louboutin Shoes", "price": "$66.62", "seller": "Various", "rating": 4.7},
            {"id": "sh162", "name": "Louboutin Low", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh163", "name": "Bape Shoes", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh164", "name": "Hermes Shoes", "price": "$46.15", "seller": "Various", "rating": 4.7},
            {"id": "sh165", "name": "Hermes Bouncing", "price": "$75.85", "seller": "Various", "rating": 4.7},
            {"id": "sh166", "name": "Hermes Slippers", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh167", "name": "Amiri Shoes", "price": "$70.77", "seller": "Various", "rating": 4.7},
            {"id": "sh168", "name": "Autry Shoes", "price": "$76.92", "seller": "Various", "rating": 4.7},
            {"id": "sh169", "name": "Givenchy Shoes", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh170", "name": "Crocs Slippers", "price": "$20.46", "seller": "Various", "rating": 4.7},
            {"id": "sh171", "name": "YSL High Heel", "price": "$70.77", "seller": "Various", "rating": 4.7},
            {"id": "sh172", "name": "Saint Laurent Shoes", "price": "$64.15", "seller": "Various", "rating": 4.7},
            {"id": "sh173", "name": "Timberland Shoes", "price": "$92.31", "seller": "Various", "rating": 4.7},
            {"id": "sh174", "name": "Dsquared2 Shoes", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh175", "name": "Veja Shoes", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh176", "name": "Birkenstock Shoes", "price": "$43.08", "seller": "Various", "rating": 4.7},
            {"id": "sh177", "name": "Converse Shoes", "price": "$30.77", "seller": "Various", "rating": 4.7},
            {"id": "sh178", "name": "Fendi Shoes", "price": "$76.92", "seller": "Various", "rating": 4.7},
            {"id": "sh179", "name": "Fendi Slippers", "price": "$23.54", "seller": "Various", "rating": 4.7},
            {"id": "sh180", "name": "Maison Margiela Shoes", "price": "$45.38", "seller": "Various", "rating": 4.7},
            {"id": "sh181", "name": "Maison Margiela", "price": "$45.38", "seller": "Various", "rating": 4.7},
            {"id": "sh182", "name": "Philipp Plein Shoes", "price": "$49.23", "seller": "Various", "rating": 4.7},
            {"id": "sh183", "name": "Loewe Shoes", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh184", "name": "Salomon Shoes", "price": "$58.46", "seller": "Various", "rating": 4.7},
            {"id": "sh185", "name": "Balmain Shoes", "price": "$120.00", "seller": "Various", "rating": 4.7},
            {"id": "sh186", "name": "Vans Shoes", "price": "$38.46", "seller": "Various", "rating": 4.7},
            {"id": "sh187", "name": "Maison Minara Yasuhiro Shoes", "price": "$69.23", "seller": "Various", "rating": 4.7},
            {"id": "sh188", "name": "Bottega Veneta Shoes", "price": "$63.54", "seller": "Various", "rating": 4.7},
            {"id": "sh189", "name": "Hoka Shoes", "price": "$55.85", "seller": "Various", "rating": 4.7},
            {"id": "sh190", "name": "Boss Shoes", "price": "$53.85", "seller": "Various", "rating": 4.7},
            {"id": "sh191", "name": "Zegna Shoes", "price": "$49.23", "seller": "Various", "rating": 4.7},
            {"id": "sh192", "name": "Coach Shoes", "price": "$44.46", "seller": "Various", "rating": 4.7},
            {"id": "sh193", "name": "Ferragamo Shoes", "price": "$47.08", "seller": "Various", "rating": 4.7},
            {"id": "sh194", "name": "Ferragamo", "price": "$47.08", "seller": "Various", "rating": 4.7},
            {"id": "sh195", "name": "Brunello Cucinelli Shoes", "price": "$44.46", "seller": "Various", "rating": 4.7},
            {"id": "sh196", "name": "Dunhill Shoes", "price": "$60.15", "seller": "Various", "rating": 4.7},
            {"id": "sh197", "name": "Kiton Shoes", "price": "$47.08", "seller": "Various", "rating": 4.7},
            {"id": "sh198", "name": "Stefano Ricci Shoes", "price": "$52.31", "seller": "Various", "rating": 4.7},
            {"id": "sh199", "name": "Bally Shoes", "price": "$47.08", "seller": "Various", "rating": 4.7},
            {"id": "sh200", "name": "Bally Slippers", "price": "$23.54", "seller": "Various", "rating": 4.7},
            {"id": "sh201", "name": "Armani Shoes", "price": "$44.46", "seller": "Various", "rating": 4.7},
            {"id": "sh202", "name": "Celine Shoes", "price": "$52.31", "seller": "Various", "rating": 4.7},
            {"id": "sh203", "name": "Berluti Shoes", "price": "$44.46", "seller": "Various", "rating": 4.7},
            {"id": "sh204", "name": "Moncler Shoes", "price": "$49.69", "seller": "Various", "rating": 4.7},
            {"id": "sh205", "name": "Tom Ford Shoe", "price": "$70.62", "seller": "Various", "rating": 4.7},
            {"id": "sh206", "name": "The Row", "price": "$46.15", "seller": "Various", "rating": 4.7},
        ]
    },
    "hoodies": {
        "name": "Hoodies",
        "icon": "🧥",
        "description": "Hoodies and sweatshirts",
        "items": [
            {"id": "h1", "name": "Essentials Hoodie", "price": "$29.00", "seller": "GMAN", "rating": 4.8},
            {"id": "h2", "name": "Nike Tech Fleece", "price": "$45.00", "seller": "Husky", "rating": 4.9},
            {"id": "h3", "name": "Spider Hoodie", "price": "$35.00", "seller": "Angel King", "rating": 4.7},
            {"id": "h4", "name": "Chrome Hearts Hoodie", "price": "$42.00", "seller": "Rick Studio", "rating": 4.6},
            {"id": "h5", "name": "Represent Hoodie", "price": "$38.00", "seller": "Husky", "rating": 4.8},
            {"id": "h6", "name": "Stussy Hoodie", "price": "$28.00", "seller": "Union Kingdom", "rating": 4.7},
        ]
    },
    "shirts": {
        "name": "Shirts",
        "icon": "👕",
        "description": "T-shirts and polos",
        "items": [
            {"id": "s1", "name": "Essentials Tee", "price": "$15.00", "seller": "GMAN", "rating": 4.7},
            {"id": "s2", "name": "Gallery Dept Tee", "price": "$22.00", "seller": "Angel King", "rating": 4.6},
            {"id": "s3", "name": "Chrome Hearts Tee", "price": "$18.00", "seller": "Rick Studio", "rating": 4.8},
            {"id": "s4", "name": "Palm Angels Tee", "price": "$16.00", "seller": "Black Cat", "rating": 4.5},
            {"id": "s5", "name": "Balenciaga Tee", "price": "$25.00", "seller": "LY Factory", "rating": 4.8},
            {"id": "s6", "name": "Corteiz Tee", "price": "$16.00", "seller": "Goat", "rating": 4.7},
        ]
    },
    "pants": {
        "name": "Pants",
        "icon": "👖",
        "description": "Jeans, joggers, and trousers",
        "items": [
            {"id": "p1", "name": "Essentials Sweatpants", "price": "$25.00", "seller": "GMAN", "rating": 4.8},
            {"id": "p2", "name": "Nike Tech Pants", "price": "$38.00", "seller": "Husky", "rating": 4.9},
            {"id": "p3", "name": "Gallery Dept Jeans", "price": "$45.00", "seller": "Angel King", "rating": 4.6},
            {"id": "p4", "name": "Amiri Jeans", "price": "$55.00", "seller": "Rick Studio", "rating": 4.5},
            {"id": "p5", "name": "Represent Joggers", "price": "$35.00", "seller": "Husky", "rating": 4.7},
            {"id": "p6", "name": "Corteiz Cargos", "price": "$32.00", "seller": "Goat", "rating": 4.8},
        ]
    },
    "accessories": {
        "name": "Accessories",
        "icon": "⌚",
        "description": "Bags, belts, watches, and jewelry",
        "items": [
            {"id": "a1", "name": "Goyard Card Holder", "price": "$18.00", "seller": "Aadi", "rating": 4.7},
            {"id": "a2", "name": "LV Belt", "price": "$25.00", "seller": "Brother Sam", "rating": 4.8},
            {"id": "a3", "name": "Chrome Hearts Ring", "price": "$12.00", "seller": "Survival Source", "rating": 4.6},
            {"id": "a4", "name": "Rolex Submariner", "price": "$85.00", "seller": "Various", "rating": 4.7},
            {"id": "a5", "name": "Cartier Bracelet", "price": "$45.00", "seller": "Miss Chen", "rating": 4.9},
            {"id": "a6", "name": "TNF Backpack", "price": "$35.00", "seller": "Husky", "rating": 4.5},
        ]
    },
    "jackets": {
        "name": "Jackets",
        "icon": "🧥",
        "description": "Coats, down jackets, and outerwear",
        "items": [
            {"id": "j1", "name": "TNF Nuptse", "price": "$65.00", "seller": "Husky", "rating": 4.9},
            {"id": "j2", "name": "Moncler Down Jacket", "price": "$95.00", "seller": "TopMoncler", "rating": 4.8},
            {"id": "j3", "name": "Canada Goose", "price": "$120.00", "seller": "KOG", "rating": 4.7},
            {"id": "j4", "name": "Arcteryx Jacket", "price": "$75.00", "seller": "Repcourier", "rating": 4.8},
            {"id": "j5", "name": "Trapstar Jacket", "price": "$45.00", "seller": "Goat", "rating": 4.6},
            {"id": "j6", "name": "Carhartt Jacket", "price": "$55.00", "seller": "TopStoney", "rating": 4.8},
        ]
    },
}

# ============== TRACKING MODULE ==============

# Data-driven delivery-estimate model, built from delivered-haul history
# (_build_delivery_model.py -> delivery_model.json). Empty {} -> the estimator
# falls back to the hardcoded SHIPPING_ESTIMATES.
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "delivery_model.json"), encoding="utf-8") as _dmf:
        DELIVERY_MODEL = json.load(_dmf)
        print(f"[ETA] delivery model: {len(DELIVERY_MODEL.get('routes', {}))} routes, "
              f"{len(DELIVERY_MODEL.get('routes_by_line', {}))} lines, {len(DELIVERY_MODEL.get('local_leg', {}))} local")
except Exception as _dme:
    DELIVERY_MODEL = {}
    print(f"[ETA] no delivery model ({_dme}); using hardcoded estimates")


class TrackingAggregator:
    """Aggregates tracking information from multiple sources."""
    
    # Estimated delivery times in days (min, max) from China
    SHIPPING_ESTIMATES = {
        # Express lines
        "kr-ems": {"name": "KR-EMS", "days": (7, 15), "description": "Fast, reliable Korean routing"},
        "ems": {"name": "EMS", "days": (7, 20), "description": "Standard express mail"},
        "dhl": {"name": "DHL Express", "days": (3, 7), "description": "Premium express shipping"},
        "fedex": {"name": "FedEx", "days": (3, 7), "description": "Premium express shipping"},
        "ups": {"name": "UPS", "days": (3, 7), "description": "Premium express shipping"},
        "sf-express": {"name": "SF Express", "days": (5, 12), "description": "Fast Chinese carrier"},
        
        # Standard lines
        "gd-ems": {"name": "GD-EMS", "days": (10, 20), "description": "Guangdong EMS routing"},
        "hz-ems": {"name": "HZ-EMS", "days": (10, 20), "description": "Hangzhou EMS routing"},
        "eub": {"name": "e-EMS/EUB", "days": (15, 30), "description": "Economy express"},
        "china-post": {"name": "China Post", "days": (20, 45), "description": "Standard airmail"},
        "hk-post": {"name": "HK Post", "days": (15, 30), "description": "Hong Kong routing"},
        "singapore-post": {"name": "Singapore Post", "days": (12, 25), "description": "Singapore routing"},
        
        # Economy lines
        "sal": {"name": "SAL", "days": (20, 40), "description": "Surface Air Lifted - economy"},
        "yanwen": {"name": "Yanwen", "days": (15, 35), "description": "Economy shipping"},
        "uniteddeliveryservice": {"name": "United Delivery Service", "days": (10, 30), "description": "UDS logistics"},
        "topyou": {"name": "TopYou / JASPOST", "days": (15, 35), "description": "Economy China shipping"},
        "4px": {"name": "4PX", "days": (12, 28), "description": "Economy express"},
        "cainiao": {"name": "Cainiao", "days": (15, 35), "description": "Alibaba logistics"},
        
        # Budget lines
        "china-post-sea": {"name": "China Post Sea", "days": (45, 90), "description": "Sea freight - very slow"},
        "ship": {"name": "Sea Shipping", "days": (30, 60), "description": "Ocean freight"},
        
        # Regional carriers
        "yto": {"name": "YTO Express", "days": (10, 25), "description": "Chinese domestic/international"},
        "zto": {"name": "ZTO Express", "days": (10, 25), "description": "Chinese domestic/international"},
        "sto": {"name": "STO Express", "days": (10, 25), "description": "Chinese domestic/international"},
        "yunda": {"name": "Yunda Express", "days": (10, 25), "description": "Chinese domestic/international"},
        
        # US specific
        "usps": {"name": "USPS", "days": (1, 5), "description": "US domestic delivery"},
        
        # UK specific
        "royal-mail": {"name": "Royal Mail", "days": (7, 21), "description": "UK postal service"},
        
        # Default
        "unknown": {"name": "Standard Shipping", "days": (15, 35), "description": "Estimated based on typical times"},
    }

    # Destination/local carriers — a tracking under one of these has already been
    # handed off in-country, so its FIRST scan is the handoff (not the China origin).
    # courier_code -> ISO2 destination country. Used to pick the last-mile leg
    # instead of the full-route estimate (fixes the China->local carrier swap).
    LOCAL_CARRIERS = {
        "usps": "US", "royal-mail": "GB", "evri": "GB", "hermes": "GB",
        "canada-post": "CA", "australia-post": "AU", "dhl-germany": "DE",
        "deutsche-post": "DE", "colissimo": "FR", "la-poste": "FR",
        "poste-italiane": "IT", "correos-spain": "ES", "postnl": "NL",
        "swiss-post": "CH", "posten-norge": "NO", "postnord-sweden": "SE",
        "postnord-denmark": "DK", "an-post": "IE", "new-zealand-post": "NZ",
        "singapore-post": "SG", "japan-post": "JP", "korea-post": "KR",
    }

    # Status-based adjustments (how much of journey is complete)
    STATUS_PROGRESS = {
        "shipment information received": 0.05,
        "information received": 0.05,
        "label created": 0.05,
        "picked up": 0.10,
        "collected": 0.10,
        "accepted": 0.15,
        "processing": 0.25,
        "departed from origin": 0.35,
        "in transit": 0.50,
        "arrived at transit": 0.55,
        "departed transit": 0.60,
        "arrived at destination country": 0.75,
        "inbound into customs": 0.78,
        "customs clearance": 0.80,
        "customs cleared": 0.82,
        "released from customs": 0.85,
        "arrived at local facility": 0.88,
        "item processed": 0.85,
        "out for delivery": 0.95,
        "delivered": 1.0,
    }
    
    # Location-based progress boosts (for when package is in destination country)
    LOCATION_PROGRESS = {
        # Canadian cities = package is in Canada, should be 75%+ 
        "toronto": 0.80,
        "vancouver": 0.82,
        "richmond": 0.85,
        "burnaby": 0.85,
        "mississauga": 0.82,
        "montreal": 0.80,
        "calgary": 0.80,
        "ottawa": 0.80,
        "coquitlam": 0.88,
        "surrey": 0.85,
        "canada": 0.78,
        # US cities
        "los angeles": 0.80,
        "new york": 0.80,
        "chicago": 0.80,
        "usa": 0.78,
        # Origin locations = early stage
        "china": 0.30,
        "guangzhou": 0.25,
        "shenzhen": 0.25,
        "hong kong": 0.35,
        "singapore": 0.40,
    }
    
    # Letter-prefix patterns — reliable, used for numbers containing letters
    CARRIER_PATTERNS = {
        "ems": r"^(E[A-Z]\d{9}CN)$",
        "china-post": r"^(R[A-Z]\d{9}CN|P[A-Z]\d{9}CN|C[A-Z]\d{9}CN)$",
        "yanwen": r"^(Y[A-Z]\d{9}CN|S\d{10,12})$",
        "uniteddeliveryservice": r"^(AP\d{10,14})$",
        "topyou": r"^(JAS\d{8,12}CN)$",
        "sf-express": r"^(SF\d{12,15})$",
        "yto": r"^(YT\d{13,18})$",
        "zto": r"^(ZT\d{14,18})$",
        "sto": r"^(ST\d{12,18})$",
        "cainiao": r"^(LP\d{14,20}|CAINIAO\d+)$",
        "dhl-germany": r"^([A-Z]{2}\d{9,12}DE)$",
        "deutsche-post": r"^([A-Z]{2}\d{9}DE)$",
        "ups": r"^(1Z[A-Z0-9]{16}|T\d{10})$",
        "usps": r"^([A-Z]{2}\d{9}US)$",
        "royal-mail": r"^([A-Z]{2}\d{9}GB)$",
        "kr-ems": r"^(E[A-Z]\d{9}KR)$",
        "hk-post": r"^([A-Z]{2}\d{9}HK)$",
        "australia-post": r"^([A-Z]{2}\d{9}AU)$",
        "japan-post": r"^([A-Z]{2}\d{9}JP)$",
        "singapore-post": r"^([A-Z]{2}\d{9}SG)$",
        "4px": r"^(4PX\d{10,16}|RF\d{9}CN)$",
        "eub": r"^(U[A-Z]\d{9}CN|L[A-Z]\d{9}CN)$",
        "yunexpress": r"^(YT\d{16}|YU[A-Z0-9]{12,16})$",
        "jnet": r"^(JJ\d{10,18})$",
    }

    # Map detect API carrier codes to our direct API carrier codes
    DETECT_TO_DIRECT_API = {
        "dhl": "dhl",
        "dhlglobalmail": "dhl",
        "dhl-germany": "dhl",
        "canada-post": "canada-post",
    }
    
    STATUS_EXPLANATIONS = {
        "shipment information received": "The seller has created a shipping label, but the package hasn't been handed to the carrier yet. This is normal and can take 1-3 days.",
        "information received": "The seller has created a shipping label. Waiting for carrier pickup.",
        "label created": "Shipping label created. Waiting for pickup or drop-off.",
        "accepted": "The carrier has received your package. It's now in the system.",
        "collected": "Package picked up from the seller.",
        "departed": "Package has left this location.",
        "arrived": "Package arrived at a facility.",
        "in transit": "Your package is on its way between facilities.",
        "customs clearance": "Package going through customs. Can take 1-7 days.",
        "held by customs": "Being inspected by customs. May need documentation if held over a week.",
        "customs cleared": "Cleared customs successfully!",
        "out for delivery": "On the delivery truck! Should arrive today.",
        "delivered": "Package delivered! 🎉",
        "exception": "There's an issue. Check details or contact carrier.",
        "returned": "Package being returned to sender. Contact your agent.",
    }

    # Chinese / Hebrew / Spanish event phrases → plain English
    # Helps users understand foreign-language scan data from TrackingMore
    EVENT_TRANSLATIONS = {
        # Chinese
        "已揽收": "Picked up by carrier",
        "已揽件": "Picked up by carrier",
        "离开始发地": "Departed origin",
        "出境直发": "Departed export, in transit to destination",
        "到达目的国": "Arrived in destination country",
        "海关清关中": "Clearing customs",
        "已派送": "Out for delivery",
        "已签收": "Delivered",
        "邮件离开": "Mail departed",
        "邮件到达": "Mail arrived",
        "正在发往下一站": "Heading to next stop",
        "揽投配发": "Sorted for delivery",
        "处理中心": "Processing center",
        "派送中": "Out for delivery",
        "妥投": "Delivered",
        "退回": "Returned to sender",
        "异常": "Exception",
        # Chinese line-haul forwarder (Take Send etc.)
        "货物到达港口": "Arrived at destination port",
        "货物离开起运港": "Departed port of origin",
        "快件到达作业中心": "Arrived at operations center",
        "快件操作完成": "Processing complete",
        "快件电子信息已经收到": "Electronic info received",
        "到达作业中心": "Arrived at operations center",
        "离开作业中心": "Left operations center",
        "干线运输中": "In line-haul transit",
        # Hebrew (Israel Post)
        "הפריט נשלח": "Item shipped",
        "הפריט נכנס לתהליך יצוא מכס": "Item entered export customs",
        "הפריט נמצא במרכז מיון": "Item at sorting center",
        "הפריט התקבל למשלוח": "Item accepted for shipping",
        "הפריט חזר מבדיקת הרשויות": "Item cleared customs inspection",
        "התקבל מידע על חבילה": "Package information received",
        # Spanish (Correos / Mexico / Spain etc.)
        "entregado": "Delivered",
        "en tránsito": "In transit",
        "salió del centro": "Left facility",
        "en reparto": "Out for delivery",
        "enviado": "Shipped",
    }

    def translate_event(self, text: str) -> str:
        """Append plain-English translation in parentheses if event has foreign text."""
        if not text:
            return text
        for foreign, english in self.EVENT_TRANSLATIONS.items():
            if foreign in text:
                # Append translation if not already present
                if english.lower() not in text.lower():
                    return f"{text} ({english})"
                return text
        return text

    # Carrier-specific tracking deep links — used when our API returns no data
    # so the user can still check the carrier's own site directly.
    CARRIER_DEEP_LINKS = {
        "taqbin-jp": "https://track.kuronekoyamato.co.jp/multi/?number01={tn}",
        "yamato": "https://track.kuronekoyamato.co.jp/multi/?number01={tn}",
        "japan-post": "https://trackings.post.japanpost.jp/services/srv/search/?reqCodeNo1={tn}",
        "dhl-germany": "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode={tn}",
        "dhl-parcel-de": "https://www.dhl.de/de/privatkunden/dhl-sendungsverfolgung.html?piececode={tn}",
        "dhl": "https://www.dhl.com/global-en/home/tracking/tracking-parcel.html?submit=1&tracking-id={tn}",
        "china-ems": "https://www.ems.com.cn/queryList?mailNum={tn}",
        "china-post": "http://yjcx.chinapost.com.cn/qps/yjcx?si={tn}",
        "yanwen-express": "https://track.yw56.com.cn/en/querydel?nums={tn}",
        "yanwen": "https://track.yw56.com.cn/en/querydel?nums={tn}",
        "4px": "https://track.4px.com/#/result/0/{tn}",
        "cainiao": "https://global.cainiao.com/detail.htm?mailNoList={tn}",
        "usps": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tn}",
        "ups": "https://www.ups.com/track?tracknum={tn}",
        "fedex": "https://www.fedex.com/fedextrack/?trknbr={tn}",
        "royal-mail": "https://www.royalmail.com/track-your-item#/tracking-results/{tn}",
        "canada-post": "https://www.canadapost-postescanada.ca/track-reperage/en#/details/{tn}",
        "australia-post": "https://auspost.com.au/mypost/track/#/details/{tn}",
        # US last-mile carriers (common for rep shipments routed to USA)
        "axlehire": "https://axlehire.com/tracking/{tn}",
        "ontrac": "https://www.ontrac.com/tracking/?number={tn}",
        "newgistics": "https://www.newgistics.com/package-tracking/?trackNumber={tn}",
        "veho": "https://shipveho.com/track/{tn}",
        "lasership": "https://www.lasership.com/track?track={tn}",
        # Other commonly-detected couriers
        "hellmann": "https://www.hellmann.com/tracking?ref={tn}",
        "sf-express": "https://www.sf-express.com/we/ow/chn/en/waybill/waybillNew/detailNew?billNo={tn}",
        "yun-express": "https://www.yuntrack.com/parcelTracking?id={tn}",
        "yunexpress": "https://www.yuntrack.com/parcelTracking?id={tn}",
    }

    # Per-carrier hints shown alongside tracking when the carrier has a
    # known data-quality quirk users routinely complain about.
    CARRIER_HINTS = {
        "dhl-germany": "DHL Paket doesn't expose flight or transit-leg detail via API. For full route info, check dhl.de directly.",
        "dhl-parcel-de": "DHL Paket doesn't expose flight or transit-leg detail via API. For full route info, check dhl.de directly.",
        "usps": "USPS scans can lag 12-24 hours behind reality. Your package may be further along than shown.",
        "taqbin-jp": "Yamato (TaQBin) Japan doesn't share live data with our partners. Use the direct link below for real-time scans.",
        # Small US last-mile carriers often update their own site hours/days before our aggregator
        "axlehire": "Axlehire updates their own tracking site faster than our partner. If you see a different status here vs. axlehire.com, trust axlehire.com.",
        "ontrac": "OnTrac scans usually appear on their site hours before they reach our aggregator. Check the direct link for the latest.",
        "newgistics": "Newgistics tracking updates can lag in our system. Use the direct link for the freshest status.",
        "veho": "Veho is a last-mile carrier that updates its own site faster than aggregators. Use the direct link for real-time status.",
        "lasership": "LaserShip / OnTrac updates their own tracking faster than our partner.",
    }

    def get_deep_link(self, courier_code: str, tracking_number: str) -> Optional[str]:
        """Return carrier's own tracking URL for the given number, if known."""
        if not courier_code:
            return None
        tpl = self.CARRIER_DEEP_LINKS.get(courier_code.lower())
        if tpl:
            return tpl.format(tn=tracking_number)
        return None

    def get_carrier_hint(self, courier_code: str) -> Optional[str]:
        """Return a one-line hint for known data-quality quirks of a carrier."""
        if not courier_code:
            return None
        return self.CARRIER_HINTS.get(courier_code.lower())

    @staticmethod
    def parse_event_dt(s):
        """Parse a carrier checkpoint date string to a naive datetime, or None.
        Handles the mixed formats TrackingMore returns (space or T separator,
        optional timezone suffix, date-only)."""
        from datetime import datetime
        if not s or not isinstance(s, str):
            return None
        raw = s.strip().replace("T", " ").replace("/", "-")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(raw[:len("2026-01-01 00:00:00") if "%S" in fmt else (16 if "%M" in fmt else 10)], fmt)
            except (ValueError, TypeError):
                continue
        return None

    def is_stalled_pre_handoff(self, history: list, status_lower: str) -> bool:
        """Detect 'sender created label but carrier never received package'.
        Triggered when there's only 1-2 InfoReceived-style events AND >5 days old.
        """
        if not history or len(history) > 2:
            return False
        first_status = (history[0].get("status") or "").lower() if history else ""
        is_pre_handoff = any(kw in first_status for kw in [
            "instruction data", "info received", "info_received", "label created",
            "shipment information", "electronic information", "pre-shipment"
        ]) or status_lower in ("info received", "pre-shipment", "inforeceived")
        if not is_pre_handoff:
            return False
        # Check date age
        try:
            from datetime import datetime, timezone
            for h in history:
                d = h.get("date", "")
                # Try common formats
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(d[:19], fmt)
                        age_days = (datetime.now() - dt).days
                        if age_days >= 5:
                            return True
                        return False
                    except (ValueError, TypeError):
                        continue
        except Exception:
            pass
        return False

    def pre_handoff_info(self, carrier_name, history, status_lower):
        """For a parcel that only has a 'label created / info received' scan on the
        DESTINATION carrier (no real movement yet), return (explanation, warning)
        that explains the China-leg situation. Returns (None, None) otherwise.
        Rep parcels from China carry the destination carrier's number (Canada Post,
        USPS, etc.) but the detailed early journey lives on the forwarder's line-haul
        waybill, which the destination carrier / 17track don't show — so the page
        looks empty until it physically lands in-country and gets scanned."""
        first = (history[0].get("status") or "").lower() if history else (status_lower or "")
        label_only = len(history) <= 2 and any(kw in first for kw in (
            "info received", "info_received", "electronic information", "label created",
            "instruction data", "shipment information", "pre-shipment", "pre shipment"))
        status_prehandoff = (status_lower or "") in (
            "info received", "inforeceived", "pre-shipment", "pre shipment")
        if not (label_only or status_prehandoff or self.is_stalled_pre_handoff(history, status_lower or "")):
            return None, None
        cn = carrier_name or "the carrier"
        explanation = (
            f"{cn} has created the shipping label but hasn't physically received your parcel yet, so there's "
            f"no movement to show here. For rep parcels from China this is normal: the early journey (leaving "
            f"the warehouse, China hubs, the international flight) is tracked on your agent's forwarder / line-haul "
            f"waybill — which {cn} and 17track don't display. This page starts updating once the parcel lands "
            f"in-country and {cn} scans it. No action needed unless it's been ~2+ weeks.")
        warning = {
            "kind": "pre_handoff",
            "title": f"Still in transit from China — {cn} hasn't received it yet",
            "body": (f"The label is made and the parcel is on its way, but {cn} only shows movement once it "
                     f"arrives and gets scanned. For the China-leg detail, check your agent's order page or the "
                     f"forwarder's waybill. Contact your agent only if it's been 2+ weeks with no change."),
        }
        return explanation, warning

    def detect_carrier(self, tracking_number: str) -> Optional[str]:
        """Hybrid carrier detection: local regex for letter-prefix, API detect for pure digits."""
        tracking_number = tracking_number.upper().strip()

        # Step 1: If has letters, use local regex (fast and reliable for Chinese carriers)
        if re.search(r'[A-Za-z]', tracking_number):
            for carrier, pattern in self.CARRIER_PATTERNS.items():
                if re.match(pattern, tracking_number, re.IGNORECASE):
                    return carrier
            return None

        # Step 2: Pure digits — use TrackingMore detect API (free, no credits)
        detected = self._detect_via_api(tracking_number)
        if detected:
            # Map to our internal carrier code if we have a direct API for it
            direct = self.DETECT_TO_DIRECT_API.get(detected)
            if direct:
                print(f"  [DETECT API] {tracking_number} -> {detected} -> direct API: {direct}")
                return direct
            print(f"  [DETECT API] {tracking_number} -> {detected} (TrackingMore)")
            return detected

        # Step 3: Fallback for common digit-only formats if API is down
        length = len(tracking_number)
        if length == 10:
            return "dhl"
        if length == 16:
            return "canada-post"

        return None

    def _detect_via_api(self, tracking_number: str) -> Optional[str]:
        """Call TrackingMore detect API (free) to identify carrier for pure-digit numbers."""
        try:
            api_key = os.getenv("TRACKINGMORE_API_KEY", "")
            if not api_key:
                return None
            resp = http_requests.post(
                "https://api.trackingmore.com/v4/couriers/detect",
                headers={"Content-Type": "application/json", "Tracking-Api-Key": api_key},
                json={"tracking_number": tracking_number},
                timeout=8
            )
            data = resp.json()
            if data.get("meta", {}).get("code") == 200:
                results = data.get("data", [])
                if results:
                    return results[0]["courier_code"]
        except Exception as e:
            print(f"  [DETECT API] Error: {e}")
        return None
    
    def get_explanation(self, status: str) -> str:
        status_lower = status.lower()
        for key, explanation in self.STATUS_EXPLANATIONS.items():
            if key in status_lower:
                return explanation
        
        if "transit" in status_lower:
            return "Your package is moving through the shipping network."
        elif "customs" in status_lower:
            return "Your package is being processed by customs."
        elif "delivered" in status_lower:
            return "Your package has been delivered!"
        elif "departed" in status_lower:
            return "Package left this location, heading to the next stop."
        elif "arrived" in status_lower:
            return "Package arrived at a facility for processing."
        
        return "Package is being processed. Check back for updates."
    
    def get_progress_percentage(self, status: str, location: str = "") -> float:
        """Estimate how far along the package is based on status and location.

        Location-aware: keywords like 'customs' mean different things in China vs
        destination country. Origin-side customs (China) = early. Destination
        customs = late. Detect origin location and cap progress accordingly.
        """
        status_lower = status.lower()
        location_lower = location.lower() if location else ""

        # Detect if we're at the ORIGIN side (China/HK/SG = early stage)
        origin_keywords = [
            "china", "guangzhou", "shenzhen", "shanghai", "beijing", "hong kong",
            "hk", "singapore", "wuhan", "huizhou", "office of exchange",
            "guangdong", "zhejiang", "jiangsu", "fujian", "henan", "xiamen",
            "guangzhou ems", "cn", "cnwuhd", "cnsh", "cnhgh", "cnpek",
        ]
        is_origin = any(kw in location_lower for kw in origin_keywords)
        # Also detect from status text - origin events often say "originating country"
        if "originating country" in status_lower or "office of exchange" in status_lower:
            is_origin = True

        # First check location - if in destination country, use location-based progress
        location_progress = 0.0
        for loc_key, loc_progress in self.LOCATION_PROGRESS.items():
            if loc_key in location_lower:
                location_progress = loc_progress
                break

        # Then check status
        status_progress = 0.30  # Default
        for key, progress in self.STATUS_PROGRESS.items():
            if key in status_lower:
                status_progress = progress
                break

        # Fuzzy matching for common keywords - location-aware!
        if "delivered" in status_lower:
            status_progress = 1.0
        elif "out for delivery" in status_lower:
            status_progress = 0.95
        elif "customs" in status_lower:
            # Origin customs (export customs in China) = ~30%, not 80%!
            # Destination customs (import customs at recipient country) = ~80%
            if is_origin or "export" in status_lower:
                status_progress = 0.30
            elif "cleared" in status_lower:
                status_progress = 0.85
            elif "held" in status_lower:
                status_progress = 0.75
            else:
                status_progress = 0.78
        elif "destination" in status_lower and not is_origin:
            status_progress = 0.75
        elif "processed" in status_lower:
            # "Processed in originating country" = early. Generic "processed" later.
            if is_origin or "originating" in status_lower:
                status_progress = 0.25
            else:
                status_progress = max(status_progress, 0.85)
        elif "transit" in status_lower:
            # "En route" from China = ~40%. "In transit" in destination country = ~70%.
            status_progress = max(status_progress, 0.40 if is_origin else 0.55)
        elif "departure" in status_lower or "departed" in status_lower:
            # Departure from origin Office of Exchange = 25-30%. Departure from
            # destination facility = much later.
            status_progress = max(status_progress, 0.28 if is_origin else 0.50)
        elif "office of exchange" in status_lower:
            status_progress = 0.30
        elif "arrived" in status_lower or "arrival" in status_lower:
            # Arrival in China = early. Arrival at destination = late.
            status_progress = max(status_progress, 0.20 if is_origin else 0.70)
        elif "origin" in status_lower:
            status_progress = 0.20
        elif "accepted" in status_lower or "received" in status_lower or "package received" in status_lower:
            status_progress = 0.10
        elif "label created" in status_lower or "shipment information" in status_lower or "instruction data" in status_lower:
            status_progress = 0.05

        # Use the higher of status or location progress, but hard-cap the FINAL value
        # when we're clearly still at origin, so a destination-city substring matched on
        # a China-side scan can't pin a still-in-China parcel near "done".
        result = max(status_progress, location_progress)
        if is_origin:
            result = min(result, 0.45)
        return result
    
    ORIGIN_KEYWORDS = (
        "china", "guangzhou", "shenzhen", "shanghai", "beijing", "hong kong",
        "singapore", "wuhan", "huizhou", "office of exchange", "originating country",
        "guangdong", "zhejiang", "jiangsu", "fujian", "henan", "xiamen",
        "dongguan", "yiwu", "shippers warehouse", "shenz", "departed from origin",
    )

    def _looks_origin(self, text):
        """True if a scan location/status is China/origin-side. Matches the bare
        country code 'cn' only as a token, to avoid substrings like 'cncentre'."""
        t = (text or "").lower()
        if any(k in t for k in self.ORIGIN_KEYWORDS):
            return True
        # bare 'cn' token, or a China UPU/office-of-exchange code like CNGGZ/CNSZX/CNSHA
        return bool(re.search(r'(?:^|[^a-z])cn[a-z]{0,4}(?:[^a-z]|$)', t))

    def _at_local_leg(self, status, history):
        """Is the parcel actually in the destination carrier's network (on the last
        mile)? A local-carrier number is often assigned while the parcel is still in
        China, so we require POSITIVE destination-side evidence; otherwise we treat it
        as the full journey (safer to over- than under-estimate)."""
        s = (status or "").lower()
        STRONG = ("delivered", "out for delivery", "available for pickup", "ready for pickup",
                  "attempted delivery", "delivery office", "with local", "with courier",
                  "final mile", "being delivered", "on vehicle for delivery")
        if any(k in s for k in STRONG):
            return True
        hist = history or []
        if not hist:
            return False
        # history is newest-first; if the freshest scan (or the status text) is still
        # origin-side, it is NOT on the last mile — fall through to the full route.
        newest = (hist[0].get("location", "") or "") + " " + (hist[0].get("status", "") or "")
        if self._looks_origin(newest) or self._looks_origin(s):
            return False
        # freshest scan is clearly past origin and shows destination-side movement
        txt = (newest + " " + s).lower()
        return any(k in txt for k in ("out for delivery", "delivered", "customs", "processed",
                                      "in transit", "arrived", "sorting", "departed", "en route",
                                      "picked up", "received by"))

    COUNTRY_ISO = {
        "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "USA": "US", "AMERICA": "US",
        "UNITED KINGDOM": "GB", "UK": "GB", "GREAT BRITAIN": "GB", "BRITAIN": "GB", "ENGLAND": "GB",
        "SCOTLAND": "GB", "WALES": "GB", "CANADA": "CA", "AUSTRALIA": "AU", "NEW ZEALAND": "NZ",
        "GERMANY": "DE", "DEUTSCHLAND": "DE", "FRANCE": "FR", "ITALY": "IT", "ITALIA": "IT",
        "SPAIN": "ES", "ESPANA": "ES", "NETHERLANDS": "NL", "HOLLAND": "NL", "SWITZERLAND": "CH",
        "AUSTRIA": "AT", "BELGIUM": "BE", "PORTUGAL": "PT", "IRELAND": "IE", "NORWAY": "NO",
        "SWEDEN": "SE", "DENMARK": "DK", "FINLAND": "FI", "ICELAND": "IS", "POLAND": "PL",
        "CZECHIA": "CZ", "CZECH REPUBLIC": "CZ", "ROMANIA": "RO", "HUNGARY": "HU", "GREECE": "GR",
        "CROATIA": "HR", "SERBIA": "RS", "SLOVAKIA": "SK", "SLOVENIA": "SI", "BULGARIA": "BG",
        "UKRAINE": "UA", "MOLDOVA": "MD", "RUSSIA": "RU", "RUSSIAN FEDERATION": "RU",
        "BRAZIL": "BR", "BRASIL": "BR", "MEXICO": "MX", "CHILE": "CL", "ARGENTINA": "AR",
        "COLOMBIA": "CO", "PERU": "PE", "URUGUAY": "UY", "ECUADOR": "EC", "COSTA RICA": "CR",
        "DOMINICAN REPUBLIC": "DO", "PANAMA": "PA", "SAUDI ARABIA": "SA", "UNITED ARAB EMIRATES": "AE",
        "UAE": "AE", "QATAR": "QA", "ISRAEL": "IL", "KUWAIT": "KW", "BAHRAIN": "BH", "OMAN": "OM",
        "JORDAN": "JO", "LEBANON": "LB", "EGYPT": "EG", "TURKEY": "TR", "TURKIYE": "TR",
        "JAPAN": "JP", "SOUTH KOREA": "KR", "KOREA": "KR", "REPUBLIC OF KOREA": "KR",
        "SINGAPORE": "SG", "MALAYSIA": "MY", "THAILAND": "TH", "INDONESIA": "ID", "PHILIPPINES": "PH",
        "VIETNAM": "VN", "VIET NAM": "VN", "INDIA": "IN", "TAIWAN": "TW", "HONG KONG": "HK",
        "CAMBODIA": "KH", "MOROCCO": "MA", "SOUTH AFRICA": "ZA", "NIGERIA": "NG",
    }

    def _resolve_country(self, raw):
        """Destination string -> ISO-2. Already-2-char codes pass through; full names
        resolve via COUNTRY_ISO; anything else returns '' so we fall back to the generic
        window instead of mis-slicing a name into a wrong country (Chile->CH, etc.)."""
        s = (raw or "").strip().upper()
        if not s:
            return ""
        if len(s) == 2 and s.isalpha():
            return s
        return self.COUNTRY_ISO.get(s, "")

    def _data_window(self, courier_code, dest_country, status, history):
        """Data-driven (min, max, basis, n) day window from the delivery model, or
        None to fall back to the hardcoded carrier estimate. Handles the China->local
        carrier swap: a LOCAL-carrier tracking's first scan is the handoff, so we use
        just the last-mile leg; a CHINA-carrier tracking gets the full route (and a
        line-specific window when we have enough samples for that carrier)."""
        M = DELIVERY_MODEL
        if not M:
            return None
        cc = (courier_code or "").lower().strip()
        # Local/destination carrier -> last-mile leg ONLY once the parcel is actually
        # in that carrier's network. TrackingMore often labels a parcel with its final
        # carrier (e.g. "Canada Post") while it's still sitting in China; using the
        # last-mile window there would promise a ~2-10 day delivery for a parcel that
        # hasn't even shipped. If it's not on the last mile yet, fall through and treat
        # it as the full China->destination journey.
        if cc in self.LOCAL_CARRIERS:
            ldc = self.LOCAL_CARRIERS[cc]
            ll = (M.get("local_leg") or {}).get(ldc or "")
            # Use the last-mile-only window only when (a) the parcel is genuinely on the
            # last mile AND (b) we have a plausible last-mile leg (>=2 days; the GB/IT
            # percentiles collapse to ~1 day and would promise next-day delivery).
            # DE's "local_leg" is contaminated: DHL creates the label while the parcel
            # is still in China, so that leg spans the whole journey, not the last mile.
            if (self._at_local_leg(status, history) and ll and ll.get("n", 0) >= 8
                    and (ll.get("p50") or 0) >= 2 and ldc != "DE"):
                lo = max(1, ll.get("p10") or 1)
                hi = max(lo + 1, ll.get("p85") or ll.get("p50") or lo + 2)
                return (lo, hi, f"lastmile:{ldc}", ll["n"])
            # still in China, or no usable last-mile leg -> full journey to this country
            dest_country = dest_country or ldc
            cc = ""
        # China/origin carrier -> full China->destination route (prefer line-specific)
        dc = self._resolve_country(dest_country)
        if not dc:
            return None
        # Highest priority: real first-party door-to-door data (KakoBuy own parcels).
        # Beats the TrackingMore line/route windows, which truncate at the China->local
        # carrier swap and so undercount the last-mile leg.
        gt = (M.get("ground_truth_routes") or {}).get(dc)
        if gt and gt.get("lo"):
            return (max(2, gt["lo"]), max(gt["lo"] + 1, gt.get("hi") or gt["lo"] + 5),
                    "firstparty:" + dc, gt.get("n", 0))
        line = (M.get("routes_by_line") or {}).get(f"{dc}|{cc}")
        route = (M.get("routes") or {}).get(dc)
        # A de-biased route is full door-to-door; the line windows are China-leg-biased
        # (truncated at the carrier swap), so prefer the de-biased route over the line.
        if route and route.get("door_to_door"):
            r = route
        else:
            r = line if (line and line.get("n", 0) >= 12) else route
        if r and r.get("n", 0) >= 8:
            # eta_lo/eta_hi are the de-biased windows (raw percentiles skew fast because
            # they only include hauls a China carrier tracked end-to-end); fall back to
            # raw percentiles if a recalibrated window isn't present.
            lo = max(2, r.get("eta_lo") or r.get("p10") or r.get("p50") or 5)
            hi = max(lo + 1, r.get("eta_hi") or r.get("p85") or r.get("p90") or lo + 5)
            return (lo, hi, "route:" + dc + (f"|{cc}" if r is line else ""), r["n"])
        # No internal route data -> external research benchmark (covers ~60 countries)
        ext = (M.get("external_routes") or {}).get(dc)
        if ext and ext.get("min"):
            return (max(2, ext["min"]), max(ext["min"] + 1, ext.get("max") or ext["min"] + 8), "external:" + dc, 0)
        # Still unmapped -> region-aware fallback so we never show the flat carrier
        # guess (e.g. a country in LATAM gets a realistic slow-customs window, not 5-12d).
        rf = M.get("region_fallback") or {}
        band = rf.get((M.get("country_region") or {}).get(dc) or "") or rf.get("DEFAULT")
        if band and band.get("min"):
            reg = (M.get("country_region") or {}).get(dc) or "intl"
            return (max(2, band["min"]), max(band["min"] + 1, band.get("max") or band["min"] + 8), "region:" + reg, 0)
        return None

    def _route_note(self, dest_country, courier_code=""):
        """Short destination customs/seasonal note (from the model's route_notes),
        or None. Resolves the country from dest_country, else the local carrier."""
        notes = DELIVERY_MODEL.get("route_notes") or {}
        if not notes:
            return None
        dc = self._resolve_country(dest_country)
        if dc not in notes:
            dc = self.LOCAL_CARRIERS.get((courier_code or "").lower(), "")
        return notes.get(dc)

    def estimate_delivery(self, carrier: str, status: str, ship_date: str = None, location: str = "", history: list = None, dest_country: str = "", courier_code: str = "") -> dict:
        """
        Estimate delivery date based on carrier, current status, and ship date.
        Returns estimated date range and confidence level.
        Progress is monotonic — takes the highest progress across all events so it
        never goes backwards (fixes the "50% then 85% then 50%" bug).
        Uses the data-driven per-route model (DELIVERY_MODEL) when available, falling
        back to the hardcoded SHIPPING_ESTIMATES otherwise.
        """
        from datetime import datetime, timedelta

        # Get carrier estimates
        carrier_lower = (carrier or "unknown").lower().replace(" ", "-").replace("_", "-")
        carrier_info = self.SHIPPING_ESTIMATES.get(carrier_lower, self.SHIPPING_ESTIMATES["unknown"])

        min_days, max_days = carrier_info["days"]

        # Prefer the data-driven, carrier-swap-aware window when we have history for it.
        _eta_basis, _eta_n = None, 0
        _dw = self._data_window(courier_code or carrier_lower, dest_country, status, history)
        if _dw:
            min_days, max_days, _eta_basis, _eta_n = _dw

        # Calculate progress — MAX across all events, never less than current status
        progress = self.get_progress_percentage(status, location)
        if history:
            for event in history:
                ev_progress = self.get_progress_percentage(
                    event.get("status", "") or "",
                    event.get("location", "") or ""
                )
                if ev_progress > progress:
                    progress = ev_progress
        # If the latest scan is still origin-side, the parcel is in China — cap the
        # monotonic progress so an earlier high-scoring event (e.g. China export
        # "customs clearance completed", scored like destination customs) can't inflate
        # it past mid-journey and shrink the remaining window. (location/status are the
        # current state, so this doesn't depend on history ordering.)
        if self._looks_origin((location or "") + " " + (status or "")):
            progress = min(progress, 0.45)
        
        # If delivered, no estimation needed
        if progress >= 1.0:
            return {
                "status": "delivered",
                "message": "Your package has been delivered! 🎉",
                "progress_percent": 100,
                "confidence": "high"
            }
        
        # Get today's date
        today = datetime.now()

        # Find a STABLE origin date to anchor the ETA to. Without this we anchor to
        # now() on every call, so the predicted date slides +1/day while the package
        # sits ("says tomorrow every day"). Use the earliest real checkpoint
        # (history is sorted newest-first, so history[-1] is the first scan), then
        # fall back to the ship_date param.
        origin_dt = None
        if history:
            for ev in reversed(history):
                origin_dt = self.parse_event_dt(ev.get("date", "") or "")
                if origin_dt:
                    break
        if origin_dt is None and ship_date:
            origin_dt = self.parse_event_dt(ship_date)

        # Pre-shipment: the package is only at the label-created / info-received /
        # "tracking registered" stage (progress at the pre-shipment floor) — the
        # carrier hasn't physically picked it up, so the transit clock hasn't started
        # even if that registration event carries a date. Anchoring a calendar ETA to
        # the registration date would falsely promise delivery in a few days while the
        # parcel is still sitting in a China warehouse. Show a soft, honest window
        # ("~X-Y days once it ships") instead of a date.
        # NOTE: an unrecognized status defaults to 30% progress, so we can't rely on
        # `progress <= 0.05` alone — detect the pre-shipment statuses by name, but
        # never when the status already shows real movement.
        _sl = (status or "").lower()
        # A parcel whose LATEST scan is still in China (even one "moving" within China,
        # e.g. "In Transit, Shenzhen" / "Departed from origin, CNGGZ") has the whole
        # China->destination journey ahead — treat it like pre-shipment so the window is
        # anchored to today + the full route, never to a stale origin scan (which would
        # promise "arrives in 3 days" for a parcel still sitting in Shenzhen).
        _still_in_china = (not self._at_local_leg(status, history)
                           and self._looks_origin((location or "") + " " + _sl))
        # A status string alone (no scans) doesn't prove movement, so don't let a bare
        # "In Transit" with empty history read as mid-journey — treat it as pre-shipment.
        _moving = bool(history) and any(k in _sl for k in ("transit", "departed", "left ", "arrived", "customs",
                                         "out for delivery", "delivered", "picked up", "collected",
                                         "processing", "dispatch", "en route", "flight", "port"))
        _pre_ship = (not history) or _still_in_china or (progress <= 0.05) or (not _moving and any(k in _sl for k in (
            "pending", "info received", "inforeceived", "information received",
            "tracking registered", "label created", "awaiting", "shipment received",
            "not found", "expecting", "pre-shipment", "pre-transit", "data received")))
        if _pre_ship:
            # Still in China / not picked up yet: the whole journey is still ahead, so
            # anchor a REAL window to today + the full route estimate (don't narrow by
            # the bogus default progress — that's what produced the "arrives in 2 days
            # while sitting in a China warehouse" nonsense). It's correct for this to
            # drift later each day it sits unscanned — a longer wait before pickup does
            # mean a later delivery. Once it gets a real scan, the in-transit logic
            # below takes over with a firmer date.
            lo_date = today + timedelta(days=min_days)
            hi_date = today + timedelta(days=max_days)
            window = lo_date.strftime("%b %d") + " - " + hi_date.strftime("%b %d")
            _note = ("Still in China — the international leg hasn't started yet; early estimate that firms up once it leaves China."
                     if _still_in_china and _moving else
                     "Still in China and not picked up yet — early estimate; it'll firm up once the carrier scans it.")
            return {
                "status": "in_progress",
                "delivery_window": window,
                "remaining_days_min": min_days,
                "remaining_days_max": max_days,
                "progress_percent": min(int(progress * 100), 15),
                "confidence": "low",
                "confidence_note": _note,
                "carrier_name": carrier_info["name"],
                "carrier_description": carrier_info["description"],
                "estimate_basis": _eta_basis,
                "sample_size": _eta_n,
                "route_note": self._route_note(dest_country, courier_code),
                "message": f"Estimated arrival: {window}",
            }

        # No usable origin date but the package is clearly moving — fall back to the
        # old now()-relative behaviour (still better than nothing, and these packages
        # update often enough that the slide isn't noticeable).
        if origin_dt is None:
            origin_dt = today

        # Adjust remaining time based on progress
        remaining_progress = 1.0 - progress

        # Calculate remaining days
        remaining_min = max(1, int(min_days * remaining_progress))
        remaining_max = max(2, int(max_days * remaining_progress))

        # Anchor the absolute arrival window to the STABLE origin date, not now().
        # Far edge = origin + full carrier estimate (fixed; never slides while idle).
        # Near edge = origin + min carrier estimate, but never earlier than today
        # (a package still in transit can't arrive in the past) and never after the
        # far edge. As real checkpoints advance, progress rises and `remaining_*`
        # shrink, narrowing the window — while the target stays put.
        est_max_date = origin_dt + timedelta(days=max_days)
        est_min_date = origin_dt + timedelta(days=min_days)
        # Re-derive the near edge from remaining progress so it tightens over time,
        # then clamp into [today, est_max_date] so we never show a past or inverted date.
        progress_min_date = today + timedelta(days=remaining_min)
        # When the parcel is genuinely at/near the destination (on the last mile or
        # out for delivery), the near edge must be allowed to pull EARLIER than
        # origin+min_days so an out-for-delivery parcel converges to ~1-2 days instead
        # of staying pinned days out. Otherwise keep the floor (never earlier than the
        # route minimum) so a fresh scan can't promise an impossibly early arrival.
        _at_dest = progress >= 0.9 or self._at_local_leg(status, history)
        if _at_dest:
            est_min_date = progress_min_date
        elif progress_min_date > est_min_date:
            est_min_date = progress_min_date
        if est_min_date < today:
            est_min_date = today
        # If the fixed far edge is already in the past (package overdue), the carrier
        # estimate has lapsed — slide a short tentative tail off today instead of
        # showing a stale past date, and don't claim high confidence.
        if est_max_date <= today:
            est_max_date = today + timedelta(days=max(2, remaining_max))
        if est_min_date > est_max_date:
            est_min_date = est_max_date
        
        # Determine confidence level (location-aware to prevent "almost there" when
        # package is still in China)
        status_lower = status.lower()
        location_lower = (location or "").lower()
        origin_hints = ["china", "guangzhou", "shenzhen", "wuhan", "huizhou",
                        "office of exchange", "originating country", "hong kong"]
        is_at_origin = any(h in location_lower or h in status_lower for h in origin_hints)

        if is_at_origin and progress < 0.5:
            confidence = "low"
            confidence_note = "Just shipped from origin — long journey ahead"
        elif progress >= 0.9:
            confidence = "high"
            confidence_note = "Out for final delivery soon"
        elif progress >= 0.75 and not is_at_origin:
            confidence = "high"
            confidence_note = "Package is almost there"
        elif progress >= 0.55:
            confidence = "medium"
            confidence_note = "On track for estimated delivery"
        elif progress >= 0.3:
            confidence = "medium"
            confidence_note = "Mid-journey — times may vary"
        else:
            confidence = "low"
            confidence_note = "Early stage — estimate is rough"

        # Special status messages — but only if at destination customs
        if "customs" in status_lower and "cleared" not in status_lower and not is_at_origin and "export" not in status_lower:
            confidence_note = "In customs — may add 1-7 days"
            remaining_max += 5
            # Extend the STABLE far edge, never re-anchor to today (would re-introduce
            # the daily slide for packages parked in customs).
            est_max_date = est_max_date + timedelta(days=5)
        elif "exception" in status_lower or "held" in status_lower:
            confidence = "low"
            confidence_note = "Issue detected — delivery may be delayed"
            remaining_max += 10
            est_max_date = est_max_date + timedelta(days=10)

        # Keep the date window and the "remaining X-Y days" label on the same clock.
        # The far edge was anchored to origin+max_days and didn't shrink with progress,
        # so a mostly-done parcel could show a window stretching ~12 days out while
        # "remaining" said ~4. Cap the far edge at what progress implies, then derive
        # remaining_* from the final dates so the two can never contradict.
        progress_max_date = today + timedelta(days=remaining_max)
        if progress_max_date < est_max_date:
            est_max_date = max(progress_max_date, est_min_date + timedelta(days=1))
        remaining_min = max(0, (est_min_date - today).days)
        remaining_max = max(1, (est_max_date - today).days)

        # Format dates
        def format_date(d):
            return d.strftime("%b %d")
        
        # Create delivery window string
        if remaining_min == remaining_max or (est_max_date - est_min_date).days <= 2:
            delivery_window = f"~{format_date(est_min_date)}"
        else:
            delivery_window = f"{format_date(est_min_date)} - {format_date(est_max_date)}"
        
        # When the window is backed by real delivered-haul history, say so + bump
        # confidence (a big sample is more trustworthy than a hardcoded guess).
        if _eta_basis and _eta_n >= 20:
            confidence_note = (confidence_note or "").rstrip(".") + f" · based on {_eta_n} past hauls"
            if confidence == "low" and progress >= 0.15:
                confidence = "medium"

        return {
            "status": "in_progress",
            "delivery_window": delivery_window,
            "remaining_days_min": remaining_min,
            "remaining_days_max": remaining_max,
            "progress_percent": int(progress * 100),
            "confidence": confidence,
            "confidence_note": confidence_note,
            "carrier_name": carrier_info["name"],
            "carrier_description": carrier_info["description"],
            "estimate_basis": _eta_basis,
            "sample_size": _eta_n,
            "route_note": self._route_note(dest_country, courier_code),
            "message": f"Estimated arrival: {delivery_window}"
        }
    

    # File-based cache for tracking data (persists across server restarts)
    CACHE_FILE = "/data/tracking_cache.json" if os.path.isdir("/data") else "tracking_cache.json"
    CACHE_DURATION_ACTIVE = 1200  # 20 min for active/in-transit (reads are free; fresher updates)
    CACHE_DURATION_DELIVERED = 86400 * 365  # 1 year for delivered packages (basically forever)
    CACHE_DURATION_NOT_FOUND = 600  # 10 minutes for not-found results
    CACHE_DURATION_PENDING = 300  # 5 minutes for pending (waiting for first scan)
    
    def _load_cache(self) -> Dict:
        """Load cache from file."""
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, 'r') as f:
                    return json.load(f)
        except json.JSONDecodeError as e:
            print(f"  [CACHE] Corrupted cache file, starting fresh: {e}")
            try:
                os.remove(self.CACHE_FILE)
            except Exception:
                pass
        except Exception as e:
            print(f"  [CACHE] Error loading: {e}")
        return {}

    def _save_cache(self, cache: Dict):
        """Save cache atomically to prevent corruption from concurrent writes."""
        try:
            tmp_file = self.CACHE_FILE + ".tmp"
            with open(tmp_file, 'w') as f:
                json.dump(cache, f)
            os.replace(tmp_file, self.CACHE_FILE)
        except Exception as e:
            print(f"  [CACHE] Error saving: {e}")
    
    def _get_cached(self, tracking_number: str) -> Dict:
        """Get cached tracking data if valid. Uses smart expiry - 1hr for active, forever for delivered."""
        import time
        cache = self._load_cache()
        if tracking_number in cache:
            entry = cache[tracking_number]
            data = entry.get("data", {})
            age = time.time() - entry.get("cached_at", 0)
            
            # Check if delivered - if so, cache basically forever
            is_delivered = data.get("status", "").lower() == "delivered"
            is_error = data.get("error", False)
            is_pending = data.get("pending", False)
            
            if is_delivered:
                cache_duration = self.CACHE_DURATION_DELIVERED
            elif is_error:
                cache_duration = self.CACHE_DURATION_NOT_FOUND
            elif is_pending:
                cache_duration = self.CACHE_DURATION_PENDING
            else:
                cache_duration = self.CACHE_DURATION_ACTIVE
            
            if age < cache_duration:
                status_type = "delivered" if is_delivered else "active"
                print(f"  [CACHE] Found valid cache for {tracking_number} ({status_type}, age: {int(age)}s)")
                return data
            else:
                print(f"  [CACHE] Cache expired for {tracking_number} (age: {int(age)}s, was active package)")
        else:
            print(f"  [CACHE] No cache entry for {tracking_number}")
        return None
    
    def _set_cached(self, tracking_number: str, data: Dict):
        """Cache tracking data."""
        import time
        cache = self._load_cache()
        cache[tracking_number] = {
            "data": data,
            "cached_at": time.time()
        }
        self._save_cache(cache)
        is_delivered = data.get("status", "").lower() == "delivered"
        cache_type = "permanent" if is_delivered else "1 hour"
        print(f"  [CACHE] Cached data for {tracking_number} ({cache_type})")
    
    # Map our carrier names to TrackingMore courier codes
    TRACKINGMORE_CODES = {
        "ems": "china-ems",
        "china-post": "china-post",
        "yanwen": "yanwen",
        "uniteddeliveryservice": "uniteddeliveryservice",
        "topyou": "jaspost",
        "sf-express": "sf-express",
        "yto": "yto-express",
        "zto": "zto-express",
        "sto": "sto-express",
        "yunda": "yunda-express",
        "cainiao": "cainiao",
        "dhl": "dhl",
        "dhl-germany": "dhl-germany",
        "deutsche-post": "deutsche-post",
        "ups": "ups",
        "fedex": "fedex",
        "usps": "usps",
        "royal-mail": "royal-mail",
        "kr-ems": "korea-post",
        "hk-post": "hongkong-post",
        "australia-post": "australia-post",
        "japan-post": "japan-post",
        "singapore-post": "singapore-post",
        "4px": "4px",
        "eub": "china-ems",
        "canada-post": "canada-post",
        "yunexpress": "yunexpress",
        "jnet": "jnet",
        "aramex": "aramex",
    }

    def _is_dhl_tracking(self, tracking_number: str) -> bool:
        """Check if tracking number is from DHL (including DHL eCommerce)."""
        carrier = self.detect_carrier(tracking_number)
        return carrier in ["dhl", "dhl-germany", "deutsche-post", "dhlglobalmail"]
    
    async def _track_via_dhl(self, tracking_number: str) -> Dict:
        """Track package directly via DHL Unified Tracking API (free, 250/day)."""
        import aiohttp
        
        if not DHL_API_KEY:
            print("  [DHL] No API key configured, falling back to TrackingMore")
            return None
        
        print(f"\n[DHL DIRECT] Tracking {tracking_number} via DHL API...")
        
        # DHL Unified Tracking API endpoint
        url = f"https://api-eu.dhl.com/track/shipments?trackingNumber={tracking_number}"
        
        headers = {
            "DHL-API-Key": DHL_API_KEY,
            "Accept": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as resp:
                    print(f"  [DHL] Response status: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        shipments = data.get("shipments", [])
                        
                        if shipments and len(shipments) > 0:
                            shipment = shipments[0]
                            return self._process_dhl_response(shipment, tracking_number)
                        else:
                            print("  [DHL] No shipment data found")
                            return None
                    elif resp.status == 404:
                        print("  [DHL] Tracking number not found")
                        return None
                    elif resp.status == 401:
                        print("  [DHL] Authentication failed - check API key")
                        return None
                    else:
                        error_text = await resp.text()
                        print(f"  [DHL] Error {resp.status}: {error_text[:200]}")
                        return None
                        
        except Exception as e:
            print(f"  [DHL] Exception: {e}")
            return None
    
    def _process_dhl_response(self, shipment: Dict, tracking_number: str) -> Dict:
        """Process DHL API response into our standard format."""
        
        # Get status info
        status_info = shipment.get("status", {})
        current_status = status_info.get("status", "Unknown")
        status_code = status_info.get("statusCode", "")
        location_info = status_info.get("location", {})
        location_address = location_info.get("address", {})
        
        # Build location string
        location_parts = []
        if location_address.get("addressLocality"):
            location_parts.append(location_address.get("addressLocality"))
        if location_address.get("countryCode"):
            location_parts.append(location_address.get("countryCode"))
        current_location = ", ".join(location_parts) if location_parts else ""
        
        # Map DHL status codes to our standard status
        dhl_status_map = {
            "delivered": "Delivered",
            "transit": "In Transit",
            "out-for-delivery": "Out for Delivery",
            "customs": "In Customs",
            "failure": "Exception",
            "pre-transit": "Info Received",
            "unknown": "Pending"
        }
        mapped_status = dhl_status_map.get(status_code.lower(), current_status.title())
        
        # Process events/history
        events = shipment.get("events", [])
        history = []
        for event in events:
            event_location = event.get("location", {}).get("address", {})
            loc_parts = []
            if event_location.get("addressLocality"):
                loc_parts.append(event_location.get("addressLocality"))
            if event_location.get("countryCode"):
                loc_parts.append(event_location.get("countryCode"))
            
            history.append({
                "date": event.get("timestamp", ""),
                "status": event.get("description", event.get("status", "")),
                "location": ", ".join(loc_parts) if loc_parts else ""
            })
        
        # DHL returns events oldest-first; sort newest-first to match the
        # TrackingMore path so history[0] is the latest checkpoint.
        from datetime import datetime as _dhl_dt
        history.sort(
            key=lambda e: self.parse_event_dt(e.get("date", "")) or _dhl_dt.min,
            reverse=True,
        )
        
        # Get carrier info
        carrier_name = "DHL"
        service_info = shipment.get("service", "")
        if service_info:
            carrier_name = f"DHL {service_info}"
        
        # Get latest timestamp. Prefer DHL's authoritative summary timestamp;
        # only fall back to the newest history event (now history[0] after sort)
        # when the summary block has none.
        latest_timestamp = status_info.get("timestamp", "")
        if not latest_timestamp and history:
            latest_timestamp = history[0].get("date", "")
        
        # Calculate estimation — route through the model: pass the courier (so a DHL
        # Germany / Deutsche Post number resolves to its DE window) and any destination
        # country we can read from the freshest scan, instead of a flat hardcoded ETA.
        _cl = carrier_name.lower()
        _dhl_courier = ("dhl-germany" if ("paket" in _cl or "germany" in _cl or "parcel-de" in _cl)
                        else "deutsche-post" if "deutsche" in _cl else "dhl")
        _dhl_dest = ""
        if history:
            _last = (history[0].get("location", "") or "").split(",")[-1].strip().upper()
            if len(_last) == 2 and _last.isalpha() and _last not in ("CN", "HK", "SG"):
                _dhl_dest = _last
        estimation = self.estimate_delivery(carrier_name, mapped_status, location=current_location,
                                            history=history, dest_country=_dhl_dest, courier_code=_dhl_courier)

        # Special case: DHL Germany "instruction data only" = label created but package
        # not physically with DHL yet. Common for international rep shipping where the
        # China-leg uses a different carrier. Show helpful explanation.
        explanation = self.get_explanation(mapped_status)
        warning = None
        is_dhl_germany = ("parcel-de" in carrier_name.lower() or "germany" in carrier_name.lower())
        if is_dhl_germany:
            has_only_instruction = (
                len(history) <= 1
                and any("instruction data" in (h.get("status", "") or "").lower() for h in history)
            )
            if has_only_instruction:
                explanation = (
                    "DHL has the shipping label but hasn't physically received your package yet. "
                    "For international rep shipments, this typically means the package is still en route "
                    "to Germany via another carrier (often air freight) and DHL Paket will scan it on arrival. "
                    "This step normally takes 1-3 weeks. No action needed — tracking will update once DHL receives it."
                )
                mapped_status = "Pre-shipment"
                warning = {
                    "kind": "pre_handoff",
                    "title": "Sender hasn't handed off to DHL yet",
                    "body": "DHL has the label but doesn't have the package. Contact your shipping agent if it's been more than 2 weeks."
                }

        # Generic stall warning (any DHL service, not just Paket)
        if not warning and self.is_stalled_pre_handoff(history, mapped_status.lower()):
            warning = {
                "kind": "pre_handoff",
                "title": "Carrier hasn't received your package yet",
                "body": f"Your sender created a shipping label but {carrier_name} hasn't scanned the package as received. Contact your shipping agent — this shouldn't take more than a few days."
            }

        # Pick the hint/deep-link key matching this DHL variant
        hint_key = "dhl-germany" if is_dhl_germany else "dhl"
        carrier_hint = self.get_carrier_hint(hint_key)
        deep_link = self.get_deep_link(hint_key, tracking_number)

        print(f"  [DHL] Processed: {mapped_status}, {len(history)} events")

        return {
            "tracking_number": tracking_number,
            "carrier": carrier_name,
            "status": mapped_status,
            "explanation": explanation,
            "location": current_location,
            "timestamp": latest_timestamp,
            "history": history,
            "source": "DHL Direct",  # Shows we're using free direct API!
            "estimation": estimation,
            "error": False,
            "warning": warning,
            "carrier_hint": carrier_hint,
            "deep_link": deep_link,
        }

    def _is_canada_post_tracking(self, tracking_number: str) -> bool:
        """Check if tracking number is from Canada Post."""
        carrier = self.detect_carrier(tracking_number)
        return carrier == "canada-post"

    async def _track_via_canada_post(self, tracking_number: str) -> Dict:
        """Track package directly via Canada Post REST API (free)."""
        import base64

        if not CANADA_POST_API_USER or not CANADA_POST_API_PASS:
            print("  [CANADA POST] No API credentials configured, falling back to TrackingMore")
            return None

        print(f"\n[CANADA POST DIRECT] Tracking {tracking_number} via Canada Post API...")

        # Canada Post REST API endpoint (production)
        url = f"https://soa-gw.canadapost.ca/vis/track/pin/{tracking_number}/summary"

        # Basic auth: base64(username:password)
        auth_string = base64.b64encode(f"{CANADA_POST_API_USER}:{CANADA_POST_API_PASS}".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_string}",
            "Accept": "application/vnd.cpc.track-v2+xml",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    print(f"  [CANADA POST] Response status: {resp.status}")

                    if resp.status == 200:
                        # Canada Post returns XML
                        text = await resp.text()
                        return self._process_canada_post_response(text, tracking_number)
                    elif resp.status == 404:
                        print("  [CANADA POST] Tracking number not found")
                        return None
                    elif resp.status == 401 or resp.status == 403:
                        print("  [CANADA POST] Authentication failed - check API credentials")
                        return None
                    else:
                        error_text = await resp.text()
                        print(f"  [CANADA POST] Error {resp.status}: {error_text[:200]}")
                        return None

        except Exception as e:
            print(f"  [CANADA POST] Exception: {e}")
            return None

    def _process_canada_post_response(self, xml_text: str, tracking_number: str) -> Dict:
        """Process Canada Post XML response into our standard format."""
        import xml.etree.ElementTree as ET

        try:
            # Remove namespace for easier parsing
            xml_text = re.sub(r'\sxmlns[^"]*"[^"]*"', '', xml_text)
            root = ET.fromstring(xml_text)

            # Find the pin-summary element
            pin_summary = root.find('.//pin-summary')
            if pin_summary is None:
                pin_summary = root  # might be the root itself

            # Extract status
            event_desc = pin_summary.findtext('event-description', 'Unknown')
            event_type = pin_summary.findtext('event-type', '')
            event_date = pin_summary.findtext('event-date-time', '')
            event_location = pin_summary.findtext('event-location', '')

            # Map Canada Post event types to standard status
            cp_status_map = {
                'DELIVERY': 'Delivered',
                'INDELIVERY': 'Out for Delivery',
                'INTRANSIT': 'In Transit',
                'INFO_RECEIVED': 'Info Received',
                'PICKUP': 'Picked Up',
                'MISDIRECTED': 'Exception',
                'RETURNED': 'Returned',
            }

            mapped_status = cp_status_map.get(event_type.upper(), event_desc.title() if event_desc else 'In Transit')

            # Check for actual-delivery element
            actual_delivery = pin_summary.findtext('actual-delivery-date', '')
            if actual_delivery:
                mapped_status = 'Delivered'

            # Parse expected delivery
            expected_delivery = pin_summary.findtext('expected-delivery-date', '')
            estimation = ""
            if expected_delivery:
                try:
                    exp_date = datetime.strptime(expected_delivery, '%Y-%m-%d')
                    estimation = f"Expected delivery: {exp_date.strftime('%B %d, %Y')}"
                except:
                    estimation = f"Expected delivery: {expected_delivery}"

            # Build history from summary (Canada Post summary only gives latest event)
            history = []
            if event_desc:
                timestamp = ""
                if event_date:
                    try:
                        dt = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
                        timestamp = dt.strftime('%Y-%m-%d %H:%M')
                    except:
                        timestamp = event_date

                history.append({
                    "date": timestamp,
                    "status": event_desc,
                    "location": event_location or "",
                })

            # Now fetch detailed tracking events
            detail_history = self._fetch_canada_post_details(tracking_number)
            if detail_history:
                history = detail_history

            location = event_location or ""
            timestamp_display = ""
            if event_date:
                try:
                    dt = datetime.fromisoformat(event_date.replace('Z', '+00:00'))
                    timestamp_display = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    timestamp_display = event_date

            print(f"  [CANADA POST] Processed: {mapped_status}, {len(history)} events")

            cp_expl, cp_warn = self.pre_handoff_info("Canada Post", history, (mapped_status or "").lower())
            return {
                "tracking_number": tracking_number,
                "carrier": "Canada Post",
                "status": mapped_status,
                "explanation": cp_expl or f"Your package is being handled by Canada Post. Current status: {event_desc}",
                "location": location,
                "timestamp": timestamp_display,
                "history": history,
                "source": "Canada Post Direct",
                "estimation": estimation,
                "error": False,
                "warning": cp_warn,
                "carrier_hint": self.get_carrier_hint("canada-post"),
                "deep_link": self.get_deep_link("canada-post", tracking_number),
            }

        except ET.ParseError as e:
            print(f"  [CANADA POST] XML parse error: {e}")
            return None
        except Exception as e:
            print(f"  [CANADA POST] Processing error: {e}")
            return None

    def _fetch_canada_post_details(self, tracking_number: str) -> List:
        """Fetch detailed tracking events from Canada Post (synchronous call)."""
        import base64

        if not CANADA_POST_API_USER or not CANADA_POST_API_PASS:
            return []

        url = f"https://soa-gw.canadapost.ca/vis/track/pin/{tracking_number}/detail"
        auth_string = base64.b64encode(f"{CANADA_POST_API_USER}:{CANADA_POST_API_PASS}".encode()).decode()

        headers = {
            "Authorization": f"Basic {auth_string}",
            "Accept": "application/vnd.cpc.track-v2+xml",
        }

        try:
            resp = http_requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return []

            import xml.etree.ElementTree as ET
            xml_text = re.sub(r'\sxmlns[^"]*"[^"]*"', '', resp.text)
            root = ET.fromstring(xml_text)

            events = root.findall('.//occurrence')
            if not events:
                events = root.findall('.//significant-event')

            history = []
            for event in events:
                desc = event.findtext('event-description', '') or event.findtext('description', '')
                loc = event.findtext('event-site', '') or event.findtext('event-location', '')
                province = event.findtext('event-province', '')
                date = event.findtext('event-date', '')
                time_str = event.findtext('event-time', '')

                if province and loc:
                    loc = f"{loc}, {province}"

                timestamp = ""
                if date:
                    timestamp = date
                    if time_str:
                        timestamp = f"{date} {time_str}"

                if desc:
                    history.append({
                        "date": timestamp,
                        "status": desc,
                        "location": loc or "",
                    })

            return history

        except Exception as e:
            print(f"  [CANADA POST] Detail fetch error: {e}")
            return []

    # Some tracking numbers can work with multiple carriers.
    # If the primary carrier returns no data, try these fallbacks.
    CARRIER_FALLBACKS = {
        "china-post": ["china-ems", "cainiao", "yanwen", "4px", "canada-post", "usps", "royal-mail"],
        "ems": ["china-ems", "china-post", "cainiao", "canada-post"],
        "eub": ["china-ems", "china-post", "cainiao", "yanwen", "canada-post"],
        "yanwen": ["china-post", "cainiao", "canada-post"],
        "4px": ["china-post", "cainiao", "yanwen", "canada-post"],
        "cainiao": ["china-post", "yanwen", "4px", "canada-post"],
    }

    def _get_courier_code(self, tracking_number: str) -> str:
        """Get TrackingMore courier code from tracking number."""
        carrier = self.detect_carrier(tracking_number)
        if not carrier:
            print(f"  [CARRIER] Could not detect carrier")
            return None
        # If carrier is already a TrackingMore code (from detect API), use it directly
        if carrier in self.TRACKINGMORE_CODES:
            code = self.TRACKINGMORE_CODES[carrier]
            print(f"  [CARRIER] Detected: {carrier} -> courier_code: {code}")
            return code
        # Carrier code from detect API may already be a valid TrackingMore courier code
        print(f"  [CARRIER] Detected: {carrier} (using as courier_code directly)")
        return carrier

    def _get_fallback_codes(self, tracking_number: str) -> list:
        """Get fallback courier codes to try if primary returns no data."""
        carrier = self.detect_carrier(tracking_number)
        if carrier and carrier in self.CARRIER_FALLBACKS:
            return self.CARRIER_FALLBACKS[carrier]
        return []

    async def get_tracking_info(self, tracking_number: str, email: str = "") -> Dict:
        """Get tracking info - tries free carrier APIs first, falls back to TrackingMore."""
        tracking_number = tracking_number.strip().upper()
        carrier = self.detect_carrier(tracking_number)
        
        print(f"\n{'='*50}")
        print(f"Tracking {tracking_number}")
        print(f"{'='*50}")
        
        # Check file cache first
        cached = self._get_cached(tracking_number)
        if cached:
            print(f"[CACHE HIT] Returning cached data for {tracking_number}")
            return cached
        
        # ============================================
        # HYBRID APPROACH: Try free carrier APIs first
        # ============================================
        
        # Try DHL direct API (free, 250/day)
        if self._is_dhl_tracking(tracking_number):
            print("[HYBRID] DHL tracking detected - trying DHL direct API...")
            dhl_result = await self._track_via_dhl(tracking_number)
            if dhl_result and not dhl_result.get("error"):
                print("[HYBRID] DHL direct API SUCCESS - saved TrackingMore credits!")
                self._set_cached(tracking_number, dhl_result)
                return dhl_result
            print("[HYBRID] DHL direct API failed, falling back to TrackingMore...")
        
        # Try Canada Post direct API (free)
        if self._is_canada_post_tracking(tracking_number):
            print("[HYBRID] Canada Post tracking detected - trying Canada Post direct API...")
            cp_result = await self._track_via_canada_post(tracking_number)
            if cp_result and not cp_result.get("error"):
                print("[HYBRID] Canada Post direct API SUCCESS - saved TrackingMore credits!")
                self._set_cached(tracking_number, cp_result)
                return cp_result
            print("[HYBRID] Canada Post direct API failed, falling back to TrackingMore...")
        
        # ============================================
        # Fall back to TrackingMore for other carriers
        # ============================================
        print("[TRACKINGMORE] Using TrackingMore API...")
        
        import aiohttp
        
        api_key = os.getenv("TRACKINGMORE_API_KEY", "")
        
        if not api_key:
            print("ERROR: No TrackingMore API key found!")
            return self._tracking_error(tracking_number, carrier)
        
        headers = {
            "Content-Type": "application/json",
            "Tracking-Api-Key": api_key
        }
        
        courier_code = self._get_courier_code(tracking_number)
        
        try:
            async with aiohttp.ClientSession() as session:

                # If we couldn't detect carrier locally, try TrackingMore's detect API
                if not courier_code:
                    print("\n[Step 0] Using TrackingMore detect API...")
                    detect_url = "https://api.trackingmore.com/v4/couriers/detect"
                    detect_payload = {"tracking_number": tracking_number}
                    try:
                        async with session.post(detect_url, json=detect_payload, headers=headers, timeout=10) as resp:
                            detect_data = await resp.json()
                            if detect_data.get("meta", {}).get("code") == 200:
                                couriers = detect_data.get("data", [])
                                if couriers:
                                    courier_code = couriers[0].get("courier_code", "")
                                    print(f"  [DETECT] API detected: {courier_code}")
                    except Exception as e:
                        print(f"  [DETECT] Error: {e}")
                
                if not courier_code:
                    print("  [CARRIER] Could not detect carrier at all")
                    return self._tracking_error(tracking_number, "Unknown")
                
                # Step 1: Try to create tracking (works for new trackings)
                print(f"\n[Step 1] Creating tracking with courier_code={courier_code}...")
                step1_result = None
                create_url = "https://api.trackingmore.com/v4/trackings/create"
                create_payload = {
                    "tracking_number": tracking_number,
                    "courier_code": courier_code
                }
                if email:
                    create_payload["customer_email"] = email
                    print(f"  Including email: {email}")
                
                try:
                    async with session.post(create_url, json=create_payload, headers=headers, timeout=12) as resp:
                        data = await resp.json()
                        code = data.get("meta", {}).get("code")
                        print(f"  Code: {code}")

                        if code == 200:
                            # New tracking created - this includes full data
                            tracking_data = data.get("data", {})
                            result = self._process_trackingmore_response(tracking_data, tracking_number)
                            # Cache and return - even if no history yet (pending)
                            self._set_cached(tracking_number, result)
                            step1_result = result
                            if result.get("history") and len(result.get("history", [])) > 0:
                                return result
                            print("  Created but no tracking events yet - going straight to fetch/realtime")
                        elif code == 4101:
                            print("  Tracking already exists - will fetch via batch get")
                            # Don't delete/recreate, just fall through to Step 2
                except Exception as ce:
                    # A slow/failed create must NOT abort the lookup — fall through to the
                    # GET/realtime fetch steps (which work for already-created trackings).
                    print(f"  [Step 1] create call failed, continuing to fetch: {ce}")
                
                # Step 2: Fetch via the get endpoint (with retry). TM /trackings/get is
                # GET-only (?tracking_numbers=...); a POST list body returns HTTP 400, which
                # used to silently fail here and waste ~10s before the realtime fallback
                # rescued it. GET returns stored events immediately for existing trackings;
                # realtime (Step 2b) remains as a freshness fallback when GET has no events.
                batch_url = "https://api.trackingmore.com/v4/trackings/get"

                for attempt in range(2):
                    print(f"\n[Step 2] Get attempt {attempt + 1}/2...")
                    async with session.get(batch_url, params={"tracking_numbers": tracking_number}, headers=headers, timeout=20) as resp:
                        content_type = resp.headers.get('content-type', '')

                        if 'json' in content_type:
                            data = await resp.json()
                            batch_code = data.get('meta', {}).get('code')
                            print(f"  Batch response code: {batch_code}")

                            if batch_code == 200:
                                items = data.get("data", [])
                                if items and len(items) > 0:
                                    result = self._process_trackingmore_response(items[0], tracking_number)
                                    if result.get("history") and len(result.get("history", [])) > 0:
                                        self._set_cached(tracking_number, result)
                                        return result
                                    else:
                                        print("  Batch get returned data but no tracking events")
                                        step1_result = step1_result or result

                    if attempt < 1:
                        print(f"  No events yet, waiting 2s before retry...")
                        import asyncio
                        await asyncio.sleep(2)
                
                # Step 2a: Try up to 2 targeted fallback carriers via detect API + v3 realtime
                if not step1_result or not step1_result.get("history"):
                    print(f"\n[Step 2a] Primary carrier had no events. Trying targeted fallbacks...")
                    # Use detect API (free) to get best carrier suggestions
                    detected = self._detect_via_api(tracking_number)
                    fallback_tried = 0
                    if detected and detected != courier_code:
                        # Try detect API's top suggestion via batch get first (free)
                        print(f"  Detect API suggests: {detected}")
                        fb_batch = [{"tracking_number": tracking_number, "courier_code": detected}]
                        try:
                            async with session.post(batch_url, json=fb_batch, headers=headers, timeout=15) as fb_resp:
                                fb_data = await fb_resp.json()
                                if fb_data.get("meta", {}).get("code") == 200:
                                    fb_items = fb_data.get("data", [])
                                    if fb_items and len(fb_items) > 0:
                                        fb_history = fb_items[0].get("origin_info", {}).get("trackinfo", [])
                                        fb_history2 = fb_items[0].get("destination_info", {}).get("trackinfo", [])
                                        if fb_history or fb_history2:
                                            print(f"  Fallback {detected} has events via batch get!")
                                            result = self._process_trackingmore_response(fb_items[0], tracking_number)
                                            self._set_cached(tracking_number, result)
                                            return result
                        except Exception as fb_err:
                            print(f"  Fallback batch get error: {fb_err}")

                # Step 2b: Try v3 realtime API (returns live data directly from carrier)
                print("\n[Step 2b] Trying TrackingMore v3 realtime API...")
                v3_url = "https://api.trackingmore.com/v3/trackings/realtime"
                v3_payload = {
                    "tracking_number": tracking_number,
                    "courier_code": courier_code
                }
                try:
                    async with session.post(v3_url, json=v3_payload, headers=headers, timeout=30) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("code") == 200 and data.get("data"):
                                v3_data = data["data"]
                                origin_events = v3_data.get("origin_info", {}).get("trackinfo", [])
                                dest_events = v3_data.get("destination_info", {}).get("trackinfo", [])
                                print(f"  v3 realtime: {len(origin_events)} origin + {len(dest_events)} dest events")
                                if origin_events or dest_events:
                                    result = self._process_trackingmore_response(v3_data, tracking_number)
                                    self._set_cached(tracking_number, result)
                                    return result
                                else:
                                    print("  v3 realtime: no events")
                            else:
                                print(f"  v3 realtime code: {data.get('code')}")
                except Exception as e2b:
                    print(f"  [Step 2b] v3 realtime error: {e2b}")

                # Step 2c: Try single tracking endpoint
                print("\n[Step 2c] Trying single tracking endpoint...")
                single_url = f"https://api.trackingmore.com/v4/trackings/{tracking_number}"

                try:
                    async with session.get(single_url, headers=headers, timeout=20) as resp:
                        content_type = resp.headers.get('content-type', '')
                        if resp.status == 200 and 'json' in content_type:
                            data = await resp.json()
                            print(f"  Single tracking response code: {data.get('meta', {}).get('code')}")

                            if data.get("meta", {}).get("code") == 200:
                                tracking_data = data.get("data", {})
                                if tracking_data:
                                    result = self._process_trackingmore_response(tracking_data, tracking_number)
                                    self._set_cached(tracking_number, result)
                                    return result
                        else:
                            print(f"  Single tracking returned status={resp.status}, content-type={content_type}")
                except Exception as e2c:
                    print(f"  [Step 2c] Error: {e2c}")
                
                # Step 3: Return cached or error/waiting status
                if cached:
                    print("  [CACHE FALLBACK] Returning cached data")
                    return cached
                
                # If Step 1 got a valid pending result, return that
                if step1_result:
                    print("  [STEP 1 FALLBACK] Returning pending result from create")
                    return step1_result
                
                # If we have a courier code, the tracking is valid but just waiting for first scan
                if courier_code:
                    print(f"\n[Step 3] Carrier detected ({courier_code}) but no events yet - pending status")
                    carrier_name = courier_code.replace("-", " ").replace("_", " ").title()
                    hint = self.get_carrier_hint(courier_code)
                    deep = self.get_deep_link(courier_code, tracking_number)
                    # Tailor the explanation to what we actually know about the carrier
                    if hint and "doesn't share live data" in hint:
                        # Carriers our aggregator basically can't see (TaQBin JP)
                        explanation = (f"We detected the carrier ({carrier_name}) but our tracking partner "
                                       f"doesn't get live data from them. Use the direct link below to track on "
                                       f"the carrier's own site.")
                    elif hint and ("updates their own" in hint or "updates their own site" in hint or "scans usually appear" in hint or "tracking updates can lag" in hint):
                        # Small last-mile carriers that lag our aggregator (Axlehire, OnTrac, Newgistics, Veho)
                        explanation = (f"We detected the carrier ({carrier_name}) but our tracking partner is "
                                       f"behind on updates from this carrier. For the most current status, "
                                       f"use the direct link below.")
                    else:
                        explanation = (f"Good news! We detected your carrier ({carrier_name}) and the tracking "
                                       f"number looks valid. The carrier just hasn't scanned your package yet — "
                                       f"this usually happens within 24-48 hours after the label is created.")
                    pending_result = {
                        "tracking_number": tracking_number,
                        "carrier": carrier_name,
                        "status": "Waiting for Updates",
                        "explanation": explanation,
                        "location": "",
                        "timestamp": "",
                        "history": [],
                        "source": "TrackingMore",
                        "estimation": {
                            "min_days": None,
                            "max_days": None,
                            "estimated_date": None,
                            "confidence": "pending",
                            "confidence_note": "Waiting for first carrier scan"
                        },
                        "pending": True,
                        "error": False,
                        "contact": "@lude5 on Discord",
                        "carrier_hint": hint,
                        "deep_link": deep,
                    }
                    # Cache pending for 30 min - check again soon
                    self._set_cached(tracking_number, pending_result)
                    return pending_result
                
                # No courier code means we couldn't identify the tracking number at all
                print("\n[Step 3] No tracking data found - likely invalid tracking number")
                not_found_result = {
                    "tracking_number": tracking_number,
                    "carrier": "Unknown",
                    "status": "Tracking Not Found",
                    "explanation": "Hmm, I couldn't find any info for this tracking code. Double-check that you entered it correctly!",
                    "location": "",
                    "timestamp": "",
                    "history": [],
                    "source": "TrackingMore",
                    "estimation": {
                        "min_days": None,
                        "max_days": None,
                        "estimated_date": None,
                        "confidence": "low",
                        "confidence_note": "Tracking code not found"
                    },
                    "error": True,
                    "contact": "@lude5 on Discord"
                }
                # Cache not-found for 10 min so repeated lookups don't burn API calls
                self._set_cached(tracking_number, not_found_result)
                return not_found_result
                
        except Exception as e:
            print(f"\n[EXCEPTION] {e}")
            import traceback
            traceback.print_exc()
            if cached:
                print("  [CACHE FALLBACK ON ERROR]")
                return cached
            return self._tracking_error(tracking_number, carrier)
    
    async def track(self, tracking_number: str, email: str = "") -> Dict:
        """Public entry: get the base tracking, then enrich with the China line-haul
        origin leg (the forwarder events the destination carrier doesn't show) and
        cache the enriched result so later views are fast."""
        result = await self.get_tracking_info(tracking_number, email=email)
        try:
            if isinstance(result, dict) and not result.get("error"):
                tn = tracking_number.strip().upper()
                before = len(result.get("history") or [])
                import aiohttp
                async with aiohttp.ClientSession() as _s:
                    result = await self._enrich_with_origin_events(result, tn, _s)
                if len(result.get("history") or []) > before:
                    # We added the China line-haul leg — the parcel is clearly moving, so
                    # promote it out of the 'Info Received' limbo and refresh status/ETA/
                    # explanation off the real latest event, then cache the enriched result.
                    hist = result.get("history") or []
                    latest = (hist[0].get("status") or "") if hist else ""
                    ll = latest.lower()
                    if "deliver" not in ll:
                        result["status"] = "Out for Delivery" if "out for delivery" in ll else "In Transit"
                        result["explanation"] = (
                            "Now showing the China line-haul leg from your forwarder. Latest update: "
                            + (latest or "in transit")
                            + ". The destination carrier will keep updating once it scans the parcel in-country.")
                        try:
                            result["estimation"] = self.estimate_delivery(
                                result.get("carrier", ""), result["status"], location="", history=hist)
                        except Exception:
                            pass
                    self._set_cached(tn, result)
        except Exception as e:
            print(f"[ENRICH] track() wrapper error: {e}")
        # Always translate foreign event text on the way out (idempotent — also fixes
        # results that were cached before a translation was added).
        try:
            if isinstance(result, dict):
                for h in (result.get("history") or []):
                    if h.get("status"):
                        h["status"] = self.translate_event(h["status"])
        except Exception:
            pass
        return result

    async def _enrich_with_origin_events(self, result: Dict, tracking_number: str, session) -> Dict:
        """Find the China origin-leg events under a forwarder courier.

        DISABLED 2026-06-18 — COST GUARD. TrackingMore's v3 realtime endpoint is NOT
        free: every call CREATES a billable tracking. This method probed up to 5
        forwarder courier_codes per lookup, so one sparse-number lookup created up to
        5 extra billable trackings (account data confirmed the same number created
        under takesend/sfcservice/yunexpress/4px). That multiplied TM credit usage
        ~5-8x and caused the credit spike. Stays off until reworked to create-once-
        per-number (GET-check for an existing forwarder tracking before any realtime
        create), or moved to a free source. Do not re-enable the multi-probe version.
        """
        if not os.getenv("CHINA_LEG_ENRICH_ENABLED"):
            return result

        existing_history = result.get("history", [])

        # Only enrich the "looks empty / stuck at label" case (<=2 destination events) —
        # that's where the China origin leg is missing and worth the (rate-limited) realtime
        # lookups. Parcels already showing movement skip this, and the 20-min cache means a
        # given number triggers it at most once per window. Keeps TrackingMore realtime
        # volume low so the China leg shows reliably instead of intermittently.
        if len(existing_history) > 2:
            return result

        # Only try for pure digit numbers (cross-border packages)
        if re.search(r'[A-Za-z]', tracking_number):
            return result

        # Digit-relevant rep line-haul forwarders (lettered China-EMS/Post numbers are
        # already excluded by the A-Za-z gate above). Ordered most-likely-first; 'takesend'
        # holds the China leg for nearly every rep parcel.
        chinese_carriers = ["takesend", "sfcservice", "yunexpress", "4px", "cainiao"]
        api_key = os.getenv("TRACKINGMORE_API_KEY", "")
        if not api_key:
            return result

        headers = {"Content-Type": "application/json", "Tracking-Api-Key": api_key}
        new_events = []

        # Probe SEQUENTIALLY with an early break — NOT concurrently. TrackingMore's v3
        # realtime is burst rate-limited: firing all carriers at once gets ~7/8 back as
        # 429, including 'takesend' (which carries the China leg), so the journey silently
        # failed to merge. One-at-a-time means takesend (first) gets a clean call and the
        # common case is a single fast request. A total time budget keeps the rare
        # full-miss from dragging like the old 8-deep serial loop did.
        import time as _time
        _enrich_start = _time.monotonic()
        for carrier_code in chinese_carriers:
            if _time.monotonic() - _enrich_start > 10:
                print("  [ENRICH] time budget reached, stopping probes")
                break
            try:
                async with session.post(
                    "https://api.trackingmore.com/v3/trackings/realtime",
                    json={"tracking_number": tracking_number, "courier_code": carrier_code},
                    headers=headers, timeout=5
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        rd = data.get("data", {}) or {}
                        origin = (rd.get("origin_info") or {}).get("trackinfo") or []
                        dest = (rd.get("destination_info") or {}).get("trackinfo") or []
                        if origin or dest:
                            print(f"  [ENRICH] {carrier_code}: {len(origin)} origin + {len(dest)} dest events")
                            for e in origin + dest:
                                new_events.append({
                                    "date": e.get("checkpoint_date", ""),
                                    "status": self.translate_event(e.get("tracking_detail", e.get("StatusDescription", "")) or ""),
                                    "location": e.get("location", "")
                                })
                            break  # first carrier with data wins (no burst, reliable)
            except Exception as e:
                print(f"  [ENRICH] {carrier_code} error: {e}")

        if not new_events:
            return result

        # Merge and deduplicate events
        all_events = existing_history + new_events
        seen = set()
        unique = []
        for e in all_events:
            key = (e.get("date", ""), e.get("status", ""))
            if key not in seen:
                seen.add(key)
                unique.append(e)

        # Sort by date descending (newest first)
        unique.sort(key=lambda x: x.get("date", ""), reverse=True)

        result["history"] = unique
        print(f"  [ENRICH] Merged: {len(existing_history)} original + {len(new_events)} new = {len(unique)} total events")
        return result

    # Canonical status ordering. Used to ensure a newer checkpoint can only
    # ADVANCE the headline status, never move it backwards.
    STATUS_RANK = {
        "Not Found": 0,
        "Pending": 1,
        "Info Received": 2,
        "In Transit": 3,
        "Out for Delivery": 4,
        "Delivered": 5,
    }

    def _keyword_status_from_checkpoint(self, cp_status_text: str, cp_location: str) -> str:
        """Map a single checkpoint's raw status text to a canonical headline label,
        gated by whether the checkpoint is at the ORIGIN (China/HK/SG) side.

        Returns one of the canonical labels (matching the status_map values) or ""
        when the text doesn't clearly imply a forward status. CRITICAL: arrival /
        out-for-delivery / customs keywords only advance when NOT at origin, so a
        "arrived at sorting center" or "customs" scan in China can't masquerade as a
        destination-side arrival/delivery. Mirrors get_progress_percentage()'s
        origin gating to prevent drift.
        """
        status_lower = (cp_status_text or "").lower()
        location_lower = (cp_location or "").lower()

        # Same origin detection as get_progress_percentage()
        origin_keywords = [
            "china", "guangzhou", "shenzhen", "shanghai", "beijing", "hong kong",
            "hk", "singapore", "wuhan", "huizhou", "office of exchange",
            "guangdong", "zhejiang", "jiangsu", "fujian", "henan", "xiamen",
            "guangzhou ems", "cn", "cnwuhd", "cnsh", "cnhgh", "cnpek",
        ]
        is_origin = any(kw in location_lower for kw in origin_keywords)
        if "originating country" in status_lower or "office of exchange" in status_lower:
            is_origin = True

        # ALL forward statuses (incl. delivered) require the destination side — a
        # "delivered"/"arrived"/"customs" scan in China is a warehouse/consolidation
        # event, NOT final delivery, so it must never advance the headline status.
        if is_origin:
            return ""
        if "delivered" in status_lower:
            return "Delivered"
        if "out for delivery" in status_lower:
            return "Out for Delivery"
        if "arrived at destination" in status_lower or "arrived at local" in status_lower \
                or "arrival at" in status_lower or "arrived at facility" in status_lower:
            return "In Transit"
        if "transit" in status_lower or "departed" in status_lower or "in transit" in status_lower:
            return "In Transit"
        return ""

    def _advance_status(self, current_status: str, cp_status_text: str, cp_location: str) -> str:
        """Return the more-advanced of {current aggregate status, newest checkpoint
        status}. Never moves backwards; never advances on an origin-side scan.
        """
        cp_status = self._keyword_status_from_checkpoint(cp_status_text, cp_location)
        if not cp_status:
            return current_status
        cur_rank = self.STATUS_RANK.get(current_status, -1)
        cp_rank = self.STATUS_RANK.get(cp_status, -1)
        # Only override when the checkpoint maps to a known, strictly-more-advanced
        # rank. Unknown current statuses (cur_rank == -1) are left untouched to be safe.
        if cur_rank == -1 or cp_rank <= cur_rank:
            return current_status
        return cp_status

    def _process_trackingmore_response(self, tracking_data: Dict, tracking_number: str) -> Dict:
        """Process TrackingMore API response."""
        
        # Get origin info (checkpoints from origin country)
        origin_info = tracking_data.get("origin_info", {})
        dest_info = tracking_data.get("destination_info", {})
        
        # Combine checkpoints from both origin and destination
        all_checkpoints = []
        
        if dest_info and dest_info.get("trackinfo"):
            all_checkpoints.extend(dest_info.get("trackinfo", []))
        if origin_info and origin_info.get("trackinfo"):
            all_checkpoints.extend(origin_info.get("trackinfo", []))
        
        courier_code = tracking_data.get("courier_code") or "unknown"
        delivery_status = tracking_data.get("delivery_status") or "pending"
        
        # Also check for latest_event if no trackinfo
        latest_event = tracking_data.get("latest_event", "")
        latest_checkpoint_time = tracking_data.get("latest_checkpoint_time", "")

        # Capture delivered hauls into the learning dataset (deduped on tracking_number)
        # so the delivery-time model keeps sharpening from real outcomes. Transit days
        # are computed from the full timeline (first scan -> delivered), the same way
        # the model is built — NOT TM's transit_time field, which is unreliable.
        if delivery_status == "delivered":
            try:
                _dates = sorted(c.get("checkpoint_date", "")[:10] for c in all_checkpoints if c.get("checkpoint_date"))
                if len(_dates) >= 2:
                    import datetime as _dt
                    _days = (_dt.date.fromisoformat(_dates[-1]) - _dt.date.fromisoformat(_dates[0])).days
                    if 0 < _days <= 120:
                        from database import add_delivery_sample
                        add_delivery_sample(tracking_number, courier_code,
                                            tracking_data.get("origin_country"),
                                            tracking_data.get("destination_country"), _days)
            except Exception:
                pass

        print(f"  Processing: {courier_code}, status: {delivery_status}, {len(all_checkpoints)} checkpoints, latest_event: {latest_event[:50] if latest_event else 'None'}...")
        
        # Map delivery status
        status_map = {
            "delivered": "Delivered",
            "transit": "In Transit", 
            "pickup": "Out for Delivery",
            "pending": "Pending",
            "inforeceived": "Info Received",
            "expired": "Expired",
            "undelivered": "Undelivered",
            "exception": "Exception",
            "notfound": "Not Found"
        }
        current_status = status_map.get(delivery_status, delivery_status.replace("_", " ").title())
        carrier_name = courier_code.replace("-", " ").replace("_", " ").title()
        
        if all_checkpoints and len(all_checkpoints) > 0:
            history = []
            seen = set()
            for cp in all_checkpoints:
                d = cp.get("Date", cp.get("checkpoint_date", ""))
                s = cp.get("StatusDescription", cp.get("tracking_detail", cp.get("checkpoint_status", "")))
                loc = cp.get("Details", cp.get("location", ""))
                # Translate foreign-language phrases to plain English
                s = self.translate_event(s)
                # Dedupe identical events
                key = (d, s)
                if key in seen:
                    continue
                seen.add(key)
                history.append({"date": d, "status": s, "location": loc})

            # Sort newest first chronologically (parse real datetimes; fall back to
            # string compare only when a date can't be parsed)
            from datetime import datetime as _dt
            history.sort(key=lambda e: self.parse_event_dt(e.get("date", "")) or _dt.min, reverse=True)

            latest = history[0] if history else {}

            # Get latest location for progress calculation
            latest_location = latest.get("location", "")
            # The aggregate delivery_status from TrackingMore can lag behind the
            # newest checkpoint. Advance the headline status to reflect the freshest
            # scan, but ONLY when that scan is at the destination side and strictly
            # more advanced (never backwards, never on an origin/China event).
            current_status = self._advance_status(
                current_status, latest.get("status", ""), latest_location
            )
            estimation = self.estimate_delivery(carrier_name, current_status, location=latest_location, history=history,
                                                dest_country=(tracking_data.get("destination_country") or tracking_data.get("destination") or ""),
                                                courier_code=courier_code)

            # Special case: DHL Germany / Paket with only "instruction data" event
            explanation = self.get_explanation(current_status)
            warning = None
            if courier_code in ("dhl-germany", "dhl-parcel-de", "parcel-de"):
                has_only_instruction = (
                    len(history) <= 1
                    and any("instruction data" in (h.get("status", "") or "").lower() for h in history)
                )
                if has_only_instruction:
                    explanation = (
                        "DHL has the shipping label but hasn't physically received your package yet. "
                        "For international rep shipments, this typically means the package is still en route "
                        "to Germany via another carrier (often air freight) and DHL Paket will scan it on arrival. "
                        "This step normally takes 1-3 weeks. No action needed — tracking will update once DHL receives it."
                    )
                    warning = {
                        "kind": "pre_handoff",
                        "title": "Sender hasn't handed off to DHL yet",
                        "body": "DHL has the label but doesn't have the package. Contact your shipping agent if it's been more than 2 weeks."
                    }

            # Generalized pre-handoff stall warning for all carriers
            if not warning and self.is_stalled_pre_handoff(history, current_status.lower()):
                warning = {
                    "kind": "pre_handoff",
                    "title": "Carrier hasn't received your package yet",
                    "body": f"Your sender created a shipping label but {carrier_name} hasn't scanned the package as received. Contact your shipping agent — this shouldn't take more than a few days."
                }

            # Total transit days (first scan -> last scan) for the delivered/summary view
            transit_days = None
            if len(history) >= 2:
                first_dt = self.parse_event_dt(history[-1].get("date", ""))
                last_dt = self.parse_event_dt(history[0].get("date", ""))
                if first_dt and last_dt and last_dt >= first_dt:
                    transit_days = (last_dt - first_dt).days

            return {
                "tracking_number": tracking_number,
                "carrier": carrier_name,
                "status": current_status,
                "explanation": explanation,
                "location": latest.get("location", ""),
                "timestamp": latest.get("date", ""),
                "history": history,
                "source": "TrackingMore",
                "estimation": estimation,
                "origin_country": tracking_data.get("origin_country") or tracking_data.get("tracking_origin_country") or "",
                "destination_country": tracking_data.get("destination_country") or tracking_data.get("tracking_destination_country") or "",
                "warning": warning,
                "carrier_hint": self.get_carrier_hint(courier_code),
                "deep_link": self.get_deep_link(courier_code, tracking_number),
                "transit_days": transit_days,
            }
        else:
            # No checkpoints but we have the tracking - show what we know
            history = []
            
            # If there's a latest_event, add it as a history item
            if latest_event:
                history.append({
                    "date": latest_checkpoint_time or "",
                    "status": latest_event,
                    "location": ""
                })
            
            # Generate explanation based on status
            if delivery_status == "inforeceived" or current_status == "Info Received":
                explanation = "The shipping label has been created and info sent to the carrier. Waiting for the package to be picked up or dropped off."
            elif delivery_status == "pending":
                explanation = "Tracking registered. Waiting for the carrier to scan your package."
            else:
                explanation = self.get_explanation(current_status)
            
            # Use the real estimator so the ETA/progress card renders (it returns the
            # delivery_window/progress_percent shape the frontend expects); the old
            # {min_days,max_days} dict was silently dropped by the UI.
            estimation = self.estimate_delivery(carrier_name, current_status, location="", history=history,
                                                dest_country=(tracking_data.get("destination_country") or tracking_data.get("destination") or ""),
                                                courier_code=courier_code)
            return {
                "tracking_number": tracking_number,
                "carrier": carrier_name,
                "status": current_status,
                "explanation": explanation,
                "location": "",
                "timestamp": latest_checkpoint_time or "",
                "history": history,
                "source": "TrackingMore",
                "estimation": estimation,
                "origin_country": tracking_data.get("origin_country") or tracking_data.get("tracking_origin_country") or "",
                "destination_country": tracking_data.get("destination_country") or tracking_data.get("tracking_destination_country") or "",
                "carrier_hint": self.get_carrier_hint(courier_code),
                "deep_link": self.get_deep_link(courier_code, tracking_number),
            }

    def _tracking_error(self, tracking_number: str, carrier: str) -> Dict:
        """Return error response."""
        return {
            "tracking_number": tracking_number,
            "carrier": carrier or "Unknown",
            "status": "Tracking Not Found",
            "explanation": "Hmm, I couldn't find any info for this tracking code. Double-check that you entered it correctly!",
            "location": "",
            "timestamp": "",
            "history": [],
            "source": "None",
            "estimation": {
                "min_days": None,
                "max_days": None,
                "estimated_date": None,
                "confidence": "low",
                "confidence_note": "Tracking code not found"
            },
            "error": True,
            "contact": "@lude5 on Discord"
        }
    
    def _format_tracking_response(self, tracking_number: str, carrier_name: str, states: list, source: str, shipment: dict) -> Dict:
        """Format tracking response from any API into standard format."""
        history = []
        for state in states:
            history.append({
                "date": state.get("date", ""),
                "status": state.get("status", ""),
                "location": state.get("location", "")
            })
        
        latest = history[0] if history else {}
        current_status = latest.get("status", "In Transit")
        
        # Check if delivered
        status_lower = current_status.lower()
        if "delivered" in status_lower:
            current_status = "Delivered"
        elif "out for delivery" in status_lower:
            current_status = "Out for Delivery"
        elif "transit" in status_lower or "processed" in status_lower:
            current_status = "In Transit"
        
        estimation = self.estimate_delivery(carrier_name, current_status, history=history)

        # Use shipment delivery estimate if available
        if shipment.get("deliveryTime"):
            estimation["estimated_date"] = shipment.get("deliveryTime")
            estimation["confidence"] = "high"
        
        return {
            "tracking_number": tracking_number,
            "carrier": carrier_name,
            "status": current_status,
            "explanation": self.get_explanation(current_status),
            "location": latest.get("location", ""),
            "timestamp": latest.get("date", ""),
            "history": history,
            "source": source,
            "estimation": estimation
        }


class QCScraper:
    """Scrapes QC photos from shopping agents."""
    
    AGENT_PATTERNS = {
        "kakobuy": [r"kakobuy\.com", r"kakobuy\.co"],
        "sugargoo": [r"sugargoo\.com"],
        "cssbuy": [r"cssbuy\.com"],
        "cnfans": [r"cnfans\.com"],
        "joyabuy": [r"joyabuy\.com"],
        "pandabuy": [r"pandabuy\.com"],
        "hagobuy": [r"hagobuy\.com"],
        "wegobuy": [r"wegobuy\.com"],
        "superbuy": [r"superbuy\.com"],
    }
    
    def detect_agent(self, url: str) -> Optional[str]:
        for agent, patterns in self.AGENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url, re.IGNORECASE):
                    return agent
        return None
    
    async def scrape_qc_photos(self, url: str) -> Dict:
        """Scrape QC photos - in production, this would actually scrape."""
        agent = self.detect_agent(url)
        
        if not agent:
            return {"error": "Unsupported agent", "photos": []}
        
        # Demo response - in production, actually scrape the page
        demo_photos = [
            "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=400",
            "https://images.unsplash.com/photo-1606107557195-0e29a4b5b4aa?w=400",
            "https://images.unsplash.com/photo-1608231387042-66d1773070a5?w=400",
            "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=400",
        ]
        
        return {
            "agent": agent.title(),
            "photos": demo_photos,
            "product_name": "Sample Product - Nike Dunk Low",
            "price": "¥350",
            "url": url
        }


# ============== REDDIT SEARCH MODULE ==============

class RedditSearcher:
    """Search Reddit rep communities and summarize recommendations using Claude."""
    
    SUBREDDITS = [
        "FashionReps",
        "Repsneakers", 
        "RepLadies",
        "DesignerReps",
        "Repbudgetfashion",
        "QualityReps"
    ]
    
    def __init__(self):
        self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY', '')
    
    async def search_reddit(self, query: str) -> Dict:
        """Search Reddit and return posts with comments."""
        all_posts = []
        
        async with aiohttp.ClientSession() as session:
            # Search across all rep subreddits
            subreddit_str = "+".join(self.SUBREDDITS)
            search_url = f"https://www.reddit.com/r/{subreddit_str}/search.json"
            
            params = {
                "q": query,
                "restrict_sr": "on",
                "sort": "relevance",
                "t": "all",
                "limit": 15
            }
            
            headers = {
                "User-Agent": "RepTools/1.0 (Product Research Tool)"
            }
            
            try:
                async with session.get(search_url, params=params, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        posts = data.get("data", {}).get("children", [])
                        
                        for post in posts[:10]:  # Limit to top 10 posts
                            post_data = post.get("data", {})
                            
                            # Get comments for this post
                            permalink = post_data.get("permalink", "")
                            comments = await self._get_comments(session, permalink, headers)
                            
                            all_posts.append({
                                "title": post_data.get("title", ""),
                                "subreddit": post_data.get("subreddit", ""),
                                "score": post_data.get("score", 0),
                                "num_comments": post_data.get("num_comments", 0),
                                "url": f"https://reddit.com{permalink}",
                                "selftext": post_data.get("selftext", "")[:500],  # Limit text
                                "comments": comments,
                                "created": post_data.get("created_utc", 0)
                            })
                            
                            # Small delay to avoid rate limiting
                            await asyncio.sleep(0.5)
                            
            except Exception as e:
                print(f"Reddit search error: {e}")
                return {"error": str(e), "posts": []}
        
        return {"posts": all_posts, "query": query}
    
    async def _get_comments(self, session, permalink: str, headers: dict) -> List[str]:
        """Fetch top comments from a post."""
        comments = []
        
        try:
            url = f"https://www.reddit.com{permalink}.json"
            params = {"limit": 10, "sort": "top"}
            
            async with session.get(url, params=params, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    
                    if len(data) > 1:
                        comment_data = data[1].get("data", {}).get("children", [])
                        
                        for comment in comment_data[:5]:  # Top 5 comments
                            body = comment.get("data", {}).get("body", "")
                            if body and body != "[deleted]" and body != "[removed]":
                                comments.append(body[:300])  # Limit comment length
                                
        except Exception as e:
            print(f"Comment fetch error: {e}")
        
        return comments
    
    async def summarize_with_claude(self, query: str, reddit_data: Dict) -> Dict:
        """Use Claude to summarize Reddit recommendations."""
        
        if not self.anthropic_api_key:
            return self._basic_summary(query, reddit_data)
        
        # Build context from Reddit posts
        context = f"Product search: {query}\n\n"
        
        for i, post in enumerate(reddit_data.get("posts", [])[:8], 1):
            context += f"POST {i}: {post['title']}\n"
            context += f"Subreddit: r/{post['subreddit']} | Score: {post['score']} | Comments: {post['num_comments']}\n"
            if post.get('selftext'):
                context += f"Content: {post['selftext'][:200]}...\n"
            context += "Top comments:\n"
            for comment in post.get('comments', [])[:3]:
                context += f"- {comment[:150]}...\n"
            context += "\n"
        
        prompt = f"""Analyze these Reddit posts from replica fashion communities about "{query}".

{context}

IMPORTANT: For sneakers and some clothing items, the BATCH is often more important than the seller. Many sellers carry the same batches. Common batch names include:
- Sneakers: LJR, GX, PK, OG, M Batch, HP, VT, G Batch, X Batch, CSJ, WTG, Cappuccino, etc.
- If users mention specific batches, prioritize recommending the BATCH name, not just the seller.
- Note that multiple sellers may carry the same batch at different prices.

Provide a helpful summary with:
1. **Best Recommended Batch/Seller**: Which batches or sellers are most recommended. For sneakers, prioritize BATCH names (e.g., "LJR Batch" or "M Batch") over seller names. For clothing, seller names are usually more relevant.
2. **Where to Buy**: List sellers who carry the recommended batch (if applicable)
3. **Price Range**: What prices are people paying
4. **Quality Notes**: What do people say about quality, accuracy, flaws
5. **Sizing Advice**: Any sizing recommendations
6. **Watch Out For**: Common issues or things to avoid
7. **Top Links**: List 2-3 most helpful post URLs

Keep it concise and actionable. Format with markdown."""

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": self.anthropic_api_key,
                        "anthropic-version": "2023-06-01"
                    },
                    json={
                        "model": "claude-sonnet-4-20250514",
                        "max_tokens": 1024,
                        "messages": [
                            {"role": "user", "content": prompt}
                        ]
                    }
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        summary = data.get("content", [{}])[0].get("text", "")
                        
                        return {
                            "query": query,
                            "summary": summary,
                            "posts_analyzed": len(reddit_data.get("posts", [])),
                            "top_posts": [
                                {"title": p["title"], "url": p["url"], "subreddit": p["subreddit"], "score": p["score"]}
                                for p in reddit_data.get("posts", [])[:5]
                            ]
                        }
                    else:
                        error_text = await resp.text()
                        print(f"Claude API error: {error_text}")
                        return self._basic_summary(query, reddit_data)
                        
        except Exception as e:
            print(f"Claude summarization error: {e}")
            return self._basic_summary(query, reddit_data)
    
    def _basic_summary(self, query: str, reddit_data: Dict) -> Dict:
        """Fallback summary without Claude API."""
        posts = reddit_data.get("posts", [])
        
        # Extract batch mentions (important for sneakers)
        batch_keywords = [
            "ljr", "ljr batch", "gx", "gx batch", "pk", "pk batch", "og", "og batch",
            "m batch", "hp batch", "vt batch", "g batch", "x batch", "csj", "wtg",
            "cappuccino", "sk", "y3", "h12", "get batch", "god batch", "dt batch",
            "qy batch", "dg batch", "top batch", "s2", "lw batch", "gt batch"
        ]
        
        # Extract seller mentions
        seller_keywords = [
            "husky", "gman", "angel king", "repcourier", "topstoney", "singor", 
            "rick studio", "survival source", "brother sam", "nina", "darcy", 
            "feiyu", "busystone", "a1 top", "passerby", "philanthropist", 
            "cappuccino", "tj sneakers", "old chen", "sk", "wwtop", "kickwho"
        ]
        
        all_text = " ".join([
            p.get("title", "") + " " + p.get("selftext", "") + " " + " ".join(p.get("comments", []))
            for p in posts
        ]).lower()
        
        mentioned_batches = [b for b in batch_keywords if b in all_text]
        mentioned_sellers = [s for s in seller_keywords if s in all_text]
        
        # Look for GL/RL mentions
        gl_count = all_text.count(" gl ") + all_text.count("green light")
        rl_count = all_text.count(" rl ") + all_text.count("red light")
        
        summary = f"## Reddit Search Results for \"{query}\"\n\n"
        summary += f"**Posts Found:** {len(posts)}\n\n"
        
        if mentioned_batches:
            summary += f"**Mentioned Batches:** {', '.join(set(mentioned_batches)).upper()}\n\n"
        
        if mentioned_sellers:
            summary += f"**Mentioned Sellers:** {', '.join(set(mentioned_sellers)).title()}\n\n"
        
        if gl_count > 0 or rl_count > 0:
            summary += f"**Community Verdict:** {gl_count} GL mentions, {rl_count} RL mentions\n\n"
        
        summary += "**Top Posts:**\n"
        for p in posts[:5]:
            summary += f"- [{p['title'][:60]}...]({p['url']}) (r/{p['subreddit']}, {p['score']} upvotes)\n"
        
        return {
            "query": query,
            "summary": summary,
            "posts_analyzed": len(posts),
            "top_posts": [
                {"title": p["title"], "url": p["url"], "subreddit": p["subreddit"], "score": p["score"]}
                for p in posts[:5]
            ]
        }


# Initialize Reddit searcher
reddit_searcher = RedditSearcher()


# ============== IMAGE SEARCH MODULE ==============

class ImageSearcher:
    """Reverse image search for Chinese marketplaces."""
    
    def _parse_sales(self, sales_str: str) -> int:
        if not sales_str:
            return 0
        sales_str = str(sales_str).lower().strip()
        sales_str = re.sub(r'[^\d.kwm万+]', '', sales_str)
        try:
            if 'w' in sales_str or '万' in sales_str:
                return int(float(re.sub(r'[wm万+]', '', sales_str)) * 10000)
            elif 'k' in sales_str:
                return int(float(re.sub(r'[k+]', '', sales_str)) * 1000)
            else:
                return int(float(sales_str))
        except:
            return 0
    
    async def search(self, image_url: str) -> Dict:
        """Search for similar products - demo response."""
        # Demo response - in production, use real APIs
        demo_products = [
            {
                "title": "Nike Dunk Low Panda Black White",
                "price": "189",
                "sales": "50000+",
                "platform": "weidian",
                "url": "https://weidian.com/item.html?itemID=123456",
                "image": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=200"
            },
            {
                "title": "NK Dunk SB Low Premium Quality",
                "price": "320",
                "sales": "32000+",
                "platform": "taobao",
                "url": "https://item.taobao.com/item.htm?id=123456",
                "image": "https://images.unsplash.com/photo-1606107557195-0e29a4b5b4aa?w=200"
            },
            {
                "title": "Dunk Low Retro White Black",
                "price": "158",
                "sales": "28500+",
                "platform": "1688",
                "url": "https://detail.1688.com/offer/123456.html",
                "image": "https://images.unsplash.com/photo-1608231387042-66d1773070a5?w=200"
            },
            {
                "title": "SB Dunk Premium Batch",
                "price": "450",
                "sales": "15000+",
                "platform": "weidian",
                "url": "https://weidian.com/item.html?itemID=789012",
                "image": "https://images.unsplash.com/photo-1595950653106-6c9ebd614d3a?w=200"
            },
        ]
        
        # Sort by sales
        demo_products.sort(key=lambda x: self._parse_sales(x.get("sales", "0")), reverse=True)
        
        return {
            "products": demo_products,
            "total": len(demo_products)
        }


# Initialize services
tracking = TrackingAggregator()
qc_scraper = QCScraper()
image_searcher = ImageSearcher()


# ============== ROUTES ==============

@app.route('/')
def home():
    return render_template('home.html')


@app.route('/robots.txt')
def robots_txt():
    content = """User-agent: *
Allow: /
Disallow: /admin/
Disallow: /api/

# AI / answer-engine crawlers (ChatGPT, Perplexity, Claude, etc.) explicitly welcome
User-agent: OAI-SearchBot
Allow: /
User-agent: ChatGPT-User
Allow: /
User-agent: GPTBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Google-Extended
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: CCBot
Allow: /

Sitemap: https://rep.tools/sitemap.xml
"""
    return content, 200, {'Content-Type': 'text/plain'}


@app.route('/llms.txt')
def llms_txt():
    content = """# RepTools
> Free tools for the replica-fashion (rep) community: package tracking, QC photo viewer, product finder, and beginner guides.

## Pages
- [Home](https://rep.tools/): Free rep tools — package tracker, QC photos, and product finder.
- [Tools](https://rep.tools/tools): Track CNFans/KakoBuy packages, scrape QC photos, find batches.
- [Products](https://rep.tools/products): Browse thousands of rep finds by category.
- [Beginner Guide](https://rep.tools/tutorial): How to buy reps with an agent (Taobao/Weidian), step by step.
"""
    return content, 200, {'Content-Type': 'text/plain'}


@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404


@app.route('/sitemap.xml')
def sitemap_xml():
    from datetime import date
    today = date.today().isoformat()
    pages = [
        ('https://rep.tools/', '1.0', 'daily'),
        ('https://rep.tools/products', '0.9', 'daily'),
        ('https://rep.tools/tools', '0.9', 'weekly'),
        ('https://rep.tools/tutorial', '0.8', 'monthly'),
        ('https://rep.tools/contact', '0.5', 'monthly'),
        ('https://rep.tools/order', '0.6', 'monthly'),
        ('https://rep.tools/privacy', '0.3', 'yearly'),
        ('https://rep.tools/terms', '0.3', 'yearly'),
    ]
    for cat in PRODUCTS:
        pages.append((f'https://rep.tools/products/{cat}', '0.7', 'weekly'))
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url, priority, freq in pages:
        xml += f'  <url><loc>{url}</loc><lastmod>{today}</lastmod><priority>{priority}</priority><changefreq>{freq}</changefreq></url>\n'
    xml += '</urlset>'
    return xml, 200, {'Content-Type': 'application/xml'}



@app.route('/tools')
def tools():
    return render_template('tools.html')


@app.route('/contact')
def contact():
    return render_template('contact.html')


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.route('/terms')
def terms():
    return render_template('terms.html')


@app.route('/tutorial')
def tutorial():
    return render_template('tutorial.html')


@app.route('/order')
def order_site():
    return render_template('order.html')


@app.route('/api/site-order', methods=['POST'])
def submit_site_order():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data received"}), 400

    required = ['brand_name', 'email', 'primary_agent']
    for field in required:
        if not data.get(field):
            return jsonify({"success": False, "error": f"Missing required field: {field}"}), 400

    # Save order to JSON file
    import datetime
    order = {
        "submitted_at": datetime.datetime.utcnow().isoformat(),
        **data
    }

    try:
        from database import add_site_order
        add_site_order(order)
    except Exception as _e:
        print(f"[ORDER] DB save failed (Discord still sent): {_e}")

    print(f"[ORDER] New site order from {data.get('brand_name')} ({data.get('email')})")

    # Send Discord notification if webhook is configured
    try:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if webhook_url:
            import requests as req
            features = ', '.join(data.get('features', []))
            req.post(webhook_url, json={
                "embeds": [{
                    "title": "New Site Order!",
                    "color": 2277614,
                    "fields": [
                        {"name": "Brand", "value": data.get('brand_name', ''), "inline": True},
                        {"name": "Email", "value": data.get('email', ''), "inline": True},
                        {"name": "Agent", "value": data.get('primary_agent', ''), "inline": True},
                        {"name": "Features", "value": features or "None selected", "inline": False},
                    ]
                }]
            }, timeout=5)
    except Exception:
        pass

    return jsonify({"success": True})


@app.route('/api/report-tracking', methods=['POST'])
def report_tracking():
    """User reports an issue with a tracking number."""
    if limiter:
        limiter.limit("5 per hour")(lambda: None)()
    data = request.get_json() or {}
    tracking_number = data.get('tracking_number', '').strip()
    description = data.get('description', '').strip()

    if not tracking_number or not description:
        return jsonify({"success": False, "error": "Tracking number and description required"}), 400
    if len(description) > 1000:
        return jsonify({"success": False, "error": "Description too long"}), 400

    import datetime
    report = {
        "submitted_at": datetime.datetime.utcnow().isoformat(),
        "tracking_number": tracking_number[:50],
        "carrier": data.get('carrier', '')[:50],
        "status": data.get('status', '')[:50],
        "issue_type": data.get('issue_type', 'other')[:50],
        "description": description,
        "email": data.get('email', '').strip()[:120],
        "resolved": False,
        "admin_notes": ""
    }

    try:
        from database import add_tracking_report
        add_tracking_report(report)
    except Exception as _e:
        print(f"[REPORT] DB save failed (Discord still sent): {_e}")

    print(f"[REPORT] {report['issue_type']} on {tracking_number} from {report['email'] or 'anon'}")

    # Discord notification
    try:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if webhook_url:
            import requests as req
            req.post(webhook_url, json={
                "embeds": [{
                    "title": "🚩 New Tracking Report",
                    "color": 15158332,
                    "fields": [
                        {"name": "Tracking", "value": f"`{tracking_number}`", "inline": True},
                        {"name": "Carrier", "value": report['carrier'] or 'Unknown', "inline": True},
                        {"name": "Issue", "value": report['issue_type'].replace('_', ' ').title(), "inline": True},
                        {"name": "Description", "value": description[:1000], "inline": False},
                        {"name": "Email", "value": report['email'] or 'Anonymous', "inline": True},
                    ]
                }]
            }, timeout=5)
    except Exception:
        pass

    return jsonify({"success": True})


def _safe_int(v, default=0):
    """Parse an int from request input, falling back to default on bad/missing
    values (so a malformed ?days=abc returns the default instead of a 500)."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _deep_escape(obj):
    """Recursively HTML-escape string values so user-submitted / scraped data can't
    inject markup when a template builds HTML from it via innerHTML. Invisible for
    legit data (entities decode back to the same glyphs)."""
    import html as _h
    if isinstance(obj, str):
        return _h.escape(obj)
    if isinstance(obj, list):
        return [_deep_escape(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _deep_escape(v) for k, v in obj.items()}
    return obj


@app.route('/admin/reports', methods=['GET', 'POST'])
def admin_reports():
    if not session.get('admin'):
        return redirect('/admin/login')

    from database import get_tracking_reports, update_tracking_report

    if request.method == 'POST':
        # Update report (mark resolved, add notes, delete)
        action_data = request.get_json() or {}
        update_tracking_report(action_data.get('id'), action_data.get('action'),
                               action_data.get('notes', ''))
        return jsonify({"success": True})

    # GET — render page or return JSON (DB returns newest-first)
    reports = get_tracking_reports()
    if request.args.get('json'):
        return jsonify({"reports": _deep_escape(reports), "count": len(reports)})

    return render_template('admin_reports.html')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if limiter:
            limiter.limit("10 per hour")(lambda: None)()
        password = request.form.get('password', '')
        admin_pw = os.environ.get('ADMIN_PASSWORD', '')
        if admin_pw and password == admin_pw and len(password) >= 6:
            session.permanent = True
            session['admin'] = True
            return redirect('/admin/add')
        else:
            return render_template('admin_login.html', error='Wrong password')
    return render_template('admin_login.html', error=None)


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect('/admin/login')


@app.route('/admin/add')
def admin_add():
    if not session.get('admin'):
        return redirect('/admin/login')
    return render_template('admin_add.html')


@app.route('/admin/analytics')
def admin_analytics():
    if not session.get('admin'):
        return redirect('/admin/login')
    return render_template('admin_analytics.html')


@app.route('/admin/orders')
def admin_orders():
    if not session.get('admin'):
        return redirect('/admin/login')

    from database import get_site_orders
    orders = get_site_orders()  # newest-first

    if request.args.get('json'):
        return jsonify({"orders": _deep_escape(orders), "count": len(orders)})

    return render_template('admin_orders.html')


@app.route('/api/products/add', methods=['POST'])
def api_add_products():
    """Add products to database and products.json."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401
    try:
        new_products = request.json
        if not new_products or not isinstance(new_products, list):
            return jsonify({"error": "Expected a list of products"}), 400

        # Load current products.json
        json_path = os.path.join('static', 'products.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                products = json.load(f)
        else:
            products = {}

        # Check if background removal is requested (default: on)
        remove_bg = request.args.get('remove_bg', 'true').lower() != 'false'

        added = 0
        added_products = []
        for p in new_products:
            category = p.get('category', 'shoes')
            if category not in products:
                continue

            # Auto remove background from product image
            if remove_bg and BG_REMOVER_AVAILABLE and p.get('image'):
                try:
                    print(f"[BG] Removing background for: {p.get('name', '?')}")
                    p['image_original'] = p['image']
                    p['image'] = process_and_upload(p['image'])
                except Exception as bg_err:
                    print(f"[BG] Failed for {p.get('name', '?')}: {bg_err}")

            # Add to JSON file
            entry = {k: v for k, v in p.items() if k != 'category'}
            products[category]['items'].append(entry)

            # Add to database
            try:
                db_add_product({**p, "category": category})
            except Exception as e:
                print(f"[DB] Error adding product: {e}")

            added_products.append(p)
            added += 1

        # Save JSON
        with open(json_path, 'w') as f:
            json.dump(products, f, ensure_ascii=False)

        # Send Discord webhook notification
        if added_products:
            try:
                if len(added_products) == 1:
                    notify_new_product(added_products[0])
                else:
                    category = added_products[0].get('category', 'products')
                    notify_bulk_products(added_products, category)
            except Exception as e:
                print(f"[WEBHOOK] Error sending notification: {e}")

        return jsonify({"status": "success", "added": added})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/scrape-product', methods=['POST'])
def api_scrape_product():
    """Scrape product info from a Weidian/Taobao/1688 URL."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401
    import urllib.parse
    
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    
    # Extract platform and item ID
    platform = None
    item_id = None
    
    # Handle KakoBuy wrapped URLs
    if 'kakobuy.com' in url:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        inner = params.get('url', [''])[0]
        if inner:
            url = inner
    
    if 'weidian.com' in url:
        platform = 'weidian'
        match = re.search(r'itemID[=](\d+)', url)
        if match: item_id = match.group(1)
    elif 'taobao.com' in url or 'tmall.com' in url:
        platform = 'taobao'
        match = re.search(r'[?&]id=(\d+)', url)
        if match: item_id = match.group(1)
    elif '1688.com' in url:
        platform = '1688'
        match = re.search(r'/offer/(\d+)', url)
        if match: item_id = match.group(1)
    
    if not platform or not item_id:
        return jsonify({"error": "Could not parse URL. Supports Weidian, Taobao, 1688."}), 400
    
    result = {
        "platform": platform,
        "item_id": item_id,
        "name": "",
        "price": "",
        "image": "",
        "images": [],
        "variants": [],  # SKU variant names from the listing
    }
    
    try:
        if platform == 'weidian':
            result = _scrape_weidian(item_id, result)
        elif platform == 'taobao':
            result = _scrape_taobao(item_id, result)
        elif platform == '1688':
            result = _scrape_1688(item_id, result)
    except Exception as e:
        print(f"[SCRAPE] Error: {e}")
        result["error"] = str(e)
    
    # Generate KakoBuy link
    if platform == 'weidian':
        source = f"https://weidian.com/item.html?itemID={item_id}"
    elif platform == 'taobao':
        source = f"https://item.taobao.com/item.htm?id={item_id}"
    elif platform == '1688':
        source = f"https://detail.1688.com/offer/{item_id}.html"
    
    result["kakobuy_link"] = f"https://www.kakobuy.com/item/details?url={urllib.parse.quote(source, safe='')}&affcode=thelude"
    
    return jsonify(result)


@app.route('/api/identify-product', methods=['POST'])
def api_identify_product():
    """Use Claude AI to identify products from listing images."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401
    import base64
    
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return jsonify({"error": "ANTHROPIC_API_KEY not set in environment"}), 400
    
    data = request.get_json(silent=True) or {}
    image_urls = data.get('images', [])[:6]  # Max 6 images to keep costs down
    listing_name = data.get('listing_name', '')
    
    if not image_urls:
        return jsonify({"error": "No images provided"}), 400
    
    # Download images and convert to base64
    image_contents = []
    for img_url in image_urls:
        try:
            resp = http_requests.get(img_url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://weidian.com/",
            })
            if resp.status_code == 200:
                img_b64 = base64.b64encode(resp.content).decode('utf-8')
                # Detect media type
                ct = resp.headers.get('content-type', 'image/jpeg')
                if 'png' in ct:
                    media_type = 'image/png'
                elif 'webp' in ct:
                    media_type = 'image/webp'
                else:
                    media_type = 'image/jpeg'
                image_contents.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": img_b64}
                })
        except Exception as e:
            print(f"[AI] Failed to download image: {e}")
    
    if not image_contents:
        return jsonify({"error": "Could not download any images"}), 400
    
    # Build Claude API request
    prompt_parts = image_contents + [{
        "type": "text",
        "text": f"""These are product images from a Chinese replica goods listing. The listing title is: "{listing_name}"

Analyze the images and identify each distinct product shown (there may be multiple shoes/items in this listing).

For EACH distinct product you can identify, provide:
1. English product name (e.g. "Nike Dunk Low Panda", "Jordan 4 Black Cat", "New Balance 550 White Green")
2. Brand
3. Brief description

Respond ONLY in this JSON format, no other text:
[
  {{"name": "Nike Dunk Low Panda", "brand": "Nike", "description": "Black and white colorway"}},
  {{"name": "Jordan 4 Black Cat", "brand": "Jordan", "description": "All black colorway"}}
]"""
    }]
    
    try:
        api_resp = http_requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 1500,
                "messages": [{"role": "user", "content": prompt_parts}]
            },
            timeout=30
        )
        
        if api_resp.status_code != 200:
            print(f"[AI] API error: {api_resp.status_code} {api_resp.text[:200]}")
            return jsonify({"error": f"AI API error: {api_resp.status_code}"}), 500
        
        ai_data = api_resp.json()
        ai_text = ""
        for block in ai_data.get("content", []):
            if block.get("type") == "text":
                ai_text += block["text"]
        
        # Parse JSON from response
        ai_text = ai_text.strip()
        # Remove markdown fences if present
        ai_text = re.sub(r'^```json\s*', '', ai_text)
        ai_text = re.sub(r'\s*```$', '', ai_text)
        
        products = json.loads(ai_text)
        return jsonify({"products": products})
        
    except json.JSONDecodeError as e:
        print(f"[AI] JSON parse error: {e}, text: {ai_text[:200]}")
        return jsonify({"products": [], "raw": ai_text})
    except Exception as e:
        print(f"[AI] Error: {e}")
        return jsonify({"error": str(e)}), 500


def _scrape_weidian(item_id, result):
    """Scrape product data from Weidian using multiple methods."""
    import urllib.parse as urlparse
    
    # Method 1: Thor API — returns title, price, variants with images
    try:
        param_str = json.dumps({"itemId": item_id}, separators=(',', ':'))
        api_url = f"https://thor.weidian.com/detail/getItemSkuInfo/1.0?param={urlparse.quote(param_str)}"
        
        resp = http_requests.get(api_url, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.43",
            "Referer": f"https://shop.weidian.com/item.html?itemID={item_id}",
            "Origin": "https://shop.weidian.com",
            "Accept": "application/json, */*",
        }, timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            r = data.get('result') or {}
            
            # Title
            result['name'] = r.get('itemTitle') or r.get('title') or r.get('itemName') or ''
            
            # Price (in fen for discount fields, raw for others)
            low = r.get('itemDiscountLowPrice') or r.get('itemOriginalLowPrice')
            high = r.get('itemDiscountHighPrice') or r.get('itemOriginalHighPrice')
            if low and isinstance(low, int) and low > 100:
                result['price'] = str(low / 100)
                if high and high != low:
                    result['price_high'] = str(high / 100)
            elif r.get('price'):
                result['price'] = str(r['price'])
            
            # Main image
            main_pic = r.get('itemMainPic', '')
            if main_pic:
                result['image'] = main_pic
                result['images'] = [main_pic]
            
            # Extract variants from attrList (the gold mine)
            attr_list = r.get('attrList') or []
            variants = []
            for group in attr_list:
                group_title = group.get('attrTitle', '')  # e.g. "配色" (colorway), "Size"
                is_color_group = any(kw in group_title.lower() for kw in ['色', 'color', '配色', '款式', '款', 'style', '版本'])
                # If not obviously a size group, and has images, treat as product variants
                is_size_group = any(kw in group_title.lower() for kw in ['size', '尺码', '码', '尺寸', '号'])
                
                if is_size_group and not is_color_group:
                    continue  # Skip size selectors
                
                for val in group.get('attrValues', []):
                    variant_name = val.get('attrValue', '')
                    variant_img = val.get('img', '')
                    variant_id = val.get('attrId', '')
                    
                    if variant_name:
                        v = {
                            "name": variant_name,
                            "group": group_title,
                            "id": variant_id,
                        }
                        if variant_img:
                            v["image"] = variant_img
                            # Also add variant images to the main images list
                            if variant_img not in result['images']:
                                result['images'].append(variant_img)
                        variants.append(v)
            
            result['variants'] = variants
            
            print(f"[SCRAPE] Thor got: '{result['name'][:60]}', price=¥{result.get('price','?')}, {len(result['images'])} imgs, {len(variants)} variants")
            if result['name']:
                return result
    except Exception as e:
        print(f"[SCRAPE] Thor API failed: {e}")
    
    # Method 2: Scrape the desktop page HTML
    try:
        page_url = f"https://weidian.com/item.html?itemID={item_id}"
        resp = http_requests.get(page_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }, timeout=15)
        html = resp.text
        print(f"[SCRAPE] Weidian page size: {len(html)}")
        
        # Extract product images from Weidian CDN
        imgs = re.findall(r'(https?://si\.geilicdn\.com/[^\s"\'\\<>]+?\.(?:jpg|png|webp))(?:[?"\s][^\s]*)?', html)
        product_imgs = []
        seen = set()
        for img in imgs:
            # Clean URL
            clean = re.split(r'[?"]', img)[0]
            clean = re.sub(r'\.webp$', '', clean)
            if clean in seen:
                continue
            # Check if image has large dimensions (product photos)
            dim_match = re.search(r'_(\d+)_(\d+)', clean)
            if dim_match:
                w, h = int(dim_match.group(1)), int(dim_match.group(2))
                if w >= 500 and h >= 500:
                    seen.add(clean)
                    product_imgs.append(clean)
        
        if product_imgs:
            result['images'] = product_imgs[:8]
            result['image'] = product_imgs[0]
        elif imgs:
            # Fallback: use any CDN images that look like product images
            for img in imgs:
                clean = re.split(r'[?"]', img)[0]
                if clean not in seen and ('weidian' in clean or 'pcitem' in clean or 'shopimg' in clean):
                    seen.add(clean)
                    product_imgs.append(clean)
            if product_imgs:
                result['images'] = product_imgs[:8]
                result['image'] = product_imgs[0]
        
        # Search for title in multiple patterns
        name_patterns = [
            r'"itemName"\s*:\s*"([^"]+)"',
            r'"title"\s*:\s*"([^"]{10,200})"',
            r'"goodsName"\s*:\s*"([^"]+)"',
            r'<meta\s+name="description"\s+content="([^"]+)"',
            r'property="og:title"\s+content="([^"]+)"',
        ]
        for pattern in name_patterns:
            m = re.search(pattern, html)
            if m and len(m.group(1)) > 5 and m.group(1) not in ('商品详情', 'undefined'):
                result['name'] = m.group(1).strip()
                break
        
        # Search for price
        price_patterns = [
            r'"price"\s*:\s*"?(\d+\.?\d{0,2})"?',
            r'"minPrice"\s*:\s*"?(\d+\.?\d{0,2})"?',
            r'"curPrice"\s*:\s*"?(\d+\.?\d{0,2})"?',
            r'[¥￥]\s*(\d+\.?\d{0,2})',
        ]
        for pattern in price_patterns:
            m = re.search(pattern, html)
            if m and float(m.group(1)) > 0:
                result['price'] = m.group(1)
                break
        
        print(f"[SCRAPE] HTML got: name='{result.get('name','')[:50]}', price={result.get('price','')}, imgs={len(result.get('images',[]))}")
        
    except Exception as e:
        print(f"[SCRAPE] HTML failed: {e}")
    
    # Method 3: Try Weidian's shop mobile page variant
    if not result.get('name'):
        try:
            mobile_url = f"https://shop.weidian.com/item.html?itemID={item_id}"
            resp = http_requests.get(mobile_url, headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }, timeout=10)
            html = resp.text
            
            for pattern in name_patterns:
                m = re.search(pattern, html)
                if m and len(m.group(1)) > 5 and m.group(1) not in ('商品详情', 'undefined'):
                    result['name'] = m.group(1).strip()
                    break
            
            if not result.get('price'):
                for pattern in price_patterns:
                    m = re.search(pattern, html)
                    if m and float(m.group(1)) > 0:
                        result['price'] = m.group(1)
                        break
                        
            print(f"[SCRAPE] Mobile got: name='{result.get('name','')[:50]}', price={result.get('price','')}")
        except Exception as e:
            print(f"[SCRAPE] Mobile failed: {e}")
    
    return result


def _scrape_taobao(item_id, result):
    """Scrape product data from Taobao."""
    try:
        # Try mobile Taobao (often has more data in source)
        for base_url in [
            f"https://h5.m.taobao.com/awp/core/detail.htm?id={item_id}",
            f"https://item.taobao.com/item.htm?id={item_id}",
        ]:
            resp = http_requests.get(base_url, headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }, timeout=15, allow_redirects=True)
            html = resp.text
            
            # Title patterns
            for pattern in [
                r'"title"\s*:\s*"([^"]{10,200})"',
                r'"subject"\s*:\s*"([^"]+)"',
                r'"itemTitle"\s*:\s*"([^"]+)"',
                r'<title>([^<]{10,}?)\s*[-–]', 
            ]:
                m = re.search(pattern, html)
                if m and not result.get('name'):
                    result['name'] = m.group(1).strip()
                    break
            
            # Price
            for pattern in [
                r'"price"\s*:\s*"?(\d+\.?\d{0,2})"?',
                r'"reservePrice"\s*:\s*"?(\d+\.?\d{0,2})"?',
            ]:
                m = re.search(pattern, html)
                if m and float(m.group(1)) > 0 and not result.get('price'):
                    result['price'] = m.group(1)
                    break
            
            # Images from alicdn
            imgs = re.findall(r'(https?://(?:img|gw)\.alicdn\.com/[^\s"\'\\<>]+?\.(?:jpg|png|webp))', html)
            clean_imgs = []
            seen = set()
            for img in imgs:
                clean = re.split(r'[_\s]', img.split('?')[0])[0] + '.jpg'
                if clean not in seen and len(clean) > 30:
                    seen.add(clean)
                    clean_imgs.append(img.split('?')[0])
            if clean_imgs and not result.get('images'):
                result['images'] = clean_imgs[:8]
                result['image'] = clean_imgs[0]
            
            if result.get('name'):
                break
                
        print(f"[SCRAPE] Taobao: name='{result.get('name','')[:50]}', price={result.get('price','')}, imgs={len(result.get('images',[]))}")
        
    except Exception as e:
        print(f"[SCRAPE] Taobao failed: {e}")
    
    return result


def _scrape_1688(item_id, result):
    """Scrape product data from 1688."""
    try:
        page_url = f"https://detail.1688.com/offer/{item_id}.html"
        resp = http_requests.get(page_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }, timeout=15)
        html = resp.text
        
        # Title
        for pattern in [
            r'"subject"\s*:\s*"([^"]+)"',
            r'"title"\s*:\s*"([^"]{10,200})"',
            r'<title>([^<]+?)\s*[-–]',
        ]:
            m = re.search(pattern, html)
            if m:
                result['name'] = m.group(1).replace('-阿里巴巴', '').strip()
                break
        
        # Price
        for pattern in [
            r'"price"\s*:\s*"?(\d+\.?\d{0,2})"?',
            r'"priceRange"\s*:\s*"(\d+\.?\d{0,2})',
        ]:
            m = re.search(pattern, html)
            if m and float(m.group(1)) > 0:
                result['price'] = m.group(1)
                break
        
        # Images
        imgs = re.findall(r'(https?://cbu\d*\.alicdn\.com/[^\s"\'\\<>]+?\.(?:jpg|png|webp))', html)
        if imgs:
            clean = list(dict.fromkeys(img.split('?')[0] for img in imgs))[:8]
            result['images'] = clean
            result['image'] = clean[0]
            
        print(f"[SCRAPE] 1688: name='{result.get('name','')[:50]}', price={result.get('price','')}, imgs={len(result.get('images',[]))}")
        
    except Exception as e:
        print(f"[SCRAPE] 1688 failed: {e}")
    
    return result


@app.route('/products')
def products():
    return render_template('products.html', categories=PRODUCTS)


@app.route('/products/<category>')
def product_category(category):
    if category not in PRODUCTS:
        return render_template('products.html', categories=PRODUCTS)
    return render_template('products.html', categories=PRODUCTS, active_category=category)


@app.route('/api/batch-data')
def api_batch_data():
    """Return batch data for best batch search."""
    import json
    try:
        with open('batch_data.json', 'r') as f:
            data = json.load(f)
        # Buy links stay in batch_data.json (our private source) but are NOT exposed on
        # the site — strip them from the response so users see the batch, not the link.
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    item.pop('link', None)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/products')
def api_products():
    """Get all products from database (falls back to hardcoded if DB empty)."""
    try:
        products = db_get_all_products()
        if products:
            return jsonify(products)
    except Exception as e:
        print(f"[DB] Error loading products: {e}")
    return jsonify(PRODUCTS)


@app.route('/api/products/<category>')
def api_product_category(category):
    """Get products for a specific category from database."""
    try:
        cat_data = db_get_category_products(category)
        if cat_data:
            return jsonify(cat_data)
    except Exception as e:
        print(f"[DB] Error loading category: {e}")
    if category not in PRODUCTS:
        return jsonify({"error": "Category not found"}), 404
    return jsonify(PRODUCTS[category])


@app.route('/api/products/search')
def api_search_products():
    """Search products by name with optional category filter."""
    query = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip() or None
    try:
        limit = max(1, min(_safe_int(request.args.get('limit'), 20), 50))
    except (TypeError, ValueError):
        limit = 20

    if not query:
        return jsonify({"error": "Search query required (use ?q=)"}), 400

    try:
        results = db_search_products(query, category, limit)
        return jsonify({"query": query, "count": len(results), "results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============== AFFILIATE CLICK TRACKING ==============

@app.route('/api/click', methods=['POST'])
def record_click():
    """Record an affiliate link click for analytics."""
    data = request.get_json()

    product_id = data.get('product_id', '')
    product_name = data.get('product_name', '')
    category = data.get('category', '')
    agent = data.get('agent', 'kakobuy')

    if not product_id and not product_name:
        return jsonify({"error": "product_id or product_name required"}), 400

    try:
        track_click(
            product_id=product_id,
            product_name=product_name,
            category=category,
            agent=agent,
            referrer=request.referrer or '',
            user_ip=hashlib.sha256((request.remote_addr or '').encode()).hexdigest()[:16],
            user_agent=request.headers.get('User-Agent', '')[:200]
        )
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"[CLICK] Error: {e}")
        return jsonify({"status": "ok"})  # Don't fail the user


@app.route('/go/<product_id>')
def affiliate_redirect(product_id):
    """Redirect through affiliate link with click tracking."""
    agent = request.args.get('agent', 'kakobuy')

    # Find the product
    try:
        products = db_get_all_products()
        product_url = None
        product_name = ""
        product_category = ""

        for cat_slug, cat_data in products.items():
            for item in cat_data.get("items", []):
                if item.get("id") == product_id:
                    product_url = item.get("url", "")
                    product_name = item.get("name", "")
                    product_category = cat_slug
                    break
            if product_url:
                break

        # Fallback to hardcoded products
        if not product_url:
            for cat_slug, cat_data in PRODUCTS.items():
                for item in cat_data.get("items", []):
                    if item.get("id") == product_id:
                        product_url = item.get("url", "")
                        product_name = item.get("name", "")
                        product_category = cat_slug
                        break
                if product_url:
                    break

        if not product_url:
            return redirect("/products")

        # Track the click
        track_click(
            product_id=product_id,
            product_name=product_name,
            category=product_category,
            agent=agent,
            referrer=request.referrer or '',
            user_ip=hashlib.sha256((request.remote_addr or '').encode()).hexdigest()[:16],
            user_agent=request.headers.get('User-Agent', '')[:200]
        )

        return redirect(product_url)

    except Exception as e:
        print(f"[REDIRECT] Error: {e}")
        return redirect("/products")


# ============== ANALYTICS API ==============

@app.route('/api/analytics')
def api_analytics():
    """Get click analytics (admin only)."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401

    days = _safe_int(request.args.get('days'), 30)
    try:
        stats = get_click_stats(days)
        return jsonify(_deep_escape(stats))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/product/<product_id>')
def api_product_analytics(product_id):
    """Get click count for a specific product."""
    try:
        clicks = get_product_clicks(product_id)
        return jsonify({"product_id": product_id, "clicks": clicks})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/all-clicks')
def api_all_product_clicks():
    """Get click counts for all products at once. Cached 5 min."""
    try:
        if not DB_AVAILABLE:
            return jsonify({})
        from database import get_db
        with get_db() as db:
            rows = db.execute(
                "SELECT product_id, COUNT(*) as clicks FROM clicks GROUP BY product_id"
            ).fetchall()
        result = {row["product_id"]: row["clicks"] for row in rows}
        resp = jsonify(result)
        resp.headers['Cache-Control'] = 'public, max-age=300'
        return resp
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/analytics/report', methods=['POST'])
def send_analytics_report():
    """Manually trigger a Discord analytics report (admin only)."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        stats = get_click_stats(30)
        success = notify_daily_stats(stats)
        return jsonify({"status": "sent" if success else "failed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============== DATABASE MANAGEMENT ==============

@app.route('/api/db/import', methods=['POST'])
def import_to_db():
    """Import products into database (admin only)."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401

    source = request.args.get('source', 'hardcoded')

    try:
        if source == 'json':
            json_path = os.path.join(app.static_folder, 'products.json')
            count = import_products_from_json(json_path)
        else:
            count = import_hardcoded_products(PRODUCTS)

        return jsonify({"status": "ok", "imported": count})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/remove-bg', methods=['POST'])
def api_remove_bg():
    """Remove background from a single image URL (admin only)."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401

    if not BG_REMOVER_AVAILABLE:
        return jsonify({"error": "Background remover not installed (pip install rembg)"}), 500

    data = request.get_json()
    image_url = data.get('image_url', '').strip()

    if not image_url:
        return jsonify({"error": "image_url required"}), 400

    try:
        new_url = process_and_upload(image_url)
        return jsonify({"status": "ok", "original": image_url, "processed": new_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/remove-bg/bulk', methods=['POST'])
def api_remove_bg_bulk():
    """Remove backgrounds in small batches (3 per request) to avoid timeouts. Call repeatedly until done."""
    if not session.get('admin'):
        return jsonify({"error": "Unauthorized"}), 401

    if not BG_REMOVER_AVAILABLE:
        return jsonify({"error": "Background remover not installed (pip install rembg)"}), 500

    BATCH_SIZE = 3

    try:
        json_path = os.path.join('static', 'products.json')
        if not os.path.exists(json_path):
            return jsonify({"error": "products.json not found"}), 404

        with open(json_path, 'r', encoding='utf-8') as f:
            products = json.load(f)

        # Find items that still need processing
        pending = []
        already_done = 0
        for cat_slug, cat_data in products.items():
            for item in cat_data.get("items", []):
                image_url = item.get("image", "")
                if not image_url or len(image_url) < 10:
                    continue
                if "_nobg" in image_url or image_url.startswith("/static/images/products/"):
                    already_done += 1
                    continue
                pending.append((cat_slug, item))

        total = already_done + len(pending)

        if not pending:
            return jsonify({"status": "done", "processed": 0, "failed": 0, "remaining": 0, "total": total, "already_done": already_done})

        # Process only BATCH_SIZE items
        batch = pending[:BATCH_SIZE]
        processed = 0
        failed = 0

        for cat_slug, item in batch:
            image_url = item.get("image", "")
            try:
                new_url = process_and_upload(image_url)
                item["image_original"] = image_url
                item["image"] = new_url
                processed += 1
                print(f"[BG BULK] OK: {item.get('name', '?')[:50]}")
            except Exception as e:
                print(f"[BG BULK] Failed: {item.get('name', '?')}: {e}")
                failed += 1

        # Safe save — write to temp file first, then rename
        tmp_path = json_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(products, f, ensure_ascii=False)
        os.replace(tmp_path, json_path)

        remaining = len(pending) - processed - failed
        return jsonify({
            "status": "in_progress" if remaining > 0 else "done",
            "processed": processed,
            "failed": failed,
            "remaining": remaining,
            "total": total,
            "already_done": already_done + processed
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/track', methods=['POST'])
def track_package():
    if limiter:
        limiter.limit("20 per minute;200 per hour")(lambda: None)()
    data = request.get_json() or {}
    tracking_number = data.get('tracking_number', '').strip()
    email = data.get('email', '').strip()

    # Strip decorative brackets/wrappers users sometimes paste around tracking numbers
    # (Chinese tortoise brackets, full-width brackets, parens, square brackets, quotes,
    # zero-width chars, weird whitespace). Only the inner alphanumeric content matters.
    tracking_number = re.sub(r'[【】［］\[\]()【】「」『』"“”‘’​‌‍﻿\s]', '', tracking_number)

    # Input validation — prevent abuse
    if not tracking_number:
        return jsonify({"error": "Tracking number required"}), 400
    if len(tracking_number) > 50 or len(tracking_number) < 6:
        return jsonify({"error": "Invalid tracking number length"}), 400
    if not re.match(r'^[A-Za-z0-9\-]+$', tracking_number):
        return jsonify({"error": "Invalid tracking number format"}), 400
    if email and len(email) > 120:
        return jsonify({"error": "Invalid email"}), 400

    result = asyncio.run(tracking.track(tracking_number, email=email))

    # Centralized: whichever path produced this, if it's a 'label created / info-received
    # only' state (no real movement on the destination carrier) with no warning yet, attach
    # the China-leg explanation + warning so it doesn't look empty/dead to the user.
    try:
        if isinstance(result, dict) and not result.get("error") and not result.get("warning"):
            expl, warn = tracking.pre_handoff_info(
                result.get("carrier"), result.get("history") or [], (result.get("status") or "").lower())
            if warn:
                result["warning"] = warn
                if expl:
                    result["explanation"] = expl
    except Exception as e:
        print(f"[TRACK] pre-handoff post-process error: {e}")
    return jsonify(result)


@app.route('/api/subscribe-tracking', methods=['POST'])
def subscribe_tracking():
    """Subscribe an email to a tracking number. Phase 1: store the subscription
    LOCALLY (reliable source of truth) instead of relying on TrackingMore's
    customer_email field (which was broken). Status changes are delivered by the
    /api/tm-webhook receiver + our own email sender."""
    if limiter:
        limiter.limit("12 per hour")(lambda: None)()
    data = request.get_json() or {}
    tracking_number = data.get('tracking_number', '').strip().upper()
    email = data.get('email', '').strip()

    if not tracking_number or not email:
        return jsonify({"error": "Tracking number and email required"}), 400
    if len(email) > 120 or not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return jsonify({"status": "error", "message": "Please enter a valid email address."}), 400
    if len(tracking_number) > 50 or len(tracking_number) < 5:
        return jsonify({"status": "error", "message": "That tracking number doesn't look right."}), 400
    # Reject junk: a real tracking number always contains a digit, so this blocks
    # the literal "UNDEFINED"/"NULL"/etc. the frontend sends when the field is empty.
    if not re.search(r'\d', tracking_number) or tracking_number in ("UNDEFINED", "NULL", "NONE", "NAN", "UNKNOWN"):
        return jsonify({"status": "error", "message": "That tracking number doesn't look right."}), 400

    if not SUBS_AVAILABLE:
        return jsonify({"status": "error", "message": "Notifications are temporarily unavailable."}), 503

    try:
        try:
            courier_code = tracking._get_courier_code(tracking_number) or ""
        except Exception:
            courier_code = ""
        # Soft opt-in: the public subscribe form discloses that signups also receive
        # occasional related marketing (with one-click unsubscribe), so flag = 1.
        # (Admin-imported subscriptions are NOT flagged — they never saw the notice.)
        add_subscription(tracking_number, email, courier_code,
                         marketing_consent=1)
        print(f"[EMAIL] Subscribed {email} to {tracking_number} (courier: {courier_code or '?'}, mktg: 1 soft-optin)")
        return jsonify({"status": "success",
                        "message": "Done! We'll email you when this package updates."})
    except Exception as e:
        print(f"[EMAIL] subscribe error: {e}")
        return jsonify({"status": "error", "message": "Something went wrong. Try again in a moment."}), 500


@app.route('/api/tm-webhook', methods=['POST'])
def tm_webhook():
    """Receive TrackingMore status-change webhooks (free, no credits) and email
    subscribers. Returns 200 fast. Optional shared-secret via ?token= to deter abuse."""
    if not TM_WEBHOOK_TOKEN or request.args.get('token', '') != TM_WEBHOOK_TOKEN:
        return jsonify({"status": "forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    data = payload.get('data') or payload  # tolerate {data:{...}} or a flat object
    tn = (data.get('tracking_number') or '').strip().upper()
    courier = data.get('courier_code') or data.get('carrier_code') or ''
    status = data.get('delivery_status') or data.get('status') or ''
    if not tn:
        return jsonify({"status": "ignored", "reason": "no tracking_number"}), 200
    try:
        sent = _notify_subscribers(tn, courier, status, tm_obj=data)
        print(f"[EMAIL] webhook {tn} status={status} -> {sent} email(s)")
    except Exception as e:
        print(f"[EMAIL] webhook handler error: {e}")
        # Still 200 so TM doesn't hammer retries on a transient send error
    return jsonify({"status": "ok"}), 200


@app.route('/u/<token>', methods=['GET', 'POST'])
def email_unsubscribe(token):
    """Unsubscribe. RFC 8058 one-click clients POST (we unsubscribe). A plain GET
    (including mail-scanner / proxy / preview PREFETCH) must NOT mutate state — it
    only renders a confirmation page whose button POSTs back."""
    import html as _h
    if request.method == 'POST':
        if SUBS_AVAILABLE:
            unsubscribe_by_token(token)
        return ('', 200)  # one-click clients only need a 2xx
    tok = _h.escape(token)  # reflected in the form action below
    return f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe — RepTools</title></head>
<body style="margin:0;background:#0a0a0b;color:#fafafa;font-family:Arial,sans-serif;display:flex;min-height:100vh;align-items:center;justify-content:center;text-align:center;">
<div style="padding:2rem;"><div style="font-size:1.5rem;font-weight:800;color:#22d3ee;">RepTools</div>
<p style="margin-top:1rem;color:#a1a1aa;">Stop getting tracking-update emails for this package?</p>
<form method="POST" action="{SITE_BASE_URL}/u/{tok}" style="margin-top:1.25rem;">
<button type="submit" style="background:#22d3ee;color:#0a0a0b;border:none;padding:11px 22px;border-radius:9px;font-weight:700;font-size:14px;cursor:pointer;">Unsubscribe</button></form>
<a href="{SITE_BASE_URL}/tools" style="display:inline-block;margin-top:1.25rem;color:#71717a;">← Back to tracking</a></div></body></html>""", 200


@app.route('/api/email-webhook', methods=['POST'])
def email_provider_webhook():
    """Receive delivery-event webhooks from the email provider (Resend) and add
    bounced/complained addresses to the suppression list so we stop emailing them.
    Protect with ?token=<TM_WEBHOOK_TOKEN>. Returns 200 fast."""
    if not TM_WEBHOOK_TOKEN or request.args.get('token', '') != TM_WEBHOOK_TOKEN:
        return jsonify({"status": "forbidden"}), 403
    payload = request.get_json(silent=True) or {}
    etype = (payload.get('type') or '').lower()
    data = payload.get('data') or {}
    # Resend puts recipients in data.to (list) or data.email
    recipients = data.get('to') or ([data.get('email')] if data.get('email') else [])
    if isinstance(recipients, str):
        recipients = [recipients]
    try:
        if any(k in etype for k in ('bounce', 'complain', 'spam')):
            for addr in recipients:
                if addr:
                    add_suppression(addr, etype)
                    print(f"[EMAIL] suppressed {addr} ({etype})")
    except Exception as e:
        print(f"[EMAIL] email-webhook error: {e}")
    return jsonify({"status": "ok"}), 200


@app.route('/internal/recheck', methods=['GET', 'POST'])
def internal_recheck():
    """Backstop for any webhook TrackingMore failed to deliver: re-read current
    status of active subscriptions (FREE reads, no credits) and email on any new
    milestone. Point a free external cron (e.g. cron-job.org) at this every 6-12h.
    Protected by ?token=<INTERNAL_TOKEN or TM_WEBHOOK_TOKEN>."""
    secret = os.getenv("INTERNAL_TOKEN", "") or TM_WEBHOOK_TOKEN
    if not secret or request.args.get('token', '') != secret:
        return jsonify({"status": "forbidden"}), 403
    if not SUBS_AVAILABLE:
        return jsonify({"status": "unavailable"}), 503
    api_key = os.getenv("TRACKINGMORE_API_KEY", "")
    if not api_key:
        return jsonify({"status": "no_tm_key"}), 200
    subs = get_due_recheck_subscriptions(limit=200)
    if not subs:
        return jsonify({"status": "ok", "checked": 0, "emails": 0}), 200
    headers = {"Content-Type": "application/json", "Tracking-Api-Key": api_key}
    checked = 0
    emails = 0
    try:
        for i in range(0, len(subs), 40):
            chunk = subs[i:i+40]
            try:
                r = http_requests.get("https://api.trackingmore.com/v4/trackings/get",
                                      params={"tracking_numbers": ",".join(s["tracking_number"] for s in chunk)},
                                      headers=headers, timeout=20)
                jd = r.json()
                items = (jd.get("data") or []) if (jd.get("meta") or {}).get("code") == 200 else []
            except Exception as e:
                print(f"[RECHECK] batch error: {e}")
                continue
            for it in items:
                checked += 1
                tn = (it.get("tracking_number") or "").strip().upper()
                emails += _notify_subscribers(tn, it.get("courier_code") or "", it.get("delivery_status") or "", tm_obj=it)
    except Exception as e:
        print(f"[RECHECK] error: {e}")
    print(f"[RECHECK] checked {checked} trackings, sent {emails} email(s)")
    return jsonify({"status": "ok", "checked": checked, "emails": emails}), 200


@app.route('/admin/subscriptions')
def admin_subscriptions():
    """Admin view of email-notification activity (counts + recent rows)."""
    if not session.get('admin'):
        return redirect('/admin/login')
    if not SUBS_AVAILABLE:
        return jsonify({"error": "subscriptions unavailable"}), 503
    from database import get_db
    with get_db() as db:
        total = db.execute("SELECT COUNT(*) c FROM tracking_subscriptions").fetchone()["c"]
        active = db.execute("SELECT COUNT(*) c FROM tracking_subscriptions WHERE active=1").fetchone()["c"]
        sent = db.execute("SELECT COUNT(*) c FROM email_log WHERE result='sent'").fetchone()["c"]
        attempted = db.execute("SELECT COUNT(*) c FROM email_log").fetchone()["c"]
        suppressed = db.execute("SELECT COUNT(*) c FROM email_suppression").fetchone()["c"]
        recent = [dict(r) for r in db.execute(
            "SELECT tracking_number, email, last_notified_status, last_notified_at, active FROM tracking_subscriptions ORDER BY id DESC LIMIT 25").fetchall()]
        recent_log = [dict(r) for r in db.execute(
            "SELECT email, tracking_number, status_sent, result, sent_at FROM email_log ORDER BY id DESC LIMIT 25").fetchall()]
    return jsonify({
        "provider_configured": bool(RESEND_API_KEY),
        "totals": {"subscriptions": total, "active": active,
                   "emails_sent": sent, "emails_attempted": attempted, "suppressed": suppressed},
        "recent_subscriptions": recent,
        "recent_email_log": recent_log,
    })


@app.route('/admin/import-subscriptions', methods=['POST'])
def admin_import_subscriptions():
    """Bulk-import recovered tracking signups, seeding each to its CURRENT milestone
    so imported subscribers only get emails for FUTURE status changes (no spurious
    'delivered' blasts about packages that already arrived).
    Auth: admin session OR ?token=<INTERNAL_TOKEN or TM_WEBHOOK_TOKEN>.
    Body: {"subscriptions":[{"email","tracking_number","courier_code"?}], "dry_run":bool}.
    If no body list is given, falls back to recovered_subs.json on /data or next to app.py.
    Idempotent: safe to re-run; reads from TrackingMore are FREE (never creates)."""
    import re as _re
    secret = os.getenv("INTERNAL_TOKEN", "") or TM_WEBHOOK_TOKEN
    if not (session.get('admin') or (secret and request.args.get('token', '') == secret)):
        return jsonify({"status": "forbidden"}), 403
    if not SUBS_AVAILABLE:
        return jsonify({"status": "unavailable"}), 503

    body = request.get_json(silent=True) or {}

    # Fast DB-only mode: caller pre-computed current milestones (avoids slow
    # server-side TM reads that would exceed Render's HTTP proxy timeout).
    if body.get('baselines') is not None:
        from database import get_db
        baselined, courier_updated = 0, 0
        with get_db() as db:
            for b in (body.get('baselines') or []):
                tn = (b.get('tracking_number') or '').strip().upper()
                ms = (b.get('milestone') or '').strip()
                c = (b.get('courier_code') or '').strip()
                if not tn:
                    continue
                if ms:
                    cur = db.execute(
                        "UPDATE tracking_subscriptions "
                        "SET last_notified_status=?, last_notified_at=CURRENT_TIMESTAMP, "
                        "    courier_code=CASE WHEN courier_code='' OR courier_code IS NULL THEN ? ELSE courier_code END "
                        "WHERE tracking_number=? AND (last_notified_status='' OR last_notified_status IS NULL)",
                        (ms, c, tn))
                    baselined += cur.rowcount
                elif c:
                    cur = db.execute(
                        "UPDATE tracking_subscriptions SET courier_code=? "
                        "WHERE tracking_number=? AND (courier_code='' OR courier_code IS NULL)",
                        (c, tn))
                    courier_updated += cur.rowcount
        print(f"[IMPORT] baseline_only: baselined={baselined} courier_updated={courier_updated}")
        return jsonify({"status": "ok", "mode": "baseline_only",
                        "baselined": baselined, "courier_updated": courier_updated}), 200

    # Server-driven chunked baseline: the server selects un-seeded rows from the DB
    # itself (covers ALL subscriptions, not just an uploaded list) and processes a
    # bounded number per call so a single request stays under the proxy timeout.
    # Every queried tracking is marked (real milestone, or '_seeded' sentinel for
    # pending/unknown) so it leaves the un-seeded pool -> the caller loops until
    # remaining == 0. The sentinel never equals a milestone key, so a genuine future
    # status change still notifies normally.
    if body.get('auto_baseline'):
        api_key = os.getenv("TRACKINGMORE_API_KEY", "")
        if not api_key:
            return jsonify({"status": "no_tm_key"}), 200
        from database import get_db
        limit = max(1, min(_safe_int(body.get('limit'), 120), 200))
        with get_db() as db:
            tns = [r["tracking_number"] for r in db.execute(
                "SELECT DISTINCT tracking_number FROM tracking_subscriptions "
                "WHERE active=1 AND (last_notified_status='' OR last_notified_status IS NULL) "
                "ORDER BY tracking_number LIMIT ?", (limit,)).fetchall()]
        headers = {"Tracking-Api-Key": api_key}
        baselined, marked, chunks, chunk_fails = 0, 0, 0, 0
        for i in range(0, len(tns), 40):
            chunk = tns[i:i+40]
            chunks += 1
            try:
                r = http_requests.get("https://api.trackingmore.com/v4/trackings/get",
                                      params={"tracking_numbers": ",".join(chunk)},
                                      headers=headers, timeout=25)
                jd = r.json()
                read_ok = (jd.get("meta") or {}).get("code") == 200
                items = (jd.get("data") or []) if read_ok else []
            except Exception as e:
                print(f"[IMPORT] auto batch {i} error: {e}")
                items, read_ok = [], False
            if not read_ok:
                # Couldn't read this chunk -> do NOT mark it '_seeded' (that would later
                # spam a real 'delivered'); leave rows at '' so a future pass retries.
                chunk_fails += 1
                continue
            with get_db() as db:
                for it in items:
                    tn = (it.get("tracking_number") or "").strip().upper()
                    ds = (it.get("delivery_status") or "").lower()
                    cour = it.get("courier_code") or ""
                    if ds in EMAIL_MILESTONES:
                        ms = EMAIL_MILESTONES[ds][0]
                        cur = db.execute(
                            "UPDATE tracking_subscriptions "
                            "SET last_notified_status=?, last_notified_at=CURRENT_TIMESTAMP, "
                            "    courier_code=CASE WHEN courier_code='' OR courier_code IS NULL THEN ? ELSE courier_code END "
                            "WHERE tracking_number=? AND (last_notified_status='' OR last_notified_status IS NULL)",
                            (ms, cour, tn))
                        baselined += cur.rowcount
                    elif cour:
                        db.execute("UPDATE tracking_subscriptions SET courier_code=? "
                                   "WHERE tracking_number=? AND (courier_code='' OR courier_code IS NULL)",
                                   (cour, tn))
                # Mark every still-unseeded tracking in this chunk so it can't be
                # re-selected forever (pending / unknown / not-in-TM).
                qs = ",".join("?" for _ in chunk)
                cur = db.execute(
                    "UPDATE tracking_subscriptions SET last_notified_status='_seeded' "
                    "WHERE tracking_number IN (" + qs + ") "
                    "AND (last_notified_status='' OR last_notified_status IS NULL)", chunk)
                marked += cur.rowcount
        with get_db() as db:
            remaining = db.execute(
                "SELECT COUNT(DISTINCT tracking_number) c FROM tracking_subscriptions "
                "WHERE active=1 AND (last_notified_status='' OR last_notified_status IS NULL)").fetchone()["c"]
        tm_failed = chunks > 0 and chunk_fails == chunks
        print(f"[IMPORT] auto_baseline: processed={len(tns)} baselined={baselined} sentinel={marked} remaining={remaining} tm_failed={tm_failed}")
        # If EVERY chunk read failed (TM down/quota), report done so a 'while not done'
        # caller halts instead of spinning + burning requests; rows stay '' for a later run.
        return jsonify({"status": "ok", "mode": "auto_baseline", "processed": len(tns),
                        "baselined": baselined, "sentinel_marked": marked,
                        "remaining": remaining, "tm_read_failed": tm_failed,
                        "done": remaining == 0 or tm_failed}), 200

    dry_run = bool(body.get('dry_run'))
    rows = body.get('subscriptions')
    if not rows:
        _dir = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
        path = os.path.join(_dir, "recovered_subs.json")
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(__file__), "recovered_subs.json")
        if not os.path.exists(path):
            return jsonify({"status": "error", "msg": "no subscriptions in body and no recovered_subs.json found"}), 404
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            return jsonify({"status": "error", "msg": f"could not parse recovered_subs.json: {e}"}), 400

    if not isinstance(rows, list):
        return jsonify({"status": "error", "msg": "subscriptions must be a JSON list"}), 400
    EMAIL_RE = _re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    clean, skipped = {}, 0
    for r in (rows or []):
        if not isinstance(r, dict):
            skipped += 1
            continue
        email = (r.get("email") or "").strip().lower()
        tn = (r.get("tracking_number") or "").strip().upper()
        courier = (r.get("courier_code") or "").strip()
        if not email or not tn or not EMAIL_RE.match(email) or not (5 <= len(tn) <= 50):
            skipped += 1
            continue
        clean[(tn, email)] = courier  # dedupe on the (tracking, email) pair

    if dry_run:
        return jsonify({"status": "dry_run", "valid_pairs": len(clean),
                        "unique_trackings": len({t for (t, _e) in clean}),
                        "skipped": skipped}), 200

    created = 0
    for (tn, email), courier in clean.items():
        try:
            add_subscription(tn, email, courier)
            created += 1
        except Exception as e:
            print(f"[IMPORT] add_subscription failed {tn}/{email}: {e}")
            skipped += 1

    # Seed current status: FREE batch reads -> map TM status to milestone key ->
    # baseline only rows still at '' (idempotent; covers multiple emails per parcel).
    api_key = os.getenv("TRACKINGMORE_API_KEY", "")
    tns = sorted({t for (t, _e) in clean})
    baselined, no_status, tm_missing = 0, 0, (0 if api_key else len(tns))
    if api_key:
        from database import get_db
        headers = {"Content-Type": "application/json", "Tracking-Api-Key": api_key}
        for i in range(0, len(tns), 40):
            chunk = tns[i:i+40]
            try:
                r = http_requests.get("https://api.trackingmore.com/v4/trackings/get",
                                      params={"tracking_numbers": ",".join(chunk)},
                                      headers=headers, timeout=25)
                jd = r.json()
                items = (jd.get("data") or []) if (jd.get("meta") or {}).get("code") == 200 else []
            except Exception as e:
                print(f"[IMPORT] TM batch {i} error: {e}")
                continue
            with get_db() as db:
                for it in items:
                    tn = (it.get("tracking_number") or "").strip().upper()
                    ds = (it.get("delivery_status") or "").lower()
                    courier = it.get("courier_code") or ""
                    if ds not in EMAIL_MILESTONES:
                        if courier:
                            db.execute("UPDATE tracking_subscriptions SET courier_code=? "
                                       "WHERE tracking_number=? AND (courier_code='' OR courier_code IS NULL)",
                                       (courier, tn))
                        no_status += 1
                        continue
                    milestone = EMAIL_MILESTONES[ds][0]
                    cur = db.execute(
                        "UPDATE tracking_subscriptions "
                        "SET last_notified_status=?, last_notified_at=CURRENT_TIMESTAMP, "
                        "    courier_code=CASE WHEN courier_code='' OR courier_code IS NULL THEN ? ELSE courier_code END "
                        "WHERE tracking_number=? AND (last_notified_status='' OR last_notified_status IS NULL)",
                        (milestone, courier, tn))
                    baselined += cur.rowcount
    print(f"[IMPORT] created={created} baselined={baselined} no_status={no_status} skipped={skipped}")
    return jsonify({"status": "ok", "created": created, "baselined": baselined,
                    "no_milestone_status": no_status, "tm_key_missing": tm_missing,
                    "skipped": skipped, "unique_trackings": len(tns)}), 200


@app.route('/api/qc', methods=['POST'])
def scrape_qc():
    data = request.get_json()
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({"error": "URL required"}), 400
    
    try:
        # Extract the actual product URL if it's an agent link
        actual_url = extract_product_url(url)
        print(f"[QC] Input URL: {url}")
        print(f"[QC] Extracted URL: {actual_url}")
        
        kakobuy_token = os.getenv("KAKOBUY_TOKEN", "")
        if not kakobuy_token:
            print("[QC] ERROR: No KAKOBUY_TOKEN environment variable!")
            return jsonify({"status": "error", "message": "No KakoBuy API token configured"}), 500
        
        print(f"[QC] Token found: {kakobuy_token[:8]}...")
        
        api_url = "https://open.kakobuy.com/open/pic/qcImage"
        
        def _classify_kakobuy_error(result_json: dict):
            """Map KakoBuy's status=error responses to user-facing outcomes.
            Returns (kind, http_code, payload) or None if it's not a known
            soft-error pattern we can interpret."""
            if not isinstance(result_json, dict):
                return None
            msg = (result_json.get("message") or "").lower()
            if any(kw in msg for kw in [
                "no qc images", "no qc found", "not found qc", "no quality",
                "qc not available", "no image"
            ]):
                return ("empty", 200, {
                    "status": "empty",
                    "message": "No QC photos available for this product yet.",
                    "hint": "QC photos appear after the agent has physically inspected the item. Check back in a few days, or contact your agent if you've already received yours.",
                    "data": []
                })
            if any(kw in msg for kw in [
                "invalid goods url", "invalid url", "goods url", "url not supported",
                "unsupported url", "url is required", "url format"
            ]):
                return ("invalid_url", 400, {
                    "status": "invalid_url",
                    "message": "We couldn't recognize that link.",
                    "hint": "Paste a product link from Taobao, Weidian, 1688, or an agent (Kakobuy / Sugargoo / Pandabuy / etc.) link to the product page.",
                    "data": []
                })
            return None

        attempts = [
            ("GET with params",   lambda: http_requests.get(api_url,  params={"token": kakobuy_token, "goodsUrl": actual_url}, timeout=15)),
            ("POST with JSON",    lambda: http_requests.post(api_url, json={"token": kakobuy_token, "goodsUrl": actual_url},   headers={"Content-Type": "application/json"}, timeout=15)),
            ("POST with form",    lambda: http_requests.post(api_url, data={"token": kakobuy_token, "goodsUrl": actual_url},   timeout=15)),
        ]
        r = None
        last_kakobuy_message = None
        for label, do_call in attempts:
            try:
                print(f"[QC] Attempt: {label}")
                r = do_call()
                print(f"[QC] Response status: {r.status_code}")
                print(f"[QC] Response body: {r.text[:500]}")
                if r.status_code != 200:
                    continue
                try:
                    result = r.json()
                except Exception:
                    continue
                # Success path
                if result.get("status") == "success" or result.get("data"):
                    # KakoBuy's QC URLs include a broken watermark transformation
                    # (their sys/wm/logo.png is missing). Strip it so the raw
                    # images load directly in <img> tags.
                    items = result.get("data") or []
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict) and item.get("image_url"):
                                item["image_url"] = _strip_broken_watermark(item["image_url"])
                    # Background-cache all image URLs as a belt-and-suspenders archive
                    _kick_qc_prewarm(result)
                    return jsonify(result)
                # Classified soft error → return immediately with friendly response
                classified = _classify_kakobuy_error(result)
                if classified:
                    kind, code, payload = classified
                    if kind == "empty":
                        # KakoBuy has no QC for this item — try the open uufinds crowd DB
                        # (server-side, unauthenticated, no agent-account risk).
                        try:
                            from qc_sources import fetch_uufinds_qc
                            alt = fetch_uufinds_qc(actual_url)
                        except Exception as e:
                            alt = []
                            print(f"[QC] uufinds fallback error: {e}")
                        if alt:
                            print(f"[QC] uufinds fallback returned {len(alt)} photos")
                            resp = {"status": "success", "source": "uufinds", "data": alt}
                            _kick_qc_prewarm(resp)
                            return jsonify(resp)
                    print(f"[QC] Soft error '{kind}' (HTTP {code}) — not a server failure")
                    return jsonify(payload), code
                # Remember the message in case all attempts are unclassified
                last_kakobuy_message = result.get("message") or last_kakobuy_message
            except Exception as e:
                print(f"[QC] Attempt {label} error: {e}")

        # Unknown KakoBuy error — return as 400 (client-fixable) with their message
        if last_kakobuy_message:
            print(f"[QC] All attempts returned unrecognized error: {last_kakobuy_message}")
            return jsonify({
                "status": "error",
                "message": str(last_kakobuy_message)[:200],
                "hint": "Try a different product link, or contact @lude5 on Discord if this keeps happening.",
                "data": []
            }), 400

        # No response at all — that's a real server problem
        error_msg = r.text[:300] if r else 'No response'
        print(f"[QC] All attempts failed (no response). Last: {error_msg}")
        return jsonify({"status": "error", "message": f"KakoBuy API error: {error_msg}"}), 502
        
    except Exception as e:
        print(f"[QC] EXCEPTION: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# --- Image proxy cache (persistent disk) ---
# KakoBuy / agent CDNs frequently 404 their own QC photos after 2-7 days. We
# cache the bytes locally on first successful fetch so users can re-view photos
# even after the upstream URL goes dead.
IMG_CACHE_DIR = '/data/img_cache' if os.path.isdir('/data') else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img_cache')
IMG_CACHE_MAX_BYTES = 400 * 1024 * 1024  # 400 MB — keep generous headroom on Render's 5 GB disk


def _img_cache_path(img_url):
    """Map URL to cache file path: /data/img_cache/<2-char-bucket>/<sha256>.bin"""
    import hashlib
    h = hashlib.sha256(img_url.encode('utf-8')).hexdigest()
    return os.path.join(IMG_CACHE_DIR, h[:2], h + '.bin'), os.path.join(IMG_CACHE_DIR, h[:2], h + '.ct')


def _img_cache_get(img_url):
    """Return (body, content_type) if cached, else (None, None)."""
    body_path, ct_path = _img_cache_path(img_url)
    if not os.path.isfile(body_path):
        return None, None
    try:
        with open(body_path, 'rb') as f:
            body = f.read()
        ct = 'image/jpeg'
        if os.path.isfile(ct_path):
            try:
                with open(ct_path, 'r') as f:
                    ct = f.read().strip() or ct
            except Exception:
                pass
        # Touch mtime for LRU
        try:
            os.utime(body_path, None)
        except Exception:
            pass
        return body, ct
    except Exception as e:
        print(f"[IMG-CACHE] read error: {e}")
        return None, None


def _img_cache_put(img_url, body, content_type):
    """Atomically save body to cache. On disk-full, trigger emergency cleanup
    and retry once before giving up. Opportunistically samples the cache
    size on every write so cleanup keeps up with bursty pre-warm traffic."""
    body_path, ct_path = _img_cache_path(img_url)
    for attempt in range(2):
        try:
            os.makedirs(os.path.dirname(body_path), exist_ok=True)
            tmp = body_path + '.tmp'
            with open(tmp, 'wb') as f:
                f.write(body)
            os.replace(tmp, body_path)
            if content_type:
                try:
                    with open(ct_path, 'w') as f:
                        f.write(content_type[:100])
                except Exception:
                    pass
            # Sample on every successful write — keeps multi-worker / bursty
            # pre-warm traffic from blowing past the cap between batch-end checks
            _img_cache_cleanup_if_needed()
            return True
        except OSError as e:
            # ENOSPC = 28 (disk full). Trigger emergency cleanup, retry once.
            if e.errno == 28 and attempt == 0:
                print(f"[IMG-CACHE] disk full, triggering emergency cleanup")
                _img_cache_emergency_cleanup()
                # Best-effort: also remove the failed tmp file
                try:
                    if os.path.isfile(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
                continue
            print(f"[IMG-CACHE] write error: {e}")
            return False
        except Exception as e:
            print(f"[IMG-CACHE] write error: {e}")
            return False
    return False


def _img_cache_walk():
    """Return (total_bytes, [(mtime, size, body_path)]) for everything in the cache."""
    total = 0
    files = []
    if not os.path.isdir(IMG_CACHE_DIR):
        return total, files
    for root, _, names in os.walk(IMG_CACHE_DIR):
        for n in names:
            if not n.endswith('.bin'):
                continue
            p = os.path.join(root, n)
            try:
                st = os.stat(p)
                files.append((st.st_mtime, st.st_size, p))
                total += st.st_size
            except Exception:
                pass
    return total, files


def _img_cache_trim_to(target_bytes):
    """Delete oldest cache entries until total size <= target_bytes."""
    total, files = _img_cache_walk()
    if total <= target_bytes:
        return total, 0
    files.sort()  # oldest first
    freed = 0
    to_free = total - target_bytes
    for _, size, path in files:
        if freed >= to_free:
            break
        try:
            os.remove(path)
            ct_path = path[:-4] + '.ct'
            if os.path.isfile(ct_path):
                os.remove(ct_path)
            freed += size
        except Exception:
            pass
    return total, freed


def _img_cache_cleanup_if_needed():
    """Sample-based size check. Called from _img_cache_put on every write so
    bursty pre-warm batches don't blow past the cap between checks. 20%
    sampling rate keeps the walk cheap while still being responsive."""
    import random
    if random.random() >= 0.20:
        return
    total, _ = _img_cache_walk()
    if total <= IMG_CACHE_MAX_BYTES:
        return
    target = int(IMG_CACHE_MAX_BYTES * 0.7)
    _, freed = _img_cache_trim_to(target)
    print(f"[IMG-CACHE] LRU cleanup: was {total//(1024*1024)}MB, freed {freed//(1024*1024)}MB")


def _img_cache_emergency_cleanup():
    """Called when a write hits ENOSPC. Aggressively trim to 50% of cap so
    we have room to keep operating instead of looping on disk-full errors."""
    target = int(IMG_CACHE_MAX_BYTES * 0.5)
    before, freed = _img_cache_trim_to(target)
    print(f"[IMG-CACHE] emergency cleanup: was {before//(1024*1024)}MB, freed {freed//(1024*1024)}MB (target {target//(1024*1024)}MB)")


def _strip_broken_watermark(img_url):
    """KakoBuy QC URLs include `?x-oss-process=image/watermark,image_c3lzL3dtL2xvZ28ucG5n,...`
    which tries to overlay their watermark `sys/wm/logo.png` — a file they
    deleted/moved, so every watermarked request returns NoSuchKey 404.
    Stripping the transformation returns the raw image (which exists)."""
    try:
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
        p = urlparse(img_url)
        if not p.query:
            return img_url
        params = parse_qs(p.query, keep_blank_values=True)
        proc = params.get("x-oss-process", [""])[0].lower()
        # Only strip when the broken watermark is what would break the request
        if "watermark" in proc:
            params.pop("x-oss-process", None)
            new_query = urlencode(params, doseq=True)
            return urlunparse(p._replace(query=new_query))
    except Exception:
        pass
    return img_url


def _fetch_and_cache_image(img_url, referer):
    """Fetch a single image with the right headers and save to disk cache.
    Returns True on success, False otherwise. Idempotent — skips if already cached.
    Shared by /api/img-proxy (on-demand) and _prewarm_qc_images (background)."""
    # Strip KakoBuy's broken watermark transformation if present
    img_url = _strip_broken_watermark(img_url)
    # Already cached? Skip the fetch entirely.
    body_path, _ = _img_cache_path(img_url)
    if os.path.isfile(body_path):
        return True
    headers = {
        "Referer": referer,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
    }
    try:
        upstream = http_requests.get(img_url, headers=headers, timeout=20)
        if upstream.status_code != 200:
            return False
        body = upstream.content[:5 * 1024 * 1024]
        ct = upstream.headers.get("Content-Type", "image/jpeg")
        return _img_cache_put(img_url, body, ct)
    except Exception as e:
        print(f"[IMG-CACHE] fetch failed for {img_url[:120]}: {str(e)[:80]}")
        return False


def _prewarm_qc_images(image_urls):
    """Download all QC image URLs to cache in parallel. Runs in background thread
    so /api/qc returns immediately. Critical because KakoBuy expires QC images
    quickly (~2 days post-hack), so we must capture them while fresh."""
    from urllib.parse import urlparse
    from concurrent.futures import ThreadPoolExecutor

    # Same whitelist as /api/img-proxy
    ALLOWED = {
        "cdn.kakobuy.com": "https://www.kakobuy.com/",
        "img.kakobuy.com": "https://www.kakobuy.com/",
        "kakobuy.com":     "https://www.kakobuy.com/",
        "img.alicdn.com":  "https://www.taobao.com/",
        "gw.alicdn.com":   "https://www.taobao.com/",
        "img.sugargoo.com":"https://www.sugargoo.com/",
        "cdn.sugargoo.com":"https://www.sugargoo.com/",
        "img.pandabuy.com":"https://www.pandabuy.com/",
        "cdn.pandabuy.com":"https://www.pandabuy.com/",
        "file.uufinds.com":"https://www.uufinds.com/",
        "img.uufinds.com": "https://www.uufinds.com/",
    }

    def _resolve_referer(url):
        try:
            host = (urlparse(url).hostname or '').lower()
        except Exception:
            return None
        for allowed_host, ref in ALLOWED.items():
            if host == allowed_host or host.endswith('.' + allowed_host):
                return ref
        return None

    tasks = []
    for u in image_urls:
        if not isinstance(u, str) or not u.startswith(('http://', 'https://')):
            continue
        ref = _resolve_referer(u)
        if ref:
            tasks.append((u, ref))

    if not tasks:
        return

    print(f"[QC-PREWARM] starting {len(tasks)} downloads")
    ok = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = pool.map(lambda t: _fetch_and_cache_image(t[0], t[1]), tasks)
        ok = sum(1 for r in results if r)
    print(f"[QC-PREWARM] done: {ok}/{len(tasks)} cached")
    # Opportunistic cleanup
    _img_cache_cleanup_if_needed()


def _kick_qc_prewarm(qc_response_data):
    """Extract image URLs from a KakoBuy QC API response and start a background
    download thread. Non-blocking."""
    import threading
    try:
        items = qc_response_data.get("data") if isinstance(qc_response_data, dict) else None
        if not items or not isinstance(items, list):
            return
        urls = []
        for item in items:
            if isinstance(item, dict):
                u = item.get("image_url")
                if u:
                    urls.append(u)
            elif isinstance(item, str):
                urls.append(item)
        if not urls:
            return
        threading.Thread(target=_prewarm_qc_images, args=(urls,), daemon=True).start()
    except Exception as e:
        print(f"[QC-PREWARM] kick error: {e}")


@app.route('/api/img-proxy')
def img_proxy():
    """Fetch an external image with the right Referer header and stream it back.
    Caches successful fetches to persistent disk so re-views survive upstream
    deleting the original (KakoBuy QC photos expire after ~2 days)."""
    from urllib.parse import urlparse
    img_url = request.args.get('url', '').strip()
    if not img_url or not img_url.startswith(('http://', 'https://')):
        return jsonify({"error": "url required"}), 400
    if len(img_url) > 2000:
        return jsonify({"error": "url too long"}), 400

    try:
        host = (urlparse(img_url).hostname or '').lower()
    except Exception:
        return jsonify({"error": "invalid url"}), 400

    # Whitelist of CDN hosts we're willing to proxy. Each maps to the Referer
    # header value that domain expects (usually their own root).
    ALLOWED = {
        "cdn.kakobuy.com":      "https://www.kakobuy.com/",
        "img.kakobuy.com":      "https://www.kakobuy.com/",
        "kakobuy.com":          "https://www.kakobuy.com/",
        "img.alicdn.com":       "https://www.taobao.com/",
        "gw.alicdn.com":        "https://www.taobao.com/",
        "img01.taobaocdn.com":  "https://www.taobao.com/",
        "img02.taobaocdn.com":  "https://www.taobao.com/",
        "img.sugargoo.com":     "https://www.sugargoo.com/",
        "cdn.sugargoo.com":     "https://www.sugargoo.com/",
        "img.pandabuy.com":     "https://www.pandabuy.com/",
        "cdn.pandabuy.com":     "https://www.pandabuy.com/",
        "file.uufinds.com":     "https://www.uufinds.com/",
        "img.uufinds.com":      "https://www.uufinds.com/",
    }
    # Also accept any subdomain of allowed roots
    referer = None
    for allowed_host, ref in ALLOWED.items():
        if host == allowed_host or host.endswith('.' + allowed_host):
            referer = ref
            break
    if not referer:
        return jsonify({"error": "host not allowed"}), 403

    # 1) Cache hit — serve from disk immediately
    cached_body, cached_ct = _img_cache_get(img_url)
    if cached_body:
        resp = make_response(cached_body)
        resp.headers["Content-Type"] = cached_ct or "image/jpeg"
        resp.headers["Cache-Control"] = "public, max-age=86400"
        resp.headers["X-Cache"] = "HIT"
        return resp

    # Browser-y headers — some CDNs require these, not just Referer.
    proxy_headers = {
        "Referer": referer,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Sec-Fetch-Dest": "image",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
    }

    # 2) Cache miss — fetch from upstream
    last_err = None
    last_status = None
    for attempt in range(2):  # 1 retry on transient failures
        try:
            upstream = http_requests.get(img_url, headers=proxy_headers, timeout=20)
            last_status = upstream.status_code
            if upstream.status_code == 200:
                ct = upstream.headers.get("Content-Type", "image/jpeg")
                if not ct.lower().startswith("image/"):
                    ct = "image/jpeg"  # nosniff-safe: some CDNs mislabel valid images
                body = upstream.content[:5 * 1024 * 1024]
                # Save to cache for future requests
                _img_cache_put(img_url, body, ct)
                _img_cache_cleanup_if_needed()
                resp = make_response(body)
                resp.headers["Content-Type"] = ct
                resp.headers["Cache-Control"] = "public, max-age=86400"
                resp.headers["X-Cache"] = "MISS"
                return resp
            if upstream.status_code in (429, 500, 502, 503, 504):
                print(f"[IMG-PROXY] upstream {upstream.status_code} on attempt {attempt+1}, retrying...")
                continue
            print(f"[IMG-PROXY] upstream {upstream.status_code} (permanent) for {img_url[:120]}")
            break
        except Exception as e:
            last_err = str(e)[:120]
            print(f"[IMG-PROXY] attempt {attempt+1} exception: {last_err}")

    msg = f"upstream {last_status}" if last_status else f"fetch failed: {last_err}"
    return jsonify({"error": msg}), 502


def extract_product_url(url):
    """Extract the actual product URL from agent links."""
    from urllib.parse import urlparse, parse_qs, unquote
    
    parsed = urlparse(url)
    host = parsed.hostname or ""
    params = parse_qs(parsed.query)
    
    direct_domains = ['item.taobao.com', 'detail.tmall.com', 'weidian.com', 
                      'detail.1688.com', 'taobao.com', 'm.intl.taobao.com']
    for domain in direct_domains:
        if domain in host:
            return url
    
    url_param_names = ['url', 'goodsUrl', 'goods_url', 'productUrl']
    for param_name in url_param_names:
        if param_name in params:
            return unquote(params[param_name][0])
    
    item_id = None
    platform = None
    
    id_params = ['itemID', 'id', 'itemId', 'item_id', 'nTag']
    for p in id_params:
        if p in params:
            item_id = params[p][0]
            break
    
    platform_params = ['platform', 'source', 'channel']
    for p in platform_params:
        if p in params:
            platform = params[p][0].lower()
            break
    
    if item_id:
        if platform and 'weidian' in platform:
            return f"https://weidian.com/item.html?itemID={item_id}"
        elif platform and '1688' in platform:
            return f"https://detail.1688.com/offer/{item_id}.html"
        else:
            return f"https://item.taobao.com/item.htm?id={item_id}"
    
    return url


@app.route('/api/search', methods=['POST'])
def search_image():
    data = request.get_json()
    image_url = data.get('image_url', '').strip()
    
    if not image_url:
        return jsonify({"error": "Image URL required"}), 400
    if len(image_url) > 2000 or not image_url.startswith(('http://', 'https://')):
        return jsonify({"error": "Invalid image URL"}), 400

    result = asyncio.run(image_searcher.search(image_url))
    return jsonify(result)


@app.route('/api/reddit-search', methods=['POST'])
def reddit_search():
    """Search Reddit rep communities and get AI-powered summary."""
    data = request.get_json()
    query = data.get('query', '').strip()
    
    if not query or len(query) > 200:
        return jsonify({"error": "Invalid search query"}), 400
    if limiter:
        limiter.limit("5 per minute;30 per hour")(lambda: None)()

    async def _search():
        reddit_data = await reddit_searcher.search_reddit(query)
        if reddit_data.get("error"):
            return reddit_data, True
        return await reddit_searcher.summarize_with_claude(query, reddit_data), False

    result, has_error = asyncio.run(_search())
    return jsonify(result), (500 if has_error else 200)


# ============== AI TOOLS API ==============

@app.route('/api/qc-score', methods=['POST'])
@_rl("10 per minute;100 per day")
def api_qc_score():
    """Compare QC photo against retail reference photo. Returns similarity score."""
    if not AI_TOOLS_AVAILABLE:
        return jsonify({"error": "AI tools not available on this server"}), 503

    try:
        # Accept either file uploads or URLs
        qc_image = None
        retail_image = None

        if 'qc_image' in request.files:
            qc_image = _get_image_from_bytes(request.files['qc_image'].read())
        elif request.form.get('qc_url'):
            qc_image = _get_image_from_url(request.form['qc_url'])

        if 'retail_image' in request.files:
            retail_image = _get_image_from_bytes(request.files['retail_image'].read())
        elif request.form.get('retail_url'):
            retail_image = _get_image_from_url(request.form['retail_url'])

        if qc_image is None or retail_image is None:
            return jsonify({"error": "Both QC and retail images are required"}), 400

        result = qc_score(qc_image, retail_image)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _num(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None


def _usual_chest(size):
    """Rough body chest (cm) for a stated apparel size — fallback when the user
    doesn't know their measurements."""
    if not size:
        return None
    s = str(size).strip().upper().replace(' ', '')
    return {'XS': 86, 'S': 94, 'M': 102, 'L': 110, 'XL': 118, 'XXL': 126,
            '2XL': 126, '3XL': 134, 'XXXL': 134}.get(s)


def recommend_size(measurements, item_type, size_label, profile):
    """Deterministic fit assessment. We have ONE item's flat measurements (one size),
    so we tell the user how THAT size fits them + whether to size up/down — not the exact
    next size's numbers (that needs a full size chart). Pure arithmetic, explainable."""
    if not profile:
        return None
    fit = (profile.get('fit') or 'regular').lower()

    def g(*names):
        for m in measurements or []:
            n = (m.get('name') or '').lower()
            if any(k in n for k in names) and m.get('value_cm') is not None:
                try:
                    return float(m['value_cm'])
                except Exception:
                    pass
        return None

    it = (item_type or '').lower()

    if 'shoe' in it:
        insole = g('insole', 'inner', 'length')
        foot = _num(profile.get('foot_length'))
        if insole and foot:
            room = insole - foot
            if room < 0.3:
                v, a = 'too small', 'size up'
            elif room < 0.6:
                v, a = 'snug', 'consider sizing up'
            elif room <= 1.5:
                v, a = 'good fit', 'true to size'
            elif room <= 2.2:
                v, a = 'a bit roomy', 'true to size or size down'
            else:
                v, a = 'too big', 'size down'
            return {'verdict': v, 'advice': a, 'tagged_size': size_label,
                    'detail': f'Insole {insole:.0f}cm vs your foot {foot:.0f}cm = {room:.1f}cm toe room (ideal ~0.7-1.2cm).'}
        return {'verdict': 'need foot length', 'advice': 'enter your foot length (cm)', 'tagged_size': size_label, 'detail': ''}

    if it in ('top', 'jacket', 'hoodie') or g('chest', 'pit'):
        chest_flat = g('chest', 'pit')
        body = _num(profile.get('chest')) or _usual_chest(profile.get('usual_size'))
        if chest_flat and body:
            garment = chest_flat * 2
            ease = garment - body
            bands = {'slim': (4, 11), 'regular': (11, 19), 'relaxed': (19, 30)}
            lo, hi = bands.get(fit, bands['regular'])
            if ease < 2:
                v, a = 'too tight', 'size up'
            elif ease < lo:
                v, a = 'snug', 'size up for your preferred fit'
            elif ease <= hi:
                v, a = 'good fit', 'true to size'
            elif ease <= hi + 8:
                v, a = 'relaxed / loose', 'true to size, or size down for a closer fit'
            else:
                v, a = 'oversized', 'size down'
            return {'verdict': v, 'advice': a, 'tagged_size': size_label,
                    'detail': f'Garment chest ~{garment:.0f}cm vs your {body:.0f}cm = {ease:.0f}cm ease ({fit} target {lo}-{hi}cm).'}
        return {'verdict': 'need chest', 'advice': 'enter your chest (cm) or usual size', 'tagged_size': size_label, 'detail': ''}

    if it in ('bottom', 'jeans', 'pants', 'shorts') or g('waist'):
        waist_flat = g('waist')
        body = _num(profile.get('waist'))
        if waist_flat and body:
            garment = waist_flat * 2
            ease = garment - body
            if ease < -1:
                v, a = 'too tight', 'size up'
            elif ease < 2:
                v, a = 'snug (ok if it has stretch)', 'true to size or size up'
            elif ease <= 8:
                v, a = 'good fit', 'true to size'
            elif ease <= 14:
                v, a = 'loose', 'true to size or size down'
            else:
                v, a = 'too big', 'size down'
            return {'verdict': v, 'advice': a, 'tagged_size': size_label,
                    'detail': f'Garment waist ~{garment:.0f}cm vs your {body:.0f}cm = {ease:.0f}cm ease.'}
        return {'verdict': 'need waist', 'advice': 'enter your waist (cm)', 'tagged_size': size_label, 'detail': ''}

    return None


def _est_from_hw(height, weight):
    """Rough body chest/waist (cm) from height(cm)+weight(kg). Approximate — low confidence."""
    h, w = _num(height), _num(weight)
    if not h or not w:
        return None, None
    return round(0.62 * w + 0.30 * h + 7), round(0.50 * w + 0.27 * h - 8)


def _usual_waist(size):
    if not size:
        return None
    s = str(size).strip().upper().replace(' ', '')
    if s.isdigit():
        n = int(s)
        if 22 <= n <= 50:      # inch waist size (28/30/32/34...) -> cm
            return round(n * 2.54)
        if 55 <= n <= 120:     # already a cm waist label
            return n
        return None
    return {'XS': 68, 'S': 74, 'M': 80, 'L': 86, 'XL': 94, 'XXL': 102, '2XL': 102, '3XL': 110}.get(s)


def estimate_body(profile):
    """Best chest/waist for the user, by accuracy: measurements > usual size > height/weight."""
    chest, waist = _num(profile.get('chest')), _num(profile.get('waist'))
    if chest is None and waist is None:
        uc, uw = _usual_chest(profile.get('usual_size')), _usual_waist(profile.get('usual_size'))
        if uc or uw:
            return {'chest': uc, 'waist': uw, 'source': 'usual size', 'confidence': 'medium'}
        ec, ew = _est_from_hw(profile.get('height'), profile.get('weight'))
        return {'chest': ec, 'waist': ew, 'source': 'height/weight estimate', 'confidence': 'low'}
    return {'chest': chest, 'waist': waist, 'source': 'your measurements', 'confidence': 'high'}


def _fit_label(ease):
    if ease is None:
        return None
    if ease < 2:
        return 'tight'
    if ease < 8:
        return 'fitted'
    if ease < 16:
        return 'regular'
    if ease < 24:
        return 'relaxed'
    return 'oversized'


def fit_breakdown(chart, profile):
    """How each charted size fits THIS user — garment-type-aware ease + height/weight band,
    with oversized-cut detection, a confidence score, and plain-language reasons."""
    sizes = (chart or {}).get('sizes') or []
    if not sizes:
        return None
    it = (chart.get('item_type') or '').lower()
    body = estimate_body(profile)
    uh, uw = _num(profile.get('height')), _num(profile.get('weight'))
    fit_pref = (profile.get('fit') or 'regular').lower()
    # Decide top vs bottom robustly: from the item-type label (broad keyword list) AND
    # from the chart data — a chart that lists a waist but no chest is a bottom whatever
    # the label says (read_size_chart sometimes returns 'other'/'trousers'/etc. for pants).
    _bottom_words = ('bottom', 'jean', 'pant', 'trouser', 'short', 'cargo', 'chino',
                     'jogger', 'sweatpant', 'legging', 'slack', 'capri', 'culotte')
    _has_waist = any(_num(s.get('waist')) for s in sizes)
    _has_chest = any(_num(s.get('chest')) for s in sizes)
    is_bottom = any(w in it for w in _bottom_words) or (_has_waist and not _has_chest)
    user_dim = body['waist'] if is_bottom else body['chest']
    body_chart = chart.get('value_type') == 'body_recommended'

    # Garment-type ease-target bands (cm of garment ease over the body dimension).
    if is_bottom:
        bands = {'slim': (0, 3), 'regular': (3, 9), 'relaxed': (9, 16)}
    elif it in ('jacket', 'hoodie', 'coat', 'outerwear', 'sweater'):
        bands = {'slim': (10, 18), 'regular': (18, 28), 'relaxed': (28, 40)}
    else:  # tops / tee / shirt / default
        bands = {'slim': (4, 12), 'regular': (12, 20), 'relaxed': (20, 32)}
    lo, hi = bands.get(fit_pref, bands['regular'])
    target = (lo + hi) / 2.0

    per, eases = [], []
    for s in sizes:
        hmin, hmax = _num(s.get('height_min')), _num(s.get('height_max'))
        wmin, wmax = _num(s.get('weight_min')), _num(s.get('weight_max'))
        hmatch = None
        if uh and (hmin or hmax):
            hmatch = 'in' if (hmin or 0) - 2 <= uh <= (hmax or 999) + 2 else ('below' if uh < (hmin or 0) else 'above')
        wmatch = None
        if uw and (wmin or wmax):
            wmatch = 'in' if (wmin or 0) - 3 <= uw <= (wmax or 999) + 3 else ('below' if uw < (wmin or 0) else 'above')
        g_raw = _num(s.get('waist')) if is_bottom else _num(s.get('chest'))
        # Charts list chest/waist as either the garment CIRCUMFERENCE or the FLAT
        # (pit-to-pit / half-circumference) value. A wearable garment's circumference
        # can't sit well below the body, so if g is < ~0.8x the body dimension it must
        # be a flat/half measurement — double it so ease is computed like-for-like.
        g = g_raw
        flat_doubled = False
        if g_raw is not None and user_dim and not body_chart and g_raw < user_dim * 0.8:
            g = g_raw * 2
            flat_doubled = True
        ease = (g - user_dim) if (g is not None and user_dim) else None
        if ease is not None:
            eases.append(ease)
        per.append({'size': s.get('size') or '?', 'fit': None,
                    'ease': (round(ease) if ease is not None else None), '_ease': ease, '_g': g,
                    'height_match': hmatch, 'weight_match': wmatch, 'flat_doubled': flat_doubled,
                    'garment_circ_cm': (round(g) if (g is not None and flat_doubled) else None),
                    'chest': _num(s.get('chest')), 'waist': _num(s.get('waist')), 'length': _num(s.get('length'))})

    # Oversized/boxy cut: even the smallest size sits well past 'relaxed' over the body.
    oversized = bool(eases) and not body_chart and not is_bottom and min(eases) > hi + 6

    for p in per:
        e = p['_ease']
        if body_chart and e is not None:
            p['fit'] = 'your size' if abs(e) <= 3 else ('roomy' if e > 3 else 'snug')
        elif e is None:
            p['fit'] = None
        elif is_bottom:
            p['fit'] = ('too tight' if e < lo - 2 else 'snug' if e < lo else 'true to size' if e <= hi else 'loose' if e <= hi + 6 else 'oversized')
        else:
            p['fit'] = ('tight' if e < lo - 3 else 'snug' if e < lo else 'true to size' if e <= hi else 'relaxed' if e <= hi + 8 else 'oversized')

    # Recommended size: prefer height/weight band matches, then the ease closest to the target.
    both_in = [p for p in per if p['height_match'] == 'in' and p['weight_match'] == 'in']
    hw_in = [p for p in per if p['height_match'] == 'in' or p['weight_match'] == 'in']
    cand = both_in or hw_in or per
    eased = [p for p in cand if p['_ease'] is not None]
    rec = None
    if eased:
        rec = min(eased, key=lambda p: abs(p['_ease'] - target))['size']
    elif both_in:
        rec = both_in[len(both_in) // 2]['size']
    elif body_chart:
        z = [p for p in per if p['_ease'] is not None]
        if z:
            rec = min(z, key=lambda p: abs(p['_ease']))['size']

    why, conf = [], 0.5
    conf += {'high': 0.25, 'medium': 0.1}.get(body['confidence'], 0.0)
    recp = next((p for p in per if p['size'] == rec), None)
    if recp:
        dim = 'waist' if is_bottom else 'chest'
        if recp['_g'] is not None and user_dim:
            why.append("size %s: garment %s ~%.0fcm vs your %.0fcm body = %+dcm ease (%s target %d–%dcm)" % (
                rec, dim, recp['_g'], user_dim, recp['ease'], fit_pref, lo, hi))
        if recp['height_match'] == 'in' or recp['weight_match'] == 'in':
            why.append("fits the chart's height/weight band for this size"); conf += 0.1
        elif uh or uw:
            why.append("outside the chart's height/weight band — going by measurements")
    if oversized:
        why.append("oversized/boxy cut — the whole size run runs roomy, so this isn't a 'size down' situation")
    if not user_dim:
        why.append("add your chest/waist (or usual size) for a sharper pick")
        conf = min(conf, 0.45)

    for p in per:
        p.pop('_ease', None); p.pop('_g', None)
        p['recommended'] = (p['size'] == rec)
    return {'body_used': body, 'recommended_size': rec, 'per_size': per,
            'value_type': chart.get('value_type'), 'item_type': it,
            'oversized_cut': oversized, 'confidence': min(0.95, round(conf, 2)),
            'fit_pref': fit_pref, 'why': why,
            'ease_target': [lo, hi], 'is_bottom': is_bottom,
            'user_dim': user_dim, 'user_dim_name': ('waist' if is_bottom else 'chest')}


@app.route('/api/size-chart', methods=['POST'])
@_rl("8 per minute;80 per day")
def api_size_chart():
    """[Prototype] Read a seller size chart (upload or image_urls) + per-size fit for the
    user's height/weight/measurements. Returns the chart + a fit breakdown."""
    if not AI_TOOLS_AVAILABLE:
        return jsonify({"error": "AI tools not available on this server"}), 503
    try:
        body = request.get_json(silent=True) or {}
        images = []
        chart_source = None
        if request.files:
            for f in list(request.files.values())[:4]:
                try:
                    images.append(_get_image_from_bytes(f.read()))
                except Exception:
                    pass
        # Auto-fetch from a pasted Weidian (or agent-wrapped Weidian) link: grab the
        # gallery's size-chart slides server-side so the user doesn't have to screenshot.
        if not images:
            link = body.get('link') or request.form.get('link') or ''
            if link.strip():
                wid = weidian_id_from_link(link)
                if not wid:
                    return jsonify({"error": "Auto-fetch currently supports Weidian links only. "
                                             "For Taobao/1688, screenshot the size chart and upload it."}), 400
                cand = weidian_chart_image_urls(wid)
                if not cand:
                    return jsonify({"error": "Couldn't read this Weidian listing's images. "
                                             "Upload the size chart instead."}), 400
                for u in cand:
                    try:
                        images.append(_get_image_from_url(u))
                    except Exception:
                        pass
                chart_source = {"marketplace": "weidian", "item_id": wid, "candidates": cand}
        if not images:
            urls = body.get('image_urls') or []
            if isinstance(urls, str):
                urls = [urls]
            for u in urls[:4]:
                try:
                    images.append(_get_image_from_url(u))
                except Exception:
                    pass
        if not images:
            return jsonify({"error": "Upload a size-chart image, paste a Weidian link, or pass image_urls."}), 400
        profile = dict(body.get('profile')) if isinstance(body.get('profile'), dict) else {}
        for k in ('chest', 'waist', 'hip', 'height', 'weight', 'usual_size'):
            v = request.form.get(k)
            if v not in (None, ''):
                profile[k] = v
        chart = read_size_chart(images)
        if isinstance(chart, dict):
            if chart_source:
                chart['source'] = chart_source
            if chart.get('has_chart') and chart.get('sizes'):
                rec = fit_breakdown(chart, profile)
                if rec:
                    chart['recommendation'] = rec
            elif chart_source and not chart.get('has_chart'):
                # We pulled the listing's gallery but no size chart was embedded in it
                # (common for branded hoodies that point to a Yupoo album).
                chart['note'] = ("This Weidian listing's photos don't include a size chart "
                                 "(some sellers only put it in a Yupoo album). Screenshot the "
                                 "chart and upload it instead.")
        return jsonify(chart)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/measurements')
def measurements_page():
    """Hidden/unlisted prototype: QC-photo measurement reader + size helper.
    Not linked anywhere, noindex, not in sitemap — reachable only by direct URL."""
    return render_template('measurements.html')


@app.route('/api/measure', methods=['POST'])
@_rl("8 per minute;80 per day")
def api_measure():
    """[Prototype] Read garment/shoe measurements from QC photos via GPT-4o vision.
    Accepts JSON {image_urls:[...]} (e.g. from /api/qc) or multipart file uploads."""
    if not AI_TOOLS_AVAILABLE:
        return jsonify({"error": "AI tools not available on this server"}), 503
    try:
        body = request.get_json(silent=True) or {}
        images = []
        if request.files:
            for f in list(request.files.values())[:6]:
                try:
                    images.append(_get_image_from_bytes(f.read()))
                except Exception:
                    pass
        if not images:
            urls = body.get('image_urls') or []
            if isinstance(urls, str):
                urls = [urls]
            for u in urls[:6]:
                try:
                    images.append(_get_image_from_url(u))
                except Exception:
                    pass
        if not images:
            return jsonify({"error": "No readable images. Provide image_urls or upload QC photos."}), 400
        # User profile: JSON 'profile' (link mode) or form fields (upload mode)
        profile = dict(body.get('profile')) if isinstance(body.get('profile'), dict) else {}
        for k in ('chest', 'waist', 'hip', 'height', 'foot_length', 'usual_size', 'fit'):
            v = request.form.get(k)
            if v not in (None, ''):
                profile[k] = v
        result = read_measurements(images)
        if isinstance(result, dict):
            result["images_received"] = len(images)
            if profile and result.get('measurements'):
                rec = recommend_size(result.get('measurements'), result.get('item_type'),
                                     result.get('size_label'), profile)
                if rec:
                    result['recommendation'] = rec
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def recommend_from_qc(items, profile, garment_kind=None):
    """Recommend a size from QC-derived items via the size tags' body spec. Matches the
    RIGHT body dimension for the garment — WAIST for bottoms, CHEST for tops — instead of
    always defaulting to chest (which mis-sized pants). garment_kind comes from estimate_qc;
    if absent we infer it from the items (waist-only data / numeric waist sizes => bottom)."""
    if not items:
        return None
    body = estimate_body(profile)
    uchest = body.get('chest')
    uwaist = body.get('waist')
    uh = _num(profile.get('height'))
    by_size = {}
    for it in items:
        s = it.get('size')
        if s and s not in by_size:
            by_size[s] = it
    # Decide top vs bottom: explicit kind from estimate_qc, else infer from the items.
    if garment_kind not in ('top', 'bottom'):
        has_w = any(_num(it.get('fits_waist_cm')) for it in items)
        has_c = any(_num(it.get('fits_chest_cm')) for it in items)
        nums = [str(it.get('size', '')).strip() for it in items if it.get('size')]
        num_ratio = (sum(1 for s in nums if s.isdigit()) / len(nums)) if nums else 0
        garment_kind = 'bottom' if ((has_w and not has_c) or num_ratio >= 0.5) else 'top'
    is_bottom = garment_kind == 'bottom'
    scored = []
    for s, it in by_size.items():
        # Prefer the QC tag's body spec; fall back to a standard size->body mapping when the tag
        # only gives a size letter/number (bottoms tags often lack a 170/88A-style code).
        fc = _num(it.get('fits_chest_cm')) or _usual_chest(s)
        fw = _num(it.get('fits_waist_cm')) or _usual_waist(s)
        fh = _num(it.get('fits_height_cm'))
        if is_bottom:
            score = abs(fw - uwaist) if (fw and uwaist) else (abs(fh - uh) if (fh and uh) else None)
        else:
            score = abs(fc - uchest) if (fc and uchest) else (abs(fh - uh) if (fh and uh) else None)
        scored.append({'size': s, 'fits_chest_cm': fc, 'fits_waist_cm': fw, 'fits_height_cm': fh,
                       'chest_flat_cm': it.get('chest_flat_cm'), 'confidence': it.get('confidence'),
                       '_score': score})
    valid = [x for x in scored if x['_score'] is not None]
    rec = min(valid, key=lambda x: x['_score'])['size'] if valid else None
    for x in scored:
        x.pop('_score', None)
    return {'recommended_size': rec, 'body_used': body, 'garment_kind': garment_kind,
            'matched_on': ('waist' if is_bottom else 'chest'),
            'sizes': sorted(scored, key=lambda x: str(x['size']))}


@app.route('/api/qc-size', methods=['POST'])
@_rl("6 per minute;60 per day")
def api_qc_size():
    """[Prototype] Full-set QC sizing: read every photo, group by item, pull size + body-fit
    from the tags + best-effort flat-lay measurements, and recommend a size for the profile."""
    if not AI_TOOLS_AVAILABLE:
        return jsonify({"error": "AI tools not available on this server"}), 503
    try:
        body = request.get_json(silent=True) or {}
        urls = body.get('image_urls') or []
        if isinstance(urls, str):
            urls = [urls]
        images = []
        for u in urls[:20]:
            try:
                images.append(_get_image_from_url(u))
            except Exception:
                pass
        if not images:
            return jsonify({"error": "No readable QC images."}), 400
        result = estimate_qc(images)
        profile = dict(body.get('profile')) if isinstance(body.get('profile'), dict) else {}
        if isinstance(result, dict) and result.get('items') and profile:
            rec = recommend_from_qc(result['items'], profile, result.get('garment_kind'))
            if rec:
                result['recommendation'] = rec
        # FUSION: the QC tags tell us which sizes actually SHIP (ground truth), but garment
        # measurement from photos is unreliable. If a Weidian link is available, auto-fetch
        # the seller's size chart (reliable per-size garment measurements) and merge: the
        # chart drives the fit, the QC confirms which of those sizes you'll actually get.
        link = body.get('link') or ''
        if isinstance(result, dict) and link.strip():
            wid = weidian_id_from_link(link)
            if wid:
                try:
                    cand = weidian_chart_image_urls(wid)
                    cimgs = []
                    for u in cand:
                        try:
                            cimgs.append(_get_image_from_url(u))
                        except Exception:
                            pass
                    chart = read_size_chart(cimgs) if cimgs else None
                    if isinstance(chart, dict) and chart.get('has_chart') and chart.get('sizes'):
                        fit = fit_breakdown(chart, profile)
                        qc_sizes = sorted({str(i.get('size')).upper() for i in (result.get('items') or []) if i.get('size')})
                        if fit and fit.get('per_size'):
                            for p in fit['per_size']:
                                p['qc_confirmed'] = str(p.get('size')).upper() in qc_sizes
                        result['chart'] = {k: chart.get(k) for k in ('item_type', 'value_type', 'unit', 'sizes', 'notes')}
                        result['chart_fit'] = fit
                        result['qc_sizes'] = qc_sizes
                        result['chart_source'] = {"marketplace": "weidian", "item_id": wid}
                except Exception:
                    pass
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/visual-search', methods=['POST'])
@_rl("12 per minute;200 per day")
def api_visual_search():
    """Upload an image to find visually similar products."""
    if not AI_TOOLS_AVAILABLE:
        return jsonify({"error": "AI tools not available on this server"}), 503

    try:
        query_image = None

        if 'image' in request.files:
            query_image = _get_image_from_bytes(request.files['image'].read())
        elif request.form.get('image_url'):
            query_image = _get_image_from_url(request.form['image_url'])

        if query_image is None:
            return jsonify({"error": "Image is required"}), 400

        top_k = _safe_int(request.form.get('top_k'), 20)
        result = visual_search(query_image, top_k=min(top_k, 50))
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/ai-index', methods=['POST'])
def api_build_index():
    """Build the product image index for visual search (admin only)."""
    if not session.get('admin'):
        return jsonify({"error": "Admin login required"}), 403
    if not AI_TOOLS_AVAILABLE:
        return jsonify({"error": "AI tools not available"}), 503

    import threading
    json_path = os.path.join('static', 'products.json')
    if not os.path.exists(json_path):
        return jsonify({"error": "products.json not found"}), 404

    def _build():
        build_product_index(json_path)

    t = threading.Thread(target=_build)
    t.start()
    return jsonify({"status": "Indexing started in background"})


@app.route('/api/ai-status')
def api_ai_status():
    """Check AI tools availability and index status."""
    status = {"ai_available": AI_TOOLS_AVAILABLE}
    if AI_TOOLS_AVAILABLE:
        status.update(get_index_status())
    return jsonify(status)





# ===========================================================================
# Cross-site API (used by the master admin) — token auth
# ===========================================================================
ADMIN_API_TOKEN = os.environ.get('ADMIN_API_TOKEN', '')
SITE_NAME = os.environ.get('SITE_NAME', 'RepTools')
AGENT_NAME = os.environ.get('AGENT_NAME', 'KakoBuy')


def _is_admin_api():
    if session.get('admin'):
        return True
    token = request.headers.get('X-Admin-Token') or request.args.get('token')
    return bool(ADMIN_API_TOKEN and token and token == ADMIN_API_TOKEN)


def _flatten_products():
    """rep.tools stores products grouped by category. Flatten for the master."""
    try:
        grouped = db_get_all_products()
    except Exception:
        return []
    flat = []
    if isinstance(grouped, dict):
        for slug, cat in grouped.items():
            if not isinstance(cat, dict):
                continue
            items = cat.get('items') or cat.get('products') or []
            for p in items:
                p = dict(p) if not isinstance(p, dict) else p.copy()
                if not p.get('category'):
                    p['category'] = slug
                flat.append(p)
    elif isinstance(grouped, list):
        flat = grouped
    return flat


@app.route('/admin/img-cache/status')
def admin_img_cache_status():
    """Show disk usage stats for the QC image cache. Admin session required."""
    if not session.get('admin'):
        return redirect('/admin/login')
    total, files = _img_cache_walk()
    return jsonify({
        'total_bytes': total,
        'total_mb': round(total / (1024*1024), 1),
        'cap_mb': IMG_CACHE_MAX_BYTES // (1024*1024),
        'file_count': len(files),
        'cache_dir': IMG_CACHE_DIR,
    })


@app.route('/admin/img-cache/clear', methods=['POST'])
def admin_img_cache_clear():
    """Manually clear the QC image cache. Admin session required.
    POST {} to wipe entirely, or POST {"target_mb": N} to trim to N MB."""
    if not session.get('admin'):
        return jsonify({'error': 'Unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    target_mb = data.get('target_mb')
    if target_mb is None:
        # Full wipe
        total, freed = _img_cache_trim_to(0)
    else:
        target = int(target_mb) * 1024 * 1024
        total, freed = _img_cache_trim_to(target)
    return jsonify({
        'before_mb': round(total / (1024*1024), 1),
        'freed_mb': round(freed / (1024*1024), 1),
        'remaining_mb': round((total - freed) / (1024*1024), 1),
    })


@app.route('/admin/api/ping')
def _api_ping():
    return jsonify({
        'ok': True,
        'site': SITE_NAME,
        'agent': AGENT_NAME,
        'token_required': bool(ADMIN_API_TOKEN),
        'token_valid': _is_admin_api(),
    })


@app.route('/admin/api/stats')
def _api_stats():
    if not _is_admin_api():
        return jsonify({'error': 'Unauthorized'}), 401
    days = _safe_int(request.args.get('days'), 30)
    try:
        s = get_click_stats(days=days)
    except Exception as e:
        s = {'total_clicks': 0, 'unique_visitors': 0, 'top_products': [], 'top_categories': [], 'daily_clicks': []}
    products = _flatten_products()
    # Adapt to the shape the master admin expects
    daily = [{'day': d.get('date'), 'clicks': d.get('clicks', 0), 'visitors': 0} for d in (s.get('daily_clicks') or [])]
    return jsonify({
        'site': SITE_NAME,
        'agent': AGENT_NAME,
        'total_products': len(products),
        'featured_count': 0,
        'categories': len(set(p.get('category') for p in products if p.get('category'))),
        'total_clicks': s.get('total_clicks', 0),
        'unique_visitors': s.get('unique_visitors', 0),
        'signup_clicks': 0,
        'top_products': s.get('top_products', []),
        'top_categories': s.get('top_categories', []),
        'daily': daily,
        'days': days,
    })


@app.route('/admin/api/products')
def _api_products():
    if not _is_admin_api():
        return jsonify({'error': 'Unauthorized'}), 401
    products = _flatten_products()
    return jsonify({'site': SITE_NAME, 'products': products})


@app.route('/admin/api/config')
def _api_config():
    if not _is_admin_api():
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({
        'name': SITE_NAME,
        'agent_name': AGENT_NAME,
        'host': request.host,
    })


# Module-level startup import — runs under gunicorn (not only python app.py)
# Auto-restores catalog if the DB is empty after a fresh persistent disk.
try:
    _count = 0
    _needs_migration = False
    try:
        from database import get_db as _get_db
        with _get_db() as _db:
            _row = _db.execute('SELECT COUNT(*) as c FROM products').fetchone()
            _count = _row['c'] if hasattr(_row, '__getitem__') else _row[0]
            # Detect old un-prefixed product IDs (s1, s2 …) — they need re-migrating
            _ofr = _db.execute("SELECT COUNT(*) as c FROM products WHERE id NOT LIKE '%-%'").fetchone()
            _old_fmt = _ofr['c'] if hasattr(_ofr, '__getitem__') else _ofr[0]
            if _old_fmt > 50:
                print(f'[STARTUP] Detected {_old_fmt} unprefixed product IDs — re-importing with category-prefixed IDs')
                _needs_migration = True
    except Exception:
        _count = 0
    if _count == 0 or _needs_migration:
        _json_path = os.path.join('static', 'products.json')
        if os.path.exists(_json_path):
            print(f'[STARTUP] Importing from {_json_path} ({"migration" if _needs_migration else "empty DB"})')
            _n = import_products_from_json(_json_path)
            print(f'[STARTUP] Imported {_n} products from JSON')
        else:
            try: import_hardcoded_products(PRODUCTS)
            except Exception: pass
    else:
        print(f'[STARTUP] DB has {_count} products — skipping auto-import')
except Exception as _e:
    print(f'[STARTUP] Auto-import error: {_e}')



if __name__ == '__main__':
    # Auto-import products into database on first run
    try:
        json_path = os.path.join('static', 'products.json')
        if os.path.exists(json_path):
            import_products_from_json(json_path)
        else:
            import_hardcoded_products(PRODUCTS)
    except Exception as e:
        print(f"[STARTUP] Product import error: {e}")

    app.run(debug=True, port=5000)
