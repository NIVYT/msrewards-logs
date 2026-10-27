import os
import sys
import json
import re
import time
import requests
from datetime import datetime, timezone

# Ensure stdout handles UTF-8 characters on all platforms/terminals
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CATALOG_URL = "https://rewards.bing.com/redeem/in/shop"
CATALOG_URL_FALLBACK = "https://rewards.bing.com/redeem/in"
STATE_FILE = "state.json"

WATCHLIST = [
    "amazon", "flipkart", "croma", "bookmyshow",
    "lifestyle", "myntra", "uber", "pantaloons", "zomato"
]

# High-priority direct redemption SKUs (scanned directly even if unlisted in catalog grid)
DIRECT_SKU_URLS = [
    "https://rewards.bing.com/redeem/sku/000885000034",  # Flipkart Gift Card
    "https://rewards.bing.com/redeem/sku/000885000031",  # Amazon Pay Gift Card India
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

def load_state():
    """Loads previously saved restock state from state.json."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[-] Warning: Failed to read {STATE_FILE}: {e}")
    return {}

def save_state(state):
    """Persists restock state to state.json."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[-] Warning: Failed to save {STATE_FILE}: {e}")

def extract_items_from_html(html_text):
    """
    Extracts Microsoft Rewards catalog and SKU items from Next.js RSC chunks or embedded JSON.
    In Next.js RSC, items are pushed via self.__next_f.push([1, "..."]).
    """
    found_items = []
    decoder = json.JSONDecoder()

    # 1. Search RSC push chunks
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\s*\]\)', html_text)
    for raw in chunks:
        try:
            chunk = raw.encode('utf-8').decode('unicode_escape')
            for match in re.finditer(r'\{[^{}]*"items"\s*:\s*\[', chunk):
                start_idx = match.start()
                try:
                    obj, _ = decoder.raw_decode(chunk[start_idx:])
                    if 'items' in obj and isinstance(obj['items'], list):
                        for it in obj['items']:
                            if isinstance(it, dict) and ('title' in it or 'id' in it):
                                found_items.append(it)
                except Exception:
                    pass
        except Exception:
            pass

    # Deduplicate items by ID and title
    unique_items = []
    seen = set()
    for item in found_items:
        key = item.get('id') or item.get('title')
        if key and key not in seen:
            seen.add(key)
            unique_items.append(item)

    return unique_items

def verify_sku_stock(sku_href, session):
    """
    Fetches the direct SKU redemption page to verify if denominations are in stock.
    Returns (is_in_stock: bool, reason: str, verified_items: list)
    """
    if not sku_href:
        return True, "No SKU link to verify", []

    sku_url = sku_href if sku_href.startswith("http") else f"https://rewards.bing.com{sku_href}"

    try:
        res = session.get(sku_url, headers=HEADERS, timeout=12)
        if res.status_code != 200:
            return False, f"SKU page returned HTTP {res.status_code}", []

        sku_items = extract_items_from_html(res.text)
        if sku_items:
            # Check if any denomination is NOT disabled
            available_denominations = [it for it in sku_items if it.get('isDisabled') is not True]
            if available_denominations:
                return True, f"{len(available_denominations)} denomination(s) available", available_denominations
            else:
                return False, "All denominations on SKU page have isDisabled: True", []

        # Fallback: if no RSC items extracted, check for restocking message
        html_lower = res.text.lower()
        if "restocking! back soon" in html_lower or "so popular we're restocking" in html_lower:
            return False, "SKU page shows 'restocking! back soon'", []

        return True, "SKU page accessible with no disabled indicators", []

    except Exception as e:
        print(f"[-] Warning: Failed to verify SKU page {sku_url}: {e}")
        # Default to False on network error to prevent false-positive spam
        return False, f"Network error checking SKU page: {e}", []

def is_item_in_stock(item, session):
    """
    Evaluates whether a catalog item is truly in stock.
    - If an href (direct SKU redemption link) is available, ALWAYS checks the live SKU page
      because the SKU redemption page reflects real-time inventory faster than the CDN-cached catalog grid.
    - An item is in stock if any denomination has isDisabled != True and no restocking notice.
    """
    href = item.get('href')
    if href:
        in_stock, reason, verified = verify_sku_stock(href, session)
        return in_stock, reason, verified

    # Fallback if no SKU link: check catalog isDisabled property
    if item.get('isDisabled') is True:
        return False, "Catalog item isDisabled: True", []

    return True, "Catalog item enabled (no SKU link)", [item]

