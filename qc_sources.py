# -*- coding: utf-8 -*-
"""Fallback QC-photo sources for when the KakoBuy open API returns no photos.

All sources here are UNAUTHENTICATED and queried SERVER-SIDE only (never the
browser — these APIs are CORS-locked) and never touch the user's own agent
account, so there is zero ban risk. Currently: uufinds (open cross-agent crowd
QC database). Every call is defensive (short timeout, broad except) so a failure
or upstream change can never break /api/qc.
"""
import re
from urllib.parse import urlparse, parse_qs, unquote

try:
    import requests as _rq
except Exception:  # pragma: no cover
    _rq = None

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def extract_marketplace_id(url):
    """(marketplace, item_id) from a source/agent product URL, or (None, None)."""
    if not url:
        return (None, None)
    try:
        p = urlparse(url)
        q = parse_qs(p.query)
        # Unwrap agent ?url=/goodsUrl= wrappers (e.g. kakobuy/item/details?url=...)
        for k in ("url", "goodsUrl", "goods_url", "productUrl"):
            if k in q and q[k]:
                inner = unquote(q[k][0])
                if inner and inner != url:
                    return extract_marketplace_id(inner)
        host = (p.hostname or "").lower()
        if "weidian" in host:
            iid = q.get("itemID") or q.get("itemId") or q.get("id")
            return ("weidian", str(iid[0])) if iid else (None, None)
        if "taobao" in host or "tmall" in host:
            iid = q.get("id")
            return ("taobao", str(iid[0])) if iid else (None, None)
        if "1688" in host:
            m = re.search(r"/offer/(\d+)", p.path)
            return ("1688", m.group(1)) if m else (None, None)
        # Bare agent link carrying itemID/id (+ optional platform hint)
        iid = q.get("itemID") or q.get("id") or q.get("itemId")
        if iid:
            plat = (q.get("platform") or q.get("shop_type") or q.get("channel") or [""])[0].lower()
            mk = "weidian" if ("weidian" in plat or plat == "wd") else ("1688" if "1688" in plat else "taobao")
            return (mk, str(iid[0]))
    except Exception:
        pass
    return (None, None)


def _uu_qc(params, timeout=12):
    if _rq is None:
        return []
    try:
        r = _rq.get("https://api.uufinds.com/user/qc/info/list", params=params,
                    headers={"X-Client-Type": "web", "User-Agent": _UA, "Accept": "application/json"},
                    timeout=timeout)
        j = r.json()
    except Exception:
        return []
    if not isinstance(j, dict):
        return []
    return ((j.get("result") or {}).get("records")) or []


def fetch_uufinds_qc(source_url, timeout=12, limit=40):
    """Query uufinds' open crowd-QC DB by marketplace itemID (spuNo) and return a
    KakoBuy-shaped list [{image_url, product_name, qc_date}] (possibly empty).

    IMPORTANT: query ONLY by spuNo. uufinds' /user/qc/info/list IGNORES a goodsId
    param and returns a GLOBAL recent feed (verified: different + garbage goodsIds
    all return the same records) — so a goodsId chain would surface other products'
    photos. by-spuNo is product-specific (only that itemID's user-uploaded QC).
    Photos live on file.uufinds.com (public, no referer)."""
    _mk, iid = extract_marketplace_id(source_url)
    if not iid:
        return []
    recs = _uu_qc({"spuNo": iid, "pageNo": 1, "pageSize": 40}, timeout)
    out, seen = [], set()
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        # guard: keep only records that actually belong to this itemID
        rsp = rec.get("spuNo")
        if rsp is not None and str(rsp) != str(iid):
            continue
        if str(rec.get("auditStatus") or "Y").upper() not in ("Y", "PASS", "PASSED", "APPROVED", "1", "TRUE"):
            continue
        name = rec.get("subject") or "QC photo"
        date = rec.get("createTime") or ""
        for u in (rec.get("fileUris") or []):
            if isinstance(u, str) and u.startswith("http") and u not in seen:
                seen.add(u)
                out.append({"image_url": u, "product_name": name, "qc_date": date})
                if len(out) >= limit:
                    return out
    return out
