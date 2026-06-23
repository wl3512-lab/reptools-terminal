"""
AI Tools for RepTools — QC Scorer using GPT-4o Vision & Visual W2C
"""

import os
import re
import json
import base64
import socket
import ipaddress
import numpy as np
from PIL import Image, ImageFilter
from io import BytesIO
from urllib.parse import urlparse, urljoin
import requests as http_requests

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# Sizing model — defaults to OpenRouter + Gemini Flash-lite (cheap, crypto-payable) when
# OPENROUTER_API_KEY is set, else falls back to OpenAI. Configurable via env.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SIZING_API_KEY = OPENROUTER_API_KEY or OPENAI_API_KEY
SIZING_API_BASE = (os.environ.get("SIZING_API_BASE") or
                   ("https://openrouter.ai/api/v1" if OPENROUTER_API_KEY else "https://api.openai.com/v1"))
SIZING_MODEL = (os.environ.get("SIZING_MODEL") or
                ("google/gemini-2.5-flash-lite" if OPENROUTER_API_KEY else "gpt-4o"))


def _sizing_chat(content, max_tokens=1600, temperature=0.0):
    """Chat-completions call to the configured sizing model (OpenAI-compatible).
    temperature defaults to 0 so reads are deterministic and consistent run-to-run."""
    resp = http_requests.post(
        SIZING_API_BASE.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {SIZING_API_KEY}", "Content-Type": "application/json",
                 "HTTP-Referer": "https://rep.tools", "X-Title": "RepTools Sizing"},
        json={"model": SIZING_MODEL, "messages": [{"role": "user", "content": content}],
              "max_tokens": max_tokens, "temperature": temperature},
        timeout=120,
    )
    resp.raise_for_status()
    t = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.endswith("```"):
            t = t[:-3]
    return json.loads(t.strip())


_QC_CATALOG_PROMPT = (
    "You are given the FULL QC photo set (indices 0..__LAST__) of ONE garment product that may come in "
    "MULTIPLE colors and sizes, each shot on a printed cm ruler mat. Catalog EVERY image. For each image i give: "
    "type = flatlay | folded | size_tag | tape_measure | detail | other; color (short, e.g. 'blue'); and depending on type: "
    "- size_tag: tags often list several systems (China 中国码 / US / KR / AU). read 'size' = the CHINESE size letter "
    "(the S/M/L/XL next to a height/chest code like 170/88A or 180/96A), NOT the US/KR/AU size; from that code read 'height' (170) and 'body_chest' (88). "
    "- flatlay (ONLY if the garment is laid flat, front-up, with the armpit-to-armpit line clearly visible and roughly square to the ruler): "
    "read 'chest_flat' = (cm under the RIGHT armpit) minus (cm under the LEFT armpit), and 'length' = shoulder/collar to hem on the ruler. "
    "A folded / bunched / hem-only / angled shot is type 'folded' (NOT flatlay) - do not measure it. "
    "- tape_measure: read 'chest_flat' or 'length' = the number the tape shows. "
    "Respond ONLY with valid JSON: "
    '{"images":[{"i":0,"type":"flatlay","color":"blue","size":null,"height":null,"body_chest":null,"chest_flat":56,"length":65}]}'
)


