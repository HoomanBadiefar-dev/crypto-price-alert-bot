"""
ربات هشدار قیمت کریپتو
- دستورات تلگرامی مثل /alert BTC 70000 رو می‌خونه و هشدار جدید اضافه می‌کنه
- قیمت‌ها رو از CoinGecko می‌گیره
- با هشدارهای ذخیره‌شده در alerts.json مقایسه می‌کنه
- اگه هشداری فعال بشه، پیام تلگرام می‌فرسته و اون هشدار رو غیرفعال می‌کنه

این اسکریپت برای اجرا با GitHub Actions طراحی شده (هر بار از صفر اجرا می‌شه، حافظه نداره،
به همین خاطر last_update_id و alerts.json رو خودش روی دیسک/ریپو نگه می‌داره).
"""

import json
import os
import sys
import requests

ALERTS_FILE = "alerts.json"
STATE_FILE = "state.json"

# نگاشت نمادهای رایج به شناسه CoinGecko
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


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def get_updates(bot_token, offset):
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {"offset": offset, "timeout": 0}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", [])


def parse_alert_command(text):
    # فرمت مورد انتظار: /alert BTC 70000
    parts = text.strip().split()
    if len(parts) != 3:
        return None, "فرمت درست: /alert SYMBOL PRICE   مثل: /alert BTC 70000"

    _, symbol, price_str = parts
    symbol = symbol.upper()

    if symbol not in SYMBOL_TO_ID:
        supported = ", ".join(sorted(SYMBOL_TO_ID.keys()))
        return None, f"نماد {symbol} پشتیبانی نمی‌شه. نمادهای موجود: {supported}"

    try:
        target_price = float(price_str)
    except ValueError:
        return None, "قیمت باید عدد باشه. مثل: /alert BTC 70000"

    return {"symbol": symbol, "coin_id": SYMBOL_TO_ID[symbol], "target_price": target_price}, None


def process_incoming_commands(bot_token, chat_id, state, alerts):
    updates = get_updates(bot_token, state.get("last_update_id", 0) + 1)
    if not updates:
        return alerts, state, False

    changed = False
    max_update_id = state.get("last_update_id", 0)

    for update in updates:
        max_update_id = max(max_update_id, update.get("update_id", 0))
        message = update.get("message") or {}
        text = message.get("text", "")

        if not text.lower().startswith("/alert"):
            continue

        alert_data, error = parse_alert_command(text)

        if error:
            send_telegram_message(bot_token, chat_id, f"⚠️ {error}")
            continue

        # قیمت فعلی رو می‌گیریم تا جهت هشدار (بالا/پایین) رو خودکار تشخیص بدیم
        current_prices = fetch_prices([alert_data["coin_id"]])
        current = current_prices.get(alert_data["coin_id"], {}).get("usd")

        if current is None:
            send_telegram_message(bot_token, chat_id, "⚠️ نتونستم قیمت فعلی رو بگیرم، دوباره امتحان کن.")
            continue

        direction = "above" if alert_data["target_price"] > current else "below"

        new_alert = {
            "symbol": alert_data["symbol"],
            "coin_id": alert_data["coin_id"],
            "target_price": alert_data["target_price"],
            "direction": direction,
            "triggered": False,
        }
        alerts.append(new_alert)
        changed = True

        direction_fa = "بالاتر بره" if direction == "above" else "پایین‌تر بیاد"
        send_telegram_message(
            bot_token,
            chat_id,
            f"✅ هشدار ثبت شد\n"
            f"{alert_data['symbol']} — وقتی قیمت {direction_fa} از {alert_data['target_price']:,.4f}$\n"
            f"(قیمت فعلی: {current:,.4f}$)",
        )

    state["last_update_id"] = max_update_id
    return alerts, state, changed


def check_alerts(bot_token, chat_id, alerts):
    coin_ids = list({a["coin_id"] for a in alerts if not a.get("triggered")})
    prices = fetch_prices(coin_ids)

    changed = False
    for alert in alerts:
        if alert.get("triggered"):
            continue

        coin_id = alert["coin_id"]
        target = alert["target_price"]
        direction = alert["direction"]

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

    return alerts, changed


def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("خطا: TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID تنظیم نشده.")
        sys.exit(1)

    alerts = load_json(ALERTS_FILE, [])
    state = load_json(STATE_FILE, {"last_update_id": 0})

    alerts, state, commands_changed = process_incoming_commands(bot_token, chat_id, state, alerts)
    save_json(STATE_FILE, state)

    alerts, prices_changed = check_alerts(bot_token, chat_id, alerts)

    if commands_changed or prices_changed:
        save_json(ALERTS_FILE, alerts)


if __name__ == "__main__":
    main()