def clean_text(text):
    """Sanitizes text and permanently fixes UTF-8 mojibake (e.g. â‚¹ / Â¤¹ -> ₹)."""
    if not text:
        return ""
    try:
        text = text.encode('latin1').decode('utf-8')
    except Exception:
        pass
    text = text.replace('â\x82¹', '₹').replace('â¤¹', '₹').replace('Â¤¹', '₹').replace('â—', '—')
    return text.strip()

def post_alert(card_title, full_title, points, redeem_url, image_url, timestamp):
    """
    Dispatches Design #4: Modern Bento Grid notification.
    Clean, zero AI slop, no emoji spam, Discord relative timestamps, and native 1-tap claim button.
    """
    if not DISCORD_WEBHOOK_URL:
        print("[-] Warning: DISCORD_WEBHOOK_URL secret not set. Skipping webhook notification.")
        return

    clean_full = clean_text(full_title)
    clean_card = clean_text(card_title)
    display_title = clean_full or clean_card or "Flipkart Gift Card"
    points_display = f"{points:,} pts" if isinstance(points, (int, float)) and points > 0 else "See Catalog"
    direct_link = redeem_url if redeem_url else CATALOG_URL
    epoch_now = int(time.time())

    # Extract clean denomination (e.g., ₹1,000)
    denomination = "₹1,000"
    for part in display_title.split():
        if "₹" in part:
            denomination = part
            break
        elif part.isdigit() and int(part) in (250, 500, 1000, 1500, 2000, 5000):
            denomination = f"₹{int(part):,}"
            break

    embed = {
        "title": display_title,
        "url": direct_link,
        "color": 3900150,  # Modern Bento Blue (#3B82F6)
        "fields": [
            {"name": "Denomination", "value": f"`{denomination}`", "inline": True},
            {"name": "Points", "value": f"`{points_display}`", "inline": True},
            {"name": "Status", "value": "`🟢 In Stock`", "inline": True},
            {"name": "Detected", "value": f"<t:{epoch_now}:R>", "inline": True},
            {"name": "Redemption Link", "value": f"[**Click to Redeem on Store ➔**]({direct_link})", "inline": False}
        ],
        "footer": {"text": "Microsoft Rewards India • Live Verified Stock"}
    }

    if image_url:
        embed["thumbnail"] = {"url": image_url}

    payload = {
        "content": f"@everyone **{clean_card or 'Gift Card'} Restocked**",
        "embeds": [embed],
        "components": [
            {
                "type": 1,
                "components": [
                    {
                        "type": 2,
                        "style": 5,
                        "label": f"⚡ Claim {denomination} on Store ↗",
                        "url": direct_link
                    }
                ]
            }
        ]
    }

    try:
        # Append ?with_components=true to ensure Discord processes message components
        webhook_endpoint = DISCORD_WEBHOOK_URL
        if "with_components" not in webhook_endpoint:
            delim = "&" if "?" in webhook_endpoint else "?"
            webhook_endpoint = f"{webhook_endpoint}{delim}with_components=true"

        res = requests.post(webhook_endpoint, json=payload, timeout=10)
        if res.status_code in (200, 204):
            print(f"[+] Alert successfully sent to Discord for: {display_title}")
        else:
            # Fallback without components if webhook endpoint strictly rejects them
            print(f"[-] Discord returned HTTP {res.status_code}, retrying without components...")
            payload_fallback = {"content": payload["content"], "embeds": payload["embeds"]}
            res_fb = requests.post(DISCORD_WEBHOOK_URL, json=payload_fallback, timeout=10)
            if res_fb.status_code in (200, 204):
                print(f"[+] Fallback alert successfully sent to Discord for: {display_title}")
            else:
                print(f"[-] Discord error: HTTP {res_fb.status_code} - {res_fb.text}")
    except Exception as e:
        print(f"[-] Failed to deliver Discord webhook: {e}")

