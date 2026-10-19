import os
import sys
import requests
from datetime import datetime, timezone

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CATALOG_URL = "https://rewards.bing.com/redeem/in/shop"

WATCHLIST = [
    "amazon", "flipkart", "croma", "bookmyshow",
    "lifestyle", "myntra", "uber", "pantaloons", "zomato"
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-IN,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

def post_alert(card_name, timestamp):
    if not DISCORD_WEBHOOK_URL:
        print("[-] Warning: DISCORD_WEBHOOK_URL secret not set. Skipping webhook notification.")
        return

    payload = {
        "content": "@everyone 🚨 **RESTOCK DROP DETECTED!** 🚨",
        "embeds": [
            {
                "title": f"🎉 {card_name.upper()} IS IN STOCK!",
                "description": (
                    "A restock just dropped in the **Microsoft Rewards India** catalog.\n"
                    "Claim your voucher before the batch gets drained!"
                ),
                "url": CATALOG_URL,
                "color": 5763719,  # Green
                "fields": [
                    {"name": "🏷️ Card", "value": f"`{card_name.upper()}`", "inline": True},
                    {"name": "⏰ Detected At (UTC)", "value": f"`{timestamp}`", "inline": True},
                    {"name": "🔗 Link", "value": f"[Open Rewards Store]({CATALOG_URL})", "inline": False}
                ],
                "footer": {"text": "GitHub Actions Cloud Runner • MS Rewards Sentinel"}
            }
        ]
    }
    
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if res.status_code in (200, 204):
            print(f"[+] Alert successfully sent to Discord for: {card_name}")
        else:
            print(f"[-] Discord error: HTTP {res.status_code} - {res.text}")
    except Exception as e:
        print(f"[-] Failed to deliver Discord webhook: {e}")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("[*] TEST MODE: Dispatching test alert to Discord...")
        post_alert("FLIPKART (TEST RUN)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
        return

    print(f"[*] Starting scan at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}...")
    
    try:
        res = requests.get(CATALOG_URL, headers=HEADERS, timeout=15)
        if res.status_code != 200:
            print(f"[-] Catalog fetch returned HTTP {res.status_code}")
            sys.exit(0)

        html = res.text.lower()
        found_any = False
        
        for card in WATCHLIST:
            if card in html:
                found_any = True
                print(f"[!] MATCH FOUND: {card.upper()}")
                post_alert(card, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))

        if not found_any:
            print("[+] Scan complete: Catalog still dry (Only Overwatch/Donations present).")

    except requests.exceptions.RequestException as e:
        print(f"[-] Network connection error during check: {e}")

if __name__ == "__main__":
    main()
