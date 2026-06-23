"""
RepTools Product Scraper / Bulk Adder
Run locally: python3 scraper_tool.py

Paste Weidian/Taobao URLs, it generates product entries for products.json
"""

import json, re, sys, os
from urllib.parse import urlparse, parse_qs, quote

AFFCODE = "thelude"
CATEGORIES = ["shoes", "jackets", "hoodies", "sweaters", "shirts", "pants", "shorts", "sets", "accessories", "electronics", "home"]

def extract_item_info(url):
    """Extract platform, itemID, and generate KakoBuy link from any URL format."""
    url = url.strip()
    
    platform = None
    item_id = None
    
    # Already a KakoBuy link - extract the inner URL
    if 'kakobuy.com' in url:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        inner = params.get('url', [''])[0]
        if inner:
            url = inner
    
    # Weidian
    if 'weidian.com' in url:
        platform = 'weidian'
        # itemID in query
        match = re.search(r'itemID[=](\d+)', url)
        if match:
            item_id = match.group(1)
    
    # Taobao / Tmall
    elif 'taobao.com' in url or 'tmall.com' in url:
        platform = 'taobao'
        match = re.search(r'[?&]id=(\d+)', url)
        if match:
            item_id = match.group(1)
    
    # 1688
    elif '1688.com' in url:
        platform = '1688'
        match = re.search(r'/offer/(\d+)', url)
        if match:
            item_id = match.group(1)
    
    if not platform or not item_id:
        return None
    
    # Build KakoBuy affiliate link
    if platform == 'weidian':
        source_url = f"https://weidian.com/item.html?itemID={item_id}"
    elif platform == 'taobao':
        source_url = f"https://item.taobao.com/item.htm?id={item_id}"
    elif platform == '1688':
        source_url = f"https://detail.1688.com/offer/{item_id}.html"
    
    kakobuy_link = f"https://www.kakobuy.com/item/details?url={quote(source_url, safe='')}&affcode={AFFCODE}"
    
    return {
        'platform': platform,
        'item_id': item_id,
        'source_url': source_url,
        'kakobuy_link': kakobuy_link,
    }


def generate_product_entry(info, name, price, category, image="", quality_tag="Premium Quality"):
    """Generate a products.json entry."""
    price_num = float(re.sub(r'[^\d.]', '', str(price))) if price else 0
    
    return {
        "id": f"{category[0]}{info['item_id'][-4:]}",
        "name": f"{name} [{quality_tag}]" if quality_tag else name,
        "price": f"${price_num:.2f}",
        "priceNum": price_num,
        "image": image,
        "url": info['kakobuy_link'],
        "category": category,
    }


def interactive_mode():
    """Interactive CLI for adding products one by one."""
    products = []
    
    print("\n" + "="*60)
    print("  RepTools Product Adder")
    print("  Paste URLs to generate products.json entries")
    print("="*60)
    print(f"\nCategories: {', '.join(CATEGORIES)}")
    print("Type 'done' when finished, 'export' to save\n")
    
    while True:
        url = input("\n🔗 Paste URL (or 'done'): ").strip()
        if url.lower() == 'done':
            break
        if url.lower() == 'export':
            export_products(products)
            continue
            
        info = extract_item_info(url)
        if not info:
            print("  ❌ Couldn't parse that URL. Supports Weidian, Taobao, 1688.")
            continue
        
        print(f"  ✅ {info['platform'].upper()} | Item ID: {info['item_id']}")
        print(f"  🛒 KakoBuy: {info['kakobuy_link'][:80]}...")
        
        name = input("  📝 Product name: ").strip()
        price = input("  💰 Price (USD): $").strip()
        
        print(f"  📁 Categories: {', '.join(f'{i+1}.{c}' for i, c in enumerate(CATEGORIES))}")
        cat_input = input("  📁 Category (number or name): ").strip()
        try:
            cat_idx = int(cat_input) - 1
            category = CATEGORIES[cat_idx]
        except (ValueError, IndexError):
            category = cat_input if cat_input in CATEGORIES else "shoes"
        
        image = input("  🖼️  Image URL (optional, Enter to skip): ").strip()
        
        entry = generate_product_entry(info, name, price, category, image)
        products.append(entry)
        print(f"\n  ✅ Added: {entry['name']} | {entry['price']} | {category}")
    
    if products:
        export_products(products)


def bulk_mode(urls_file):
    """Process a file of URLs with tab-separated data:
    URL\tName\tPrice\tCategory\tImage(optional)
    """
    products = []
    
    with open(urls_file, 'r') as f:
        lines = f.readlines()
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        parts = line.split('\t')
        if len(parts) < 4:
            print(f"  ⚠️  Line {i+1}: Need at least URL, Name, Price, Category (tab-separated)")
            continue
        
        url, name, price, category = parts[0], parts[1], parts[2], parts[3]
        image = parts[4] if len(parts) > 4 else ""
        
        info = extract_item_info(url)
        if not info:
            print(f"  ❌ Line {i+1}: Couldn't parse URL: {url[:60]}")
            continue
        
        entry = generate_product_entry(info, name, price, category.strip(), image.strip())
        products.append(entry)
        print(f"  ✅ {info['platform'].upper()} | {name[:40]} | {entry['price']}")
    
    if products:
        export_products(products)


def export_products(products):
    """Export products to JSON file."""
    output_file = "new_products.json"
    with open(output_file, 'w') as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*60}")
    print(f"  ✅ Exported {len(products)} products to {output_file}")
    print(f"{'='*60}")
    
    # Also print for easy copy-paste
    print("\n📋 Copy-paste ready (add to products.json items array):\n")
    for p in products[:5]:
        print(json.dumps(p, indent=2))
    if len(products) > 5:
        print(f"\n  ... and {len(products) - 5} more in {output_file}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        # Bulk mode: python3 scraper_tool.py urls.tsv
        bulk_mode(sys.argv[1])
    else:
        interactive_mode()
