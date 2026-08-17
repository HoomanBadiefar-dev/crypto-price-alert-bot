"""
ربات هشدار قیمت کریپتو + ابزارهای معامله‌گری برای HGC Academy

قابلیت‌ها:
- /alert SYMBOL PRICE      ثبت هشدار قیمت (جهت خودکار تشخیص داده می‌شه)
- /list                    لیست هشدارها با تاریخ ثبت (دکمه هم داره)
- /risk BALANCE RISK% ENTRY STOP   محاسبه‌ی حجم پوزیشن
- /gainers                 ۵ صعودی و ۵ نزولی برتر ۲۴ ساعته (دکمه هم داره)
- /feargreed                شاخص ترس و طمع بازار (دکمه هم داره)
- /convert AMOUNT FROM TO   تبدیل بین ارزها
- /compare SYMBOL          مقایسه‌ی قیمت بین چند صرافی
- /export                  ارسال فایل پشتیبان کامل هشدارها

این اسکریپت با GitHub Actions هر ۵ دقیقه اجرا می‌شه (حافظه‌ی دائمی نداره،
به همین خاطر alerts.json و state.json رو خودش روی ریپو نگه می‌داره).
"""

import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

ALERTS_FILE = "alerts.json"
STATE_FILE = "state.json"
TEHRAN_TZ = ZoneInfo("Asia/Tehran")

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

# نگاشت نماد به کد جفت‌ارز کرکن (Kraken) برای دستور /compare
KRAKEN_PAIR = {
    "BTC": "XBTUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "LTC": "LTCUSDT",
    "DOGE": "DOGEUSDT",
    "ADA": "ADAUSDT",
    "LINK": "LINKUSDT",
    "DOT": "DOTUSDT",
    "AVAX": "AVAXUSDT",
    "TRX": "TRXUSDT",
}


# ---------------------------------------------------------------------------
# ابزارهای کمکی عمومی
# ---------------------------------------------------------------------------

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_tehran_str():
    return datetime.now(TEHRAN_TZ).strftime("%Y-%m-%d %H:%M")


def fetch_prices(coin_ids):
    if not coin_ids:
        return {}
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {"ids": ",".join(coin_ids), "vs_currencies": "usd"}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_markets(per_page=100):
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": per_page,
        "page": 1,
        "price_change_percentage": "24h",
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# ارتباط با تلگرام
# ---------------------------------------------------------------------------