def estimate_qc(images, max_images=20):
    """Near-bulletproof QC sizing estimator (garments). Catalogs the full set, groups photos by item
    (color), and per item returns the SIZE + body-fit spec from the size tag (reliable) plus a median
    flat-lay measurement (best-effort) and a confidence rating. Returns {items:[...], photos_analyzed}."""
    import statistics
    from concurrent.futures import ThreadPoolExecutor
    if not SIZING_API_KEY:
        return {"error": "sizing model not configured"}
    if not images:
        return {"error": "no images"}
    imgs = images[:max_images]
    # One read per photo. A photo can be a SIZE TAG, an agent OVERLAY (dimensions burned onto the
    # image = the agent's own tape reading, ~ground truth), and/or a FLAT-LAY. We read printed NUMBERS
    # (the model's strength) and demote free-form pixel estimation to a gated, low-confidence corroborator.
    per_prompt = (
        "This is ONE QC photo of a clothing item or its tag. Read it and respond ONLY with this JSON:\n"
        '{"is_tag":false,"size":null,"height":null,"body_chest":null,"body_waist":null,'
        '"overlay_present":false,"overlay":{"chest_flat":null,"length":null,"shoulder":null,"sleeve":null,"waist":null,"hip":null,"weight_g":null},'
        '"is_flatlay":false,"flatlay_square":false,"chest_flat":null}\n'
        "Rules:\n"
        "- SIZE TAG (sewn fabric label): is_tag=true; read the CHINESE size (中国码) as one token "
        "(XS/S/M/L/XL/XXL; normalize SMALL->S, MEDIUM->M, LARGE->L, X-LARGE->XL; keep a numeric waist size as its number). "
        "From a code like 180/96A read height(180) and body_chest(96). For pants/shorts read body_waist in cm. IGNORE US/KR/AU sizes.\n"
        "- OVERLAY TEXT printed/burned ONTO the photo (digits with labels, NOT a sewn tag): overlay_present=true and "
        "transcribe each measured NUMBER into overlay{} in cm (map 胸围/bust->chest_flat, 衣长->length, 肩宽->shoulder, "
        "袖长->sleeve, 腰围->waist, 臀围->hip, 重量/g->weight_g). Only fill numbers you actually SEE printed; otherwise null. Do NOT invent an overlay.\n"
        "- FLAT-LAY (garment laid flat, front-up, armpit-to-armpit visible): is_flatlay=true. Set flatlay_square=true ONLY if the "
        "chest line is parallel to a readable ruler and the garment is not folded/bunched/angled. If flatlay_square, read "
        "chest_flat = (cm under the RIGHT armpit) - (cm under the LEFT armpit); otherwise leave chest_flat null."
    )

    def _read_one(im):
        try:
            b = _image_to_base64(im, max_size=1500)
            c = [{"type": "text", "text": per_prompt},
                 {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "high"}}]
            r = _sizing_chat(c, max_tokens=320)
            return r if isinstance(r, dict) else {}
        except Exception:
            return {}

    try:
        with ThreadPoolExecutor(max_workers=min(8, len(imgs))) as ex:
            reads = list(ex.map(_read_one, imgs))
    except Exception as e:
        return {"error": f"read failed: {e}"}

    def _norm_size(v):
        x = str(v).upper().strip().replace(" ", "").replace("-", "")
        return {"XSMALL": "XS", "SMALL": "S", "MEDIUM": "M", "LARGE": "L",
                "XLARGE": "XL", "EXTRALARGE": "XL", "XXLARGE": "XXL"}.get(x, x)

    def _robust_median(xs):
        xs = [x for x in xs if isinstance(x, (int, float))]
        if not xs:
            return None
        if len(xs) < 3:
            return round(statistics.median(xs), 1)
        med = statistics.median(xs)
        mad = statistics.median([abs(x - med) for x in xs]) or 1.0
        keep = [x for x in xs if abs(x - med) <= 3 * mad]  # drop outliers
        return round(statistics.median(keep or xs), 1)

    OV_KEYS = ("chest_flat", "length", "shoulder", "sleeve", "waist", "hip")
    sizes = {}
    flat_chests = []            # low-confidence: clean-flatlay pixel reads only
    overlay = {k: [] for k in OV_KEYS}   # high-confidence: agent-printed dimensions
    weights = []
    tags_read = overlays_read = flatlays_used = 0
    for r in reads:
        if not isinstance(r, dict):
            continue
        if r.get("is_tag") and r.get("size") is not None:
            tags_read += 1
            d = sizes.setdefault(_norm_size(r.get("size")), {"heights": [], "chests": [], "waists": [], "n": 0})
            d["n"] += 1
            for src, dst in (("height", "heights"), ("body_chest", "chests"), ("body_waist", "waists")):
                v = r.get(src)
                if isinstance(v, (int, float)) and v > 0:
                    d[dst].append(v)
        if r.get("overlay_present") and isinstance(r.get("overlay"), dict):
            got = False
            for k in OV_KEYS:
                v = r["overlay"].get(k)
                if isinstance(v, (int, float)) and 15 < v < 200:   # sane garment-cm range
                    overlay[k].append(v); got = True
            w = r["overlay"].get("weight_g")
            if isinstance(w, (int, float)) and w > 0:
                weights.append(w)
            if got:
                overlays_read += 1
        if r.get("is_flatlay") and r.get("flatlay_square") and isinstance(r.get("chest_flat"), (int, float)):
            if 25 < r["chest_flat"] < 120:
                flat_chests.append(r["chest_flat"]); flatlays_used += 1

    order = {"XS": 0, "S": 1, "M": 2, "L": 3, "XL": 4, "XXL": 5, "2XL": 5, "XXXL": 6, "3XL": 6}
    # De-noise tag reads: with temperature=0 each photo reads deterministically, so drop the
    # remaining clear misreads — implausible numerics (between brand<=8 and waist>=24) and lone
    # cross-system singletons (e.g. a single 'M' read among many numeric tags).
    def _isnum(s):
        return str(s).isdigit()
    tot_num = sum(d["n"] for s, d in sizes.items() if _isnum(s))
    tot_let = sum(d["n"] for s, d in sizes.items() if not _isnum(s))
    dom = "num" if tot_num > tot_let else ("let" if tot_let > tot_num else None)
    items = []
    for s, d in sizes.items():
        n = d.get("n", 1)
        if _isnum(s) and 9 <= int(s) <= 23:
            continue
        if n == 1 and dom and ((_isnum(s) and dom == "let") or (not _isnum(s) and dom == "num")):
            continue
        items.append({"size": s, "reads": n,
                      "fits_height_cm": (statistics.median(d["heights"]) if d["heights"] else None),
                      "fits_chest_cm": (statistics.median(d["chests"]) if d["chests"] else None),
                      "fits_waist_cm": (statistics.median(d["waists"]) if d["waists"] else None),
                      "chest_flat_cm": None, "confidence": "high" if n >= 2 else "low"})
    items.sort(key=lambda x: order.get(str(x["size"]).upper(), 9))

    # Garment flat measurement: trust agent-printed dimensions; fall back to clean flat-lay estimate; else none.
    overlay_chest = _robust_median(overlay["chest_flat"])
    rough_chest = _robust_median(flat_chests)
    if overlay_chest is not None:
        chest_flat, meas_src, meas_conf = overlay_chest, "agent-printed", "high"
    elif rough_chest is not None:
        chest_flat, meas_src, meas_conf = rough_chest, "photo-estimate", "rough"
    else:
        chest_flat, meas_src, meas_conf = None, None, None

    measured = {"chest_flat_cm": chest_flat,
                "length_cm": _robust_median(overlay["length"]),
                "shoulder_cm": _robust_median(overlay["shoulder"]),
                "sleeve_cm": _robust_median(overlay["sleeve"]),
                "waist_cm": _robust_median(overlay["waist"]),
                "hip_cm": _robust_median(overlay["hip"]),
                "weight_g": _robust_median(weights),
                "source": meas_src, "confidence": meas_conf}
    measurable = chest_flat is not None or any(v is not None for k, v in measured.items()
                                               if k.endswith("_cm") and k != "chest_flat_cm")
    note = None if measurable else (
        "We read the size tag(s) reliably, but these QC photos don't allow a garment measurement "
        "(no agent-printed dimensions and no clean flat-lay-next-to-a-ruler shot). For exact cm, upload a "
        "photo of the item laid flat beside a ruler.")
    # Garment kind: bottoms read a body-waist tag / waist+hip overlay / numeric (waist) sizes;
    # tops read body-chest + chest/shoulder/sleeve. Used so the recommender matches the RIGHT
    # body dimension (waist for pants, chest for tops) instead of defaulting to chest.
    _waist_tag = any(d.get("waists") for d in sizes.values())
    _chest_tag = any(d.get("chests") for d in sizes.values())
    _ov_bottom = bool(overlay.get("waist") or overlay.get("hip"))
    _ov_top = bool(overlay.get("chest_flat") or overlay.get("shoulder") or overlay.get("sleeve"))
    _numeric_sizes = sum(1 for s in sizes if str(s).strip().isdigit())
    if _waist_tag and not _chest_tag:
        garment_kind = "bottom"
    elif _chest_tag and not _waist_tag:
        garment_kind = "top"
    elif _ov_bottom and not _ov_top:
        garment_kind = "bottom"
    elif _ov_top and not _ov_bottom:
        garment_kind = "top"
    elif sizes and _numeric_sizes >= max(1, len(sizes) / 2.0):
        garment_kind = "bottom"   # numeric sizes (30/32/34) are waist sizes
    else:
        garment_kind = "top"
    return {"items": items, "photos_analyzed": len(imgs), "garment_kind": garment_kind,
            "tags_read": tags_read, "overlays_read": overlays_read, "flatlays_used": flatlays_used,
            "measured": measured, "measurable": measurable, "measurement_note": note,
            "garment_chest_flat_samples": sorted(flat_chests)}