def main():
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Manual test alert mode
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("[*] TEST MODE: Dispatching test in-stock alert to Discord...")
        post_alert(
            card_title="Flipkart Gift Card (TEST)",
            full_title="₹1000 Flipkart Gift Card [TEST MODE]",
            points=19320,
            redeem_url="https://rewards.bing.com/redeem/sku/000885000034",
            image_url="https://bing.com/th?id=OMR.Redeem.Flipkart.jpg&pid=Rewards",
            timestamp=utc_now
        )
        return

    print(f"[*] Starting restock scan at {utc_now}...")

    session = requests.Session()
    state = load_state()
    catalog_items = []

    # Scan primary and fallback catalog URLs
    for url in [CATALOG_URL, CATALOG_URL_FALLBACK]:
        try:
            res = session.get(url, headers=HEADERS, timeout=15)
            if res.status_code == 200:
                extracted = extract_items_from_html(res.text)
                for it in extracted:
                    key = it.get('id') or it.get('title')
                    if not any((x.get('id') or x.get('title')) == key for x in catalog_items):
                        catalog_items.append(it)
        except requests.exceptions.RequestException as e:
            print(f"[-] Network connection error while checking {url}: {e}")

    # Also scan high-priority direct SKU URLs (e.g., Flipkart, Amazon Pay) directly
    for sku_url in DIRECT_SKU_URLS:
        try:
            res = session.get(sku_url, headers=HEADERS, timeout=12)
            if res.status_code == 200:
                extracted = extract_items_from_html(res.text)
                for it in extracted:
                    key = it.get('id') or it.get('title')
                    # Ensure href is set for SKU page item
                    if not it.get('href'):
                        it['href'] = sku_url.replace("https://rewards.bing.com", "")
                    if not any((x.get('id') or x.get('title')) == key for x in catalog_items):
                        catalog_items.append(it)
        except requests.exceptions.RequestException as e:
            print(f"[-] Warning: Failed checking direct SKU {sku_url}: {e}")

    print(f"[*] Indexed {len(catalog_items)} total catalog and direct SKU items.")

    matched_watchlist_items = []

    for item in catalog_items:
        title = (item.get('title') or '').lower()
        full_title = (item.get('fullTitle') or '').lower()
        combined_text = f"{title} {full_title}"

        for kw in WATCHLIST:
            if kw in combined_text:
                matched_watchlist_items.append((kw, item))
                break

    if not matched_watchlist_items:
        print("[+] Scan complete: No watchlist gift cards currently listed in catalog.")
        save_state(state)
        return

    new_in_stock_found = 0

    for kw, item in matched_watchlist_items:
        card_id = item.get('id') or kw
        title = item.get('title') or kw.upper()
        full_title = item.get('fullTitle') or title
        price = item.get('price')
        href = item.get('href')
        image_url = item.get('imageUrl')
        redeem_url = f"https://rewards.bing.com{href}" if href else CATALOG_URL

        is_stock, reason, verified_items = is_item_in_stock(item, session)

        if is_stock:
            print(f"[!] IN STOCK: {title} ({full_title}) - Reason: {reason}")
            # Check if we already alerted about this card being in stock
            last_status = state.get(card_id, {}).get("status")

            if last_status == "in_stock":
                print(f"[i] Alert already sent previously for {title} (skipping duplicate ping).")
            else:
                # Fresh restock drop!
                new_in_stock_found += 1
                post_alert(
                    card_title=title,
                    full_title=full_title,
                    points=price,
                    redeem_url=redeem_url,
                    image_url=image_url,
                    timestamp=utc_now
                )
                state[card_id] = {
                    "name": title,
                    "status": "in_stock",
                    "restocked_at": utc_now
                }
        else:
            print(f"[-] OUT OF STOCK: {title} ({full_title}) - Reason: {reason}")
            # Update state to out of stock so next restock will alert again
            if card_id in state and state[card_id].get("status") == "in_stock":
                print(f"[*] Status transitioned: {title} is now OUT OF STOCK.")
            state[card_id] = {
                "name": title,
                "status": "out_of_stock",
                "checked_at": utc_now
            }

    save_state(state)

    if new_in_stock_found == 0:
        print("[+] Scan complete: 0 new in-stock restocks detected. No alerts needed.")
    else:
        print(f"[+] Scan complete: Sent alerts for {new_in_stock_found} newly restocked item(s)!")

if __name__ == "__main__":
    main()