def send_telegram_message(bot_token, chat_id, text, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    resp = requests.post(url, data=data)
    resp.raise_for_status()


def send_telegram_document(bot_token, chat_id, filename, content_bytes, caption=""):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    files = {"document": (filename, content_bytes, "application/json")}
    data = {"chat_id": chat_id, "caption": caption}
    resp = requests.post(url, data=data, files=files)
    resp.raise_for_status()


def answer_callback_query(bot_token, callback_query_id):
    url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
    requests.post(url, data={"callback_query_id": callback_query_id})


def get_updates(bot_token, offset):
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    params = {"offset": offset, "timeout": 0}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json().get("result", [])


MAIN_MENU_KEYBOARD = {
    "inline_keyboard": [
        [{"text": "📋 لیست هشدارها", "callback_data": "list_alerts"}],
        [{"text": "📈 برترین صعودی/نزولی", "callback_data": "gainers_losers"}],
        [{"text": "😨 شاخص ترس و طمع", "callback_data": "fear_greed"}],
    ]
}


# ---------------------------------------------------------------------------
# قابلیت‌ها
# ---------------------------------------------------------------------------

def handle_alert_command(text, bot_token, chat_id, alerts):
    parts = text.strip().split()
    if len(parts) != 3:
        send_telegram_message(bot_token, chat_id, "فرمت درست: /alert SYMBOL PRICE   مثل: /alert BTC 70000")
        return alerts, False

    _, symbol, price_str = parts
    symbol = symbol.upper()

    if symbol not in SYMBOL_TO_ID:
        supported = ", ".join(sorted(SYMBOL_TO_ID.keys()))
        send_telegram_message(bot_token, chat_id, f"⚠️ نماد {symbol} پشتیبانی نمی‌شه. نمادهای موجود: {supported}")
        return alerts, False

    try:
        target_price = float(price_str)
    except ValueError:
        send_telegram_message(bot_token, chat_id, "⚠️ قیمت باید عدد باشه. مثل: /alert BTC 70000")
        return alerts, False

    coin_id = SYMBOL_TO_ID[symbol]
    current_prices = fetch_prices([coin_id])
    current = current_prices.get(coin_id, {}).get("usd")

    if current is None:
        send_telegram_message(bot_token, chat_id, "⚠️ نتونستم قیمت فعلی رو بگیرم، دوباره امتحان کن.")
        return alerts, False

    direction = "above" if target_price > current else "below"

    new_alert = {
        "symbol": symbol,
        "coin_id": coin_id,
        "target_price": target_price,
        "direction": direction,
        "triggered": False,
        "created_at": now_tehran_str(),
    }
    alerts.append(new_alert)

    direction_fa = "بالاتر بره" if direction == "above" else "پایین‌تر بیاد"
    send_telegram_message(
        bot_token,
        chat_id,
        f"✅ هشدار ثبت شد\n"
        f"{symbol} — وقتی قیمت {direction_fa} از {target_price:,.4f}$\n"
        f"(قیمت فعلی: {current:,.4f}$)",
    )
    return alerts, True


def build_alerts_list_text(alerts):
    if not alerts:
        return "هیچ هشداری ثبت نشده."

    lines = []
    for i, a in enumerate(alerts, start=1):
        status = "✅ ارسال‌شده" if a.get("triggered") else "⏳ فعال"
        direction_fa = "بالاتر از" if a.get("direction") == "above" else "پایین‌تر از"
        created = a.get("created_at", "نامشخص")
        lines.append(
            f"{i}. {a.get('symbol')} {direction_fa} {a.get('target_price'):,.4f}$ — {status}\n   ثبت‌شده: {created}"
        )
    return "📋 لیست هشدارها:\n\n" + "\n\n".join(lines)


def handle_list(bot_token, chat_id, alerts):
    send_telegram_message(bot_token, chat_id, build_alerts_list_text(alerts))


def handle_risk_command(text, bot_token, chat_id):
    parts = text.strip().split()
    if len(parts) != 5:
        send_telegram_message(
            bot_token,
            chat_id,
            "فرمت درست: /risk BALANCE RISK% ENTRY STOP\nمثل: /risk 1000 2 65000 64000",
        )
        return

    try:
        _, balance, risk_pct, entry, stop = parts
        balance = float(balance)
        risk_pct = float(risk_pct)
        entry = float(entry)
        stop = float(stop)
    except ValueError:
        send_telegram_message(bot_token, chat_id, "⚠️ همه‌ی مقادیر باید عدد باشن.")
        return

    stop_distance = abs(entry - stop)
    if stop_distance == 0:
        send_telegram_message(bot_token, chat_id, "⚠️ قیمت ورود و حد ضرر نمی‌تونن برابر باشن.")
        return

    risk_amount = balance * (risk_pct / 100)
    position_size = risk_amount / stop_distance
    position_value = position_size * entry

    send_telegram_message(
        bot_token,
        chat_id,
        "📐 محاسبه‌ی حجم پوزیشن\n\n"
        f"مبلغ ریسک: {risk_amount:,.2f}$\n"
        f"فاصله‌ی حد ضرر: {stop_distance:,.4f}$\n"
        f"حجم پوزیشن: {position_size:,.6f} واحد\n"
        f"ارزش پوزیشن: {position_value:,.2f}$",
    )


def handle_gainers_losers(bot_token, chat_id):
    markets = fetch_markets(per_page=100)
    valid = [m for m in markets if m.get("price_change_percentage_24h") is not None]
    sorted_by_change = sorted(valid, key=lambda m: m["price_change_percentage_24h"], reverse=True)

    top_gainers = sorted_by_change[:5]
    top_losers = sorted_by_change[-5:][::-1]

    lines = ["📈 برترین صعودی‌های ۲۴ ساعته:"]
    for m in top_gainers:
        lines.append(f"  {m['symbol'].upper()}: {m['current_price']:,.4f}$ ({m['price_change_percentage_24h']:+.2f}%)")

    lines.append("\n📉 برترین نزولی‌های ۲۴ ساعته:")
    for m in top_losers:
        lines.append(f"  {m['symbol'].upper()}: {m['current_price']:,.4f}$ ({m['price_change_percentage_24h']:+.2f}%)")

    send_telegram_message(bot_token, chat_id, "\n".join(lines))


def handle_fear_greed(bot_token, chat_id):
    url = "https://api.alternative.me/fng/"
    resp = requests.get(url, params={"limit": 1}, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data", [])

    if not data:
        send_telegram_message(bot_token, chat_id, "⚠️ نتونستم شاخص ترس و طمع رو بگیرم.")
        return

    value = data[0].get("value")
    classification = data[0].get("value_classification")

    classification_fa = {
        "Extreme Fear": "ترس شدید",
        "Fear": "ترس",
        "Neutral": "خنثی",
        "Greed": "طمع",
        "Extreme Greed": "طمع شدید",
    }.get(classification, classification)

    send_telegram_message(
        bot_token,
        chat_id,
        f"😨 شاخص ترس و طمع بازار\n\nعدد: {value}/100\nوضعیت: {classification_fa}",
    )


def handle_convert_command(text, bot_token, chat_id):
    parts = text.strip().split()
    if len(parts) != 4:
        send_telegram_message(
            bot_token, chat_id, "فرمت درست: /convert AMOUNT FROM TO\nمثل: /convert 100 USD BTC یا /convert 0.5 BTC ETH"
        )
        return

    _, amount_str, from_sym, to_sym = parts
    from_sym = from_sym.upper()
    to_sym = to_sym.upper()

    try:
        amount = float(amount_str)
    except ValueError:
        send_telegram_message(bot_token, chat_id, "⚠️ مقدار باید عدد باشه.")
        return

    def usd_value_of(symbol):
        if symbol == "USD":
            return 1.0
        coin_id = SYMBOL_TO_ID.get(symbol)
        if coin_id is None:
            return None
        prices = fetch_prices([coin_id])
        return prices.get(coin_id, {}).get("usd")

    from_usd = usd_value_of(from_sym)
    to_usd = usd_value_of(to_sym)

    if from_usd is None or to_usd is None:
        supported = ", ".join(sorted(SYMBOL_TO_ID.keys()) + ["USD"])
        send_telegram_message(bot_token, chat_id, f"⚠️ نماد پشتیبانی نمی‌شه. نمادهای موجود: {supported}")
        return

    result = amount * from_usd / to_usd
    send_telegram_message(bot_token, chat_id, f"💱 {amount:,.4f} {from_sym} = {result:,.6f} {to_sym}")


def handle_compare_command(text, bot_token, chat_id):
    parts = text.strip().split()
    if len(parts) != 2:
        send_telegram_message(bot_token, chat_id, "فرمت درست: /compare SYMBOL   مثل: /compare BTC")
        return

    symbol = parts[1].upper()
    if symbol not in SYMBOL_TO_ID:
        supported = ", ".join(sorted(SYMBOL_TO_ID.keys()))
        send_telegram_message(bot_token, chat_id, f"⚠️ نماد {symbol} پشتیبانی نمی‌شه. نمادهای موجود: {supported}")
        return

    results = {}

    # Binance
    try:
        r = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": f"{symbol}USDT"},
            timeout=10,
        )
        r.raise_for_status()
        results["Binance"] = float(r.json()["price"])
    except Exception:
        results["Binance"] = None

    # Coinbase
    try:
        r = requests.get(f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot", timeout=10)
        r.raise_for_status()
        results["Coinbase"] = float(r.json()["data"]["amount"])
    except Exception:
        results["Coinbase"] = None

    # Kraken
    kraken_pair = KRAKEN_PAIR.get(symbol)
    if kraken_pair:
        try:
            r = requests.get(
                "https://api.kraken.com/0/public/Ticker", params={"pair": kraken_pair}, timeout=10
            )
            r.raise_for_status()
            result_data = r.json().get("result", {})
            first_key = next(iter(result_data))
            results["Kraken"] = float(result_data[first_key]["c"][0])
        except Exception:
            results["Kraken"] = None
    else:
        results["Kraken"] = None

    lines = [f"⚖️ مقایسه‌ی قیمت {symbol}:"]
    for exchange, price in results.items():
        if price is None:
            lines.append(f"  {exchange}: در دسترس نبود")
        else:
            lines.append(f"  {exchange}: {price:,.4f}$")

    send_telegram_message(bot_token, chat_id, "\n".join(lines))


def handle_export(bot_token, chat_id, alerts):
    content = json.dumps(alerts, ensure_ascii=False, indent=2).encode("utf-8")
    send_telegram_document(bot_token, chat_id, "alerts_backup.json", content, caption="📦 پشتیبان کامل هشدارها")


def handle_start(bot_token, chat_id):
    text = (
        "سلام! 👋 به ربات هشدار قیمت HGC Academy خوش اومدی.\n\n"
        "دستورات موجود:\n"
        "/alert SYMBOL PRICE — ثبت هشدار قیمت\n"
        "/list — لیست هشدارها\n"
        "/risk BALANCE RISK% ENTRY STOP — محاسبه‌ی حجم پوزیشن\n"
        "/gainers — برترین صعودی/نزولی ۲۴ساعته\n"
        "/feargreed — شاخص ترس و طمع\n"
        "/convert AMOUNT FROM TO — تبدیل ارز\n"
        "/compare SYMBOL — مقایسه‌ی قیمت بین صرافی‌ها\n"
        "/export — دریافت فایل پشتیبان هشدارها"
    )
    send_telegram_message(bot_token, chat_id, text, reply_markup=MAIN_MENU_KEYBOARD)


# ---------------------------------------------------------------------------
# پردازش پیام‌های ورودی (دستورات متنی + کلیک روی دکمه‌ها)
# ---------------------------------------------------------------------------

def process_incoming_updates(bot_token, chat_id, state, alerts):
    updates = get_updates(bot_token, state.get("last_update_id", 0) + 1)
    if not updates:
        return alerts, state, False

    changed = False
    max_update_id = state.get("last_update_id", 0)

    for update in updates:
        max_update_id = max(max_update_id, update.get("update_id", 0))

        # کلیک روی دکمه‌ی شیشه‌ای
        callback = update.get("callback_query")
        if callback:
            answer_callback_query(bot_token, callback["id"])
            data = callback.get("data", "")
            cb_chat_id = callback["message"]["chat"]["id"]

            if data == "list_alerts":
                handle_list(bot_token, cb_chat_id, alerts)
            elif data == "gainers_losers":
                handle_gainers_losers(bot_token, cb_chat_id)
            elif data == "fear_greed":
                handle_fear_greed(bot_token, cb_chat_id)
            continue

        # پیام متنی معمولی
        message = update.get("message") or {}
        text = message.get("text", "")
        if not text:
            continue

        command = text.strip().split()[0].lower()

        if command == "/start":
            handle_start(bot_token, chat_id)
        elif command == "/alert":
            alerts, alert_changed = handle_alert_command(text, bot_token, chat_id, alerts)
            changed = changed or alert_changed
        elif command == "/list":
            handle_list(bot_token, chat_id, alerts)
        elif command == "/risk":
            handle_risk_command(text, bot_token, chat_id)
        elif command == "/gainers":
            handle_gainers_losers(bot_token, chat_id)
        elif command == "/feargreed":
            handle_fear_greed(bot_token, chat_id)
        elif command == "/convert":
            handle_convert_command(text, bot_token, chat_id)
        elif command == "/compare":
            handle_compare_command(text, bot_token, chat_id)
        elif command == "/export":
            handle_export(bot_token, chat_id, alerts)

    state["last_update_id"] = max_update_id
    return alerts, state, changed


# ---------------------------------------------------------------------------
# چک کردن هشدارهای فعال در برابر قیمت لحظه‌ای
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("خطا: TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID تنظیم نشده.")
        sys.exit(1)

    alerts = load_json(ALERTS_FILE, [])
    state = load_json(STATE_FILE, {"last_update_id": 0})

    alerts, state, commands_changed = process_incoming_updates(bot_token, chat_id, state, alerts)
    save_json(STATE_FILE, state)

    alerts, prices_changed = check_alerts(bot_token, chat_id, alerts)

    if commands_changed or prices_changed:
        save_json(ALERTS_FILE, alerts)


if __name__ == "__main__":
    main()