def _is_safe_public_url(url):
    """True only for http(s) URLs that resolve to a publicly-routable host.
    Blocks SSRF to loopback / private / link-local / reserved ranges."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme not in ("http", "https") or not p.hostname:
        return False
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except Exception:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local or
                addr.is_reserved or addr.is_multicast or addr.is_unspecified):
            return False
        # CGNAT (RFC 6598) — not flagged by stdlib is_private
        if addr.version == 4 and addr in ipaddress.ip_network("100.64.0.0/10"):
            return False
    return True


def _get_image_from_url(url, timeout=10, max_bytes=10 * 1024 * 1024, max_redirects=3):
    """Fetch an image URL with SSRF protection: validate every hop, no auto-redirect,
    require an image content-type, and cap the body size."""
    for _ in range(max_redirects + 1):
        if not _is_safe_public_url(url):
            raise ValueError("blocked or invalid URL")
        resp = http_requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"},
                                 allow_redirects=False, stream=True)
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("Location"):
            nxt = urljoin(url, resp.headers["Location"])
            resp.close()
            url = nxt
            continue
        resp.raise_for_status()
        ctype = (resp.headers.get("Content-Type") or "").lower()
        # Soft gate: many rep CDNs mislabel images as octet-stream/binary — let PIL be
        # the real arbiter. Only reject obvious non-images (html / text / json).
        if ctype.startswith(("text/", "application/json")):
            resp.close()
            raise ValueError("not an image")
        chunks, total = [], 0
        for chunk in resp.iter_content(8192):
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                resp.close()
                raise ValueError("image too large")
        return Image.open(BytesIO(b"".join(chunks))).convert("RGB")
    raise ValueError("too many redirects")


def _get_image_from_bytes(data):
    return Image.open(BytesIO(data)).convert("RGB")


def _image_to_base64(img, max_size=512):
    """Resize and convert PIL Image to base64 for API."""
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def read_measurements(images, max_images=6):
    """Read flat garment / shoe measurements from rep QC photos using GPT-4o Vision.

    Rep QC photos are usually shot on a mat with a printed centimetre ruler on the edges;
    some include a tape measure laid on the item or a printed measurement sheet. `images`
    is a list of PIL Images. Returns structured measurements + confidence, or {"error": ...}.
    """
    if not OPENAI_API_KEY:
        return {"error": "OpenAI API key not configured"}
    if not images:
        return {"error": "no images provided"}

    imgs = images[:max_images]
    # Higher resolution than qc_score's 512px — ruler ticks / printed digits need legibility.
    imgs_b64 = [_image_to_base64(im, max_size=1400) for im in imgs]

    prompt = (
        "You are a measurement-extraction expert for replica-fashion QC photos. You are shown "
        "several QC photos of ONE item (a garment or a pair of shoes). These photos are usually "
        "taken on a mat with a printed CENTIMETRE ruler along the edges; some may also include a "
        "tape measure laid on the item or a printed measurement sheet.\n\n"
        "Steps:\n"
        "1. Across ALL images, pick the one(s) where the item is laid FLAT and roughly square to "
        "the ruler. Folded, stacked, or steeply angled shots CANNOT be measured - ignore them.\n"
        "2. Using the printed ruler / tape / sheet as the scale, measure the item's key FLAT "
        "measurements in centimetres:\n"
        "   - tops/jackets: shoulder (seam-seam), chest/pit-to-pit (flat), length (high point to "
        "hem), sleeve.\n"
        "   - bottoms/jeans: waist (flat, side-side), hip, inseam, outseam/total length, thigh, "
        "leg opening.\n"
        "   - shoes: insole/inner length (and outsole length if shown).\n"
        "3. If a printed measurement SHEET or tape-measure number is visible, READ it directly "
        "(more reliable than estimating against the mat ruler).\n"
        "4. Give each measurement a confidence 0-1. If no flat/measurable shot exists, set "
        "measurable=false and return an empty measurements list.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        "{\n"
        '  "item_type": "top|bottom|jeans|jacket|shoes|other",\n'
        '  "measurable": true,\n'
        '  "best_image_index": 0,\n'
        '  "unit": "cm",\n'
        '  "measurements": [ {"name": "chest_flat", "value_cm": 56, "confidence": 0.7, "source": "mat_ruler|tape|sheet"} ],\n'
        '  "size_label": null,\n'
        '  "notes": "what you measured from + caveats (angle/folded/occluded)"\n'
        "}"
    )

    content = [{"type": "text", "text": prompt}]
    for i, b in enumerate(imgs_b64):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "high"}})

    try:
        resp = http_requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": content}],
                  "max_tokens": 800, "temperature": 0.2},
            timeout=90,
        )
        resp.raise_for_status()
        out = resp.json()["choices"][0]["message"]["content"].strip()
        if out.startswith("```"):
            out = out.split("\n", 1)[1] if "\n" in out else out[3:]
            if out.endswith("```"):
                out = out[:-3]
            out = out.strip()
        result = json.loads(out)
        result["_images_analyzed"] = len(imgs_b64)
        return result
    except Exception as e:
        return {"error": f"measurement read failed: {e}"}


def read_size_chart(images, max_images=4):
    """Read a seller size chart (尺码表) image into structured per-size data using GPT-4o.

    Chinese rep charts usually list, per size, a recommended 身高/体重 (height/weight)
    range AND/OR garment flat measurements (胸围 chest, 衣长 length, 肩宽 shoulder,
    袖长 sleeve, 腰围 waist, 臀围 hip). Returns both when present. `images` = PIL list.
    """
    if not OPENAI_API_KEY:
        return {"error": "OpenAI API key not configured"}
    if not images:
        return {"error": "no images provided"}

    imgs_b64 = [_image_to_base64(im, max_size=1500) for im in images[:max_images]]
    prompt = (
        "You are reading a clothing/shoe SIZE CHART (often a Chinese 尺码表) from the image(s). "
        "Extract it into structured JSON. Charts may give, per size: a recommended height range "
        "(身高, cm), a recommended weight range (体重, kg/jin - convert 斤 to kg by /2), and/or "
        "garment FLAT measurements - chest/bust (胸围), length (衣长), shoulder (肩宽), sleeve "
        "(袖长), waist (腰围), hip (臀围), or shoe inner length.\n\n"
        "Rules:\n"
        "- If a value is a range, give min and max. If single, put it in both.\n"
        "- value_type = 'garment_flat' if the chest/length numbers are the garment laid flat, "
        "'body_recommended' if they are suggested BODY measurements, else 'mixed'.\n"
        "- If weight looks like 斤 (jin, i.e. numbers ~120-200 for an adult), convert to kg (/2).\n"
        "- If there is no readable size chart in the images, set has_chart=false.\n\n"
        "Respond ONLY with valid JSON, no other text:\n"
        "{\n"
        '  "has_chart": true,\n'
        '  "item_type": "top|bottom|jeans|jacket|shoes|other",\n'
        '  "unit": "cm",\n'
        '  "value_type": "garment_flat|body_recommended|mixed",\n'
        '  "sizes": [\n'
        '    {"size":"M","height_min":170,"height_max":175,"weight_min":60,"weight_max":70,'
        '"chest":108,"length":70,"shoulder":45,"sleeve":60,"waist":null,"hip":null}\n'
        "  ],\n"
        '  "notes": "anything ambiguous, e.g. chart was body vs flat, jin->kg conversion, low legibility"\n'
        "}"
    )
    content = [{"type": "text", "text": prompt}]
    for i, b in enumerate(imgs_b64):
        content.append({"type": "text", "text": f"Image {i}:"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}", "detail": "high"}})

    try:
        resp = http_requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": content}],
                  "max_tokens": 1100, "temperature": 0.1},
            timeout=90,
        )
        resp.raise_for_status()
        out = resp.json()["choices"][0]["message"]["content"].strip()
        if out.startswith("```"):
            out = out.split("\n", 1)[1] if "\n" in out else out[3:]
            if out.endswith("```"):
                out = out[:-3]
            out = out.strip()
        return json.loads(out)
    except Exception as e:
        return {"error": f"size-chart read failed: {e}"}


def weidian_chart_image_urls(item_id, top_n=3):
    """Fetch a Weidian item's gallery via the public getItemInfo API (no login, no ban risk)
    and return the most size-chart-like image URLs. Weidian sellers almost always embed the
    尺码表 as one of the gallery slides; it's the WIDE/landscape image (dimensions are encoded
    in the geilicdn filename, so we rank by aspect ratio without downloading) and tends to sit
    near the end of the gallery. Returns [] if the item has no gallery or the API fails."""
    import urllib.parse
    iid = re.sub(r"\D", "", str(item_id or ""))
    if not iid:
        return []
    param = urllib.parse.quote(json.dumps({"vitemId": iid}, separators=(",", ":")))
    url = f"https://thor.weidian.com/detail/getItemInfo/1.0?param={param}"
    try:
        resp = http_requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://weidian.com/",
        }, timeout=12)
        resp.raise_for_status()
        info = ((((resp.json() or {}).get("result") or {}).get("default_model") or {}).get("item_info") or {})
        imgs = info.get("imgs") or []
    except Exception:
        return []
    scored, n = [], len(imgs)
    for i, u in enumerate(imgs):
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        u = u.split("?")[0]  # bare CDN URL = original resolution
        m = re.search(r"_(\d{2,4})_(\d{2,4})\.(?:jpg|jpeg|png)", u)
        w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        ar = (w / h) if h else 1.0
        # charts are landscape; also bias to the last few slides where they usually sit
        score = ar + (0.3 if i >= n - 3 else 0.0)
        scored.append((score, ar, i, u))
    if not scored:
        return []
    wide = [s for s in scored if s[1] >= 1.3]   # plausibly-landscape candidates
    pool = sorted(wide or scored, reverse=True)
    seen, out = set(), []
    for _, _, _, u in pool:
        if u not in seen:
            seen.add(u); out.append(u)
        if len(out) >= top_n:
            break
    return out


def weidian_id_from_link(link):
    """Pull a Weidian itemID out of a pasted link (a weidian.com URL, an agent link that
    wraps a weidian item, or a bare id). Returns the id string or None for non-weidian links."""
    s = (link or "").strip()
    if re.fullmatch(r"\d{8,}", s):
        return s
    low = s.lower()
    m = re.search(r"item(?:id)?=(\d{6,})", low)
    if m and ("weidian" in low or "item.html" in low):
        return m.group(1)
    if "weidian" in low:   # agent link carrying a weidian item (platform/shop_type=weidian)
        m = re.search(r"[?&](?:id|itemid|goodsid|productid|spuid)=(\d{6,})", low)
        if m:
            return m.group(1)
        m = re.search(r"/(\d{8,})(?:[/?&]|$)", s)
        if m:
            return m.group(1)
    return None


def qc_score(qc_image, retail_image):
    """Compare QC photo vs retail using GPT-4o Vision."""
    if not OPENAI_API_KEY:
        return {"error": "OpenAI API key not configured"}

    qc_b64 = _image_to_base64(qc_image)
    retail_b64 = _image_to_base64(retail_image)

    prompt = """You are a replica fashion QC (quality control) expert. Compare the QC photo (first image) against the retail reference photo (second image).

