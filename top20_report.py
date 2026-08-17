"""
گزارش ۲۰ ارز برتر بازار (بر اساس ارزش بازار) - هر ۴ ساعت اجرا می‌شه
مستقل از bot.py و alerts.json عمل می‌کنه.
"""

import os
import sys

import requests


def fetch_top20():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 20,
        "page": 1,
    }
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

    coins = fetch_top20()

    lines = ["💰 ۲۰ ارز برتر بازار (بر اساس ارزش بازار):\n"]
    for i, c in enumerate(coins, start=1):
        symbol = c["symbol"].upper()
        price = c["current_price"]
        lines.append(f"{i}. {symbol}: {price:,.4f}$")

    send_telegram_message(bot_token, chat_id, "\n".join(lines))


if __name__ == "__main__":
    main()
