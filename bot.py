"""
ربات هشدار قیمت کریپتو
- قیمت‌ها رو از CoinGecko می‌گیره
- با هشدارهای ذخیره‌شده در alerts.json مقایسه می‌کنه
- اگه هشداری فعال بشه، پیام تلگرام می‌فرسته و اون هشدار رو غیرفعال می‌کنه

این اسکریپت برای اجرا با GitHub Actions طراحی شده (هر بار از صفر اجرا می‌شه، حافظه نداره).
"""

import json
import os
import sys
import requests

ALERTS_FILE = "alerts.json"

# نگاشت نمادهای رایج به شناسه CoinGecko
# می‌تونی بعداً موارد بیشتری اضافه کنی
SYMBOL_TO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "TON": "the-open-network",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "SHIB": "shiba-inu",
}


def load_alerts():
    if not os.path.exists(ALERTS_FILE):
        return []
    with open(ALERTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_alerts(alerts):
    with open(ALERTS_FILE, "w", encoding="utf-8") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


def fetch_prices(coin_ids):
    if not coin_ids:
        return {}
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(coin_ids), "vs_currencies": "usd"}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, data={"chat_id": chat_id, "text": text})
    resp.raise_for_status()


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("خطا: TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID تنظیم نشده.")
        sys.exit(1)

    alerts = load_alerts()
    if not alerts:
        print("هیچ هشدار فعالی وجود نداره.")
        return

    coin_ids = list({a["coin_id"] for a in alerts if not a.get("triggered")})
    prices = fetch_prices(coin_ids)

    changed = False
    for alert in alerts:
        if alert.get("triggered"):
            continue

        coin_id = alert["coin_id"]
        target = alert["target_price"]
        direction = alert["direction"]  # "above" یا "below"

        current = prices.get(coin_id, {}).get("usd")
        if current is None:
            continue

        hit = (direction == "above" and current >= target) or (
            direction == "below" and current <= target
        )

        if hit:
            symbol = alert.get("symbol", coin_id.upper())
            msg = (
                f"🔔 هشدار قیمت\n"
                f"{symbol} به قیمت {current:,.4f}$ رسید\n"
                f"(هدف شما: {target:,.4f}$)"
            )
            send_telegram_message(bot_token, chat_id, msg)
            alert["triggered"] = True
            changed = True
            print(f"هشدار ارسال شد: {symbol}")

    if changed:
        save_alerts(alerts)


if __name__ == "__main__":
    main()
