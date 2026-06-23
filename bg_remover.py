"""
RepTools Background Remover
Removes backgrounds from product images for a cleaner look.
Uses rembg (free, runs locally).
"""

import io
import os
import requests
from PIL import Image
from rembg import remove

# Output format settings
OUTPUT_FORMAT = "PNG"  # PNG for transparency


def remove_bg_from_url(image_url: str) -> bytes:
    """Download an image from URL and remove its background. Returns PNG bytes."""
    print(f"[BG] Downloading: {image_url[:80]}...")
    resp = requests.get(image_url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resp.raise_for_status()

    input_bytes = resp.content
    print(f"[BG] Downloaded {len(input_bytes)} bytes, removing background...")

    output_bytes = remove(input_bytes)
    print(f"[BG] Background removed. Output: {len(output_bytes)} bytes")

    return output_bytes


def remove_bg_from_bytes(image_bytes: bytes) -> bytes:
    """Remove background from image bytes. Returns PNG bytes."""
    return remove(image_bytes)


def remove_bg_from_file(input_path: str, output_path: str = None) -> str:
    """Remove background from a local file. Returns output path."""
    if not output_path:
        name, _ = os.path.splitext(input_path)
        output_path = f"{name}_nobg.png"

    with open(input_path, "rb") as f:
        input_bytes = f.read()

    output_bytes = remove(input_bytes)

    with open(output_path, "wb") as f:
        f.write(output_bytes)

    print(f"[BG] Saved: {output_path}")
    return output_path


def process_and_upload(image_url: str) -> str:
    """
    Remove background from a URL image and return a data URI or save locally.
    For production, you'd upload to your image host (postimg.cc, cloudinary, etc.)
    """
    try:
        output_bytes = remove_bg_from_url(image_url)

        # Save locally in static/images/products/
        static_dir = os.path.join(os.path.dirname(__file__), "static", "images", "products")
        os.makedirs(static_dir, exist_ok=True)

        # Generate filename from URL hash
        import hashlib
        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:12]
        filename = f"{url_hash}_nobg.png"
        filepath = os.path.join(static_dir, filename)

        with open(filepath, "wb") as f:
            f.write(output_bytes)

        # Return the local static URL
        return f"/static/images/products/{filename}"

    except Exception as e:
        print(f"[BG] Error processing {image_url}: {e}")
        return image_url  # Return original URL on failure


def bulk_process_products(products_dict: dict) -> dict:
    """
    Process all product images in a products dict, removing backgrounds.
    Returns updated dict with new image URLs.
    """
    processed = 0
    failed = 0

    for cat_slug, cat_data in products_dict.items():
        items = cat_data.get("items", [])
        for item in items:
            image_url = item.get("image", "")
            if not image_url or len(image_url) < 10:
                continue

            # Skip if already processed
            if "_nobg" in image_url or image_url.startswith("/static/images/products/"):
                continue

            try:
                new_url = process_and_upload(image_url)
                item["image_original"] = image_url  # Keep original
                item["image"] = new_url
                processed += 1
                print(f"[BG] [{processed}] {item.get('name', '?')}: done")
            except Exception as e:
                print(f"[BG] Failed: {item.get('name', '?')}: {e}")
                failed += 1

    print(f"\n[BG] Bulk complete: {processed} processed, {failed} failed")
    return products_dict
