"""
RepTools Discord Webhook Module
Auto-posts new finds and analytics to Discord channels.
"""

import os
import json
import requests
from datetime import datetime

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
WEBHOOK_ANALYTICS_URL = os.environ.get("DISCORD_WEBHOOK_ANALYTICS_URL", "")  # Optional separate channel

EMBED_COLOR = 0xC8956C  # Warm accent
SUCCESS_COLOR = 0x7DAA6D
INFO_COLOR = 0x8B6F4E


def send_webhook(webhook_url, payload):
    """Send a Discord webhook message."""
    if not webhook_url:
        print("[WEBHOOK] No webhook URL configured")
        return False

    try:
        headers = {"Content-Type": "application/json"}
        r = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
        if r.status_code in (200, 204):
            print(f"[WEBHOOK] Sent successfully")
            return True
        else:
            print(f"[WEBHOOK] Failed: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        print(f"[WEBHOOK] Error: {e}")
        return False


def notify_new_product(product):
    """Send a Discord notification when a new product is added."""
    if not WEBHOOK_URL:
        return False

    name = product.get("name", "Unknown Product")
    price = product.get("price", "N/A")
    category = product.get("category", "").title()
    image = product.get("image", "")
    url = product.get("url", "")
    seller = product.get("seller", "Various")
    batch = product.get("batch", "")

    description = f"**{price}** • {category}"
    if seller and seller != "Various":
        description += f" • {seller}"
    if batch:
        description += f" • {batch}"

    embed = {
        "title": f"New Find: {name}",
        "description": description,
        "color": EMBED_COLOR,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "RepTools • New Find Added"},
    }

    if image:
        embed["thumbnail"] = {"url": image}

    if url:
        embed["url"] = url
        embed["fields"] = [
            {"name": "Buy Link", "value": f"[View on KakoBuy]({url})", "inline": True}
        ]

    payload = {
        "username": "RepTools",
        "embeds": [embed]
    }

    return send_webhook(WEBHOOK_URL, payload)


def notify_bulk_products(products, category):
    """Send a Discord notification for bulk product additions."""
    if not WEBHOOK_URL:
        return False

    count = len(products)
    sample_names = [p.get("name", "?") for p in products[:5]]
    sample_text = "\n".join([f"• {name}" for name in sample_names])
    if count > 5:
        sample_text += f"\n• ...and {count - 5} more"

    embed = {
        "title": f"{count} New Finds Added to {category.title()}",
        "description": sample_text,
        "color": SUCCESS_COLOR,
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": "RepTools • Bulk Upload"},
    }

    payload = {
        "username": "RepTools",
        "embeds": [embed]
    }

    return send_webhook(WEBHOOK_URL, payload)


def notify_daily_stats(stats):
    """Send daily analytics summary to Discord."""
    webhook = WEBHOOK_ANALYTICS_URL or WEBHOOK_URL
    if not webhook:
        return False

    total = stats.get("total_clicks", 0)
    unique = stats.get("unique_visitors", 0)
    top_products = stats.get("top_products", [])
    top_categories = stats.get("top_categories", [])

    # Top products text
    top_text = ""
    for i, p in enumerate(top_products[:5], 1):
        top_text += f"{i}. **{p['product_name']}** — {p['clicks']} clicks\n"
    if not top_text:
        top_text = "No clicks recorded"

    # Top categories text
    cat_text = ""
    for c in top_categories[:5]:
        cat_text += f"• **{c['category'].title()}** — {c['clicks']} clicks\n"
    if not cat_text:
        cat_text = "No data"

    embed = {
        "title": "Daily Analytics Report",
        "color": INFO_COLOR,
        "fields": [
            {"name": "Total Clicks", "value": str(total), "inline": True},
            {"name": "Unique Visitors", "value": str(unique), "inline": True},
            {"name": "\u200b", "value": "\u200b", "inline": True},
            {"name": "Top Products", "value": top_text, "inline": False},
            {"name": "Top Categories", "value": cat_text, "inline": False},
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "footer": {"text": f"RepTools Analytics • Last {stats.get('period_days', 30)} days"},
    }

    payload = {
        "username": "RepTools Analytics",
        "embeds": [embed]
    }

    return send_webhook(webhook, payload)