Analyze these specific areas and give each a score from 0-100:
1. **Overall Shape/Silhouette** - Does the overall shape match retail?
2. **Color Accuracy** - Do the colors match?
3. **Logo/Branding** - Are logos, text, and branding elements accurate?
4. **Stitching/Build Quality** - Does stitching and construction look correct?
5. **Materials/Texture** - Do materials appear similar to retail?
6. **Details** - Small details like tags, lace tips, sole pattern, hardware, etc.

Then give an overall score from 0-100.

Also provide a verdict: "GL" (Green Light - good to ship), "RL" (Red Light - return it), or "Your Call" (borderline).

IMPORTANT: Respond ONLY with valid JSON in this exact format, no other text:
{
    "overall_score": 85,
    "shape": 90,
    "color": 85,
    "logo": 80,
    "stitching": 88,
    "materials": 82,
    "details": 78,
    "verdict": "GL",
    "summary": "Brief 1-2 sentence summary of the comparison",
    "flaws": ["specific flaw 1", "specific flaw 2"]
}"""

    try:
        resp = http_requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{qc_b64}", "detail": "high"}
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{retail_b64}", "detail": "high"}
                            }
                        ]
                    }
                ],
                "max_tokens": 500,
                "temperature": 0.3
            },
            timeout=60
        )

        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]

        # Parse JSON from response (handle markdown code blocks)
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        result = json.loads(content)

        # Build response
        return {
            "overall_score": result.get("overall_score", 0),
            "regions": {
                "shape": {"label": "Shape / Silhouette", "score": result.get("shape", 0)},
                "color": {"label": "Color Accuracy", "score": result.get("color", 0)},
                "logo": {"label": "Logo / Branding", "score": result.get("logo", 0)},
                "stitching": {"label": "Stitching / Build", "score": result.get("stitching", 0)},
                "materials": {"label": "Materials / Texture", "score": result.get("materials", 0)},
                "details": {"label": "Details", "score": result.get("details", 0)},
            },
            "verdict": _format_verdict(result.get("verdict", "?")),
            "summary": result.get("summary", ""),
            "flaws": result.get("flaws", [])
        }

    except http_requests.exceptions.HTTPError as e:
        error_body = e.response.text if e.response else str(e)
        return {"error": f"OpenAI API error: {error_body}"}
    except json.JSONDecodeError:
        return {"error": "Failed to parse AI response"}
    except Exception as e:
        return {"error": str(e)}


def _format_verdict(verdict):
    v = verdict.upper().strip()
    if "GL" in v:
        return "GL (Green Light) — Good to ship"
    elif "RL" in v:
        return "RL (Red Light) — Return it"
    else:
        return "Your Call — Borderline, depends on your standards"


# ===== Visual W2C (lightweight histogram matching) =====

_product_data = None
_product_histograms = None


def _get_color_histogram(img, bins=64):
    img = img.resize((256, 256), Image.LANCZOS)
    hist_r = np.histogram(np.array(img)[:,:,0], bins=bins, range=(0, 256))[0]
    hist_g = np.histogram(np.array(img)[:,:,1], bins=bins, range=(0, 256))[0]
    hist_b = np.histogram(np.array(img)[:,:,2], bins=bins, range=(0, 256))[0]
    hist = np.concatenate([hist_r, hist_g, hist_b]).astype(float)
    norm = np.linalg.norm(hist)
    if norm > 0:
        hist = hist / norm
    return hist


def build_product_index(products_json_path):
    global _product_histograms, _product_data

    print("[AI] Building product image index...")
    with open(products_json_path, 'r', encoding='utf-8') as f:
        products = json.load(f)

    histograms = []
    indexed_products = []
    failed = 0

    for i, product in enumerate(products):
        img_url = product.get("image", "")
        if not img_url:
            failed += 1
            continue
        try:
            img = _get_image_from_url(img_url, timeout=5)
            hist = _get_color_histogram(img)
            histograms.append(hist)
            indexed_products.append(product)
            if (i + 1) % 100 == 0:
                print(f"[AI] Indexed {i+1}/{len(products)} products...")
        except Exception:
            failed += 1
            continue

    if histograms:
        _product_histograms = np.array(histograms)
        _product_data = indexed_products
        _data_dir = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
        np.save(os.path.join(_data_dir, "product_histograms.npy"), _product_histograms)
        with open(os.path.join(_data_dir, "product_index.json"), 'w') as f:
            json.dump(indexed_products, f)
        print(f"[AI] Product index built: {len(indexed_products)} indexed, {failed} failed.")

    return len(indexed_products)


def load_product_index():
    global _product_histograms, _product_data
    _data_dir = "/data" if os.path.isdir("/data") else os.path.dirname(__file__)
    hist_path = os.path.join(_data_dir, "product_histograms.npy")
    idx_path = os.path.join(_data_dir, "product_index.json")

    if os.path.exists(hist_path) and os.path.exists(idx_path):
        _product_histograms = np.load(hist_path)
        with open(idx_path, 'r') as f:
            _product_data = json.load(f)
        print(f"[AI] Loaded product index from disk: {len(_product_data)} products.")
        return True
    return False


def visual_search(query_image, top_k=20):
    if _product_histograms is None or _product_data is None:
        return {"error": "Product index not built yet. An admin needs to build the index first.", "results": []}

    query_hist = _get_color_histogram(query_image)
    similarities = np.dot(_product_histograms, query_hist)
    top_indices = np.argsort(similarities)[::-1][:top_k]

    results = []
    for idx in top_indices:
        sim = float(similarities[idx])
        score = max(0, min(100, sim * 100))
        product = _product_data[idx]
        results.append({
            "name": product.get("name", "Unknown"),
            "price": product.get("price", ""),
            "image": product.get("image", ""),
            "link": product.get("link", ""),
            "similarity": round(score, 1),
            "category": product.get("category", "")
        })

    return {"results": results}


def get_index_status():
    if _product_histograms is not None:
        return {"indexed": True, "count": len(_product_data)}
    return {"indexed": False, "count": 0}
