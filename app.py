from flask import Flask
import os, time, threading, requests
import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

app = Flask(__name__)

# ================= CONFIG =================
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RISK_PER_TRADE = 5000
MAX_TRADES = 2

ENTRY_START = "09:30"
ENTRY_END = "14:30"
EXIT_TIME = "15:15"

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

TRADES_COUNT = 0
TRADED_TODAY = set()
ACTIVE_TRADES = {}
instrument_tokens = {}

PENDING_TRADES = {}
LAST_UPDATE_ID = None

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ================= MARKET BIAS =================
def get_market_bias():
    try:
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        headers = {"User-Agent": "Mozilla/5.0"}
        data = requests.get(url, headers=headers).json()

        adv = data["advance"]["advances"]
        dec = data["advance"]["declines"]

        if adv - dec > 300:
            return "LONG"
        elif dec - adv > 300:
            return "SHORT"
    except:
        pass
    return None

# ================= LOAD TOKENS =================
def load_tokens(symbols):
    instruments = kite.instruments("NSE")
    for i in instruments:
        if i["tradingsymbol"] in symbols:
            instrument_tokens[i["tradingsymbol"]] = i["instrument_token"]

# ================= GET DATA =================
def get_candles(symbol):
    try:
        token = instrument_tokens[symbol]
        data = kite.historical_data(
            token,
            datetime.now() - timedelta(days=1),
            datetime.now(),
            "5minute"
        )
        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        return df
    except:
        return None

# ================= STRATEGY =================
def check_signal(symbol, direction):
    df = get_candles(symbol)
    if df is None or len(df) < 10:
        return None

    today = datetime.now().date()
    df = df[df['date'].dt.date == today]

    if len(df) < 7:
        return None

    now = datetime.now().time()
    if not (datetime.strptime(ENTRY_START,"%H:%M").time() <= now <= datetime.strptime(ENTRY_END,"%H:%M").time()):
        return None

    candle = df.loc[df['volume'].idxmin()]

    if candle.name in df.iloc[:3].index:
        return None

    entry = candle.high if direction=="LONG" else candle.low
    sl = candle.low if direction=="LONG" else candle.high

    risk = abs(entry - sl)
    if risk <= 0:
        return None

    qty = int(RISK_PER_TRADE / risk)
    if qty <= 0:
        return None

    target = entry + (2*risk) if direction=="LONG" else entry - (2*risk)

    return direction, entry, sl, target, qty

# ================= PLACE TRADE =================
def place_trade(symbol, side, entry, sl, target, qty):
    global TRADES_COUNT

    try:
        q_half = qty // 2
        q_remain = qty - q_half

        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=kite.TRANSACTION_TYPE_BUY if side=="LONG" else kite.TRANSACTION_TYPE_SELL,
            quantity=qty,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_MIS
        )

        sl_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=kite.TRANSACTION_TYPE_SELL if side=="LONG" else kite.TRANSACTION_TYPE_BUY,
            quantity=qty,
            order_type=kite.ORDER_TYPE_SLM,
            trigger_price=round(sl,1),
            product=kite.PRODUCT_MIS
        )

        tgt_id = kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=kite.TRANSACTION_TYPE_SELL if side=="LONG" else kite.TRANSACTION_TYPE_BUY,
            quantity=q_half,
            order_type=kite.ORDER_TYPE_LIMIT,
            price=round(target,1),
            product=kite.PRODUCT_MIS
        )

        ACTIVE_TRADES[symbol] = {
            "side": side,
            "entry": entry,
            "sl_id": sl_id,
            "tgt_id": tgt_id,
            "remaining_qty": q_remain,
            "half_done": False
        }

        TRADES_COUNT += 1
        TRADED_TODAY.add(symbol)

        send_telegram(f"🚀 TRADE EXECUTED: {symbol}")

    except Exception as e:
        send_telegram(f"❌ Order Failed: {e}")

# ================= TELEGRAM LISTENER =================
def check_telegram_commands():
    global LAST_UPDATE_ID

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
            if LAST_UPDATE_ID:
                url += f"?offset={LAST_UPDATE_ID + 1}"

            res = requests.get(url).json()

            for update in res.get("result", []):
                LAST_UPDATE_ID = update["update_id"]

                if "message" in update:
                    text = update["message"].get("text", "").upper()

                    # TEST COMMAND
                    if text == "TEST":
                        PENDING_TRADES["RELIANCE"] = {
                            "side": "LONG",
                            "entry": 100,
                            "sl": 95,
                            "target": 110,
                            "qty": 10
                        }
                        send_telegram("🧪 TEST SIGNAL: RELIANCE\nReply YES RELIANCE")

                    # YES COMMAND
                    if text.startswith("YES"):
                        parts = text.split()

                        if len(parts) == 2:
                            symbol = parts[1]

                            if symbol in PENDING_TRADES:
                                trade = PENDING_TRADES.pop(symbol)

                                place_trade(
                                    symbol,
                                    trade["side"],
                                    trade["entry"],
                                    trade["sl"],
                                    trade["target"],
                                    trade["qty"]
                                )

                                send_telegram(f"✅ CONFIRMED: {symbol}")
                            else:
                                send_telegram("❌ No pending trade for this symbol")

        except Exception as e:
            print("Telegram Error:", e)

        time.sleep(5)

# ================= BOT LOOP =================
def bot_loop():

    symbols = ["RELIANCE","TCS","INFY","HDFCBANK","ICICIBANK","SBIN","LT"]
    load_tokens(symbols)

    send_telegram("🚀 V4.2 BOT STARTED (TEST + CONFIRMATION MODE)")

    while True:
        try:
            direction = get_market_bias()

            if direction is None:
                time.sleep(30)
                continue

            for symbol in symbols:

                if symbol in TRADED_TODAY:
                    continue

                if TRADES_COUNT >= MAX_TRADES:
                    continue

                if symbol in PENDING_TRADES:
                    continue

                signal = check_signal(symbol, direction)

                if signal:
                    side, entry, sl, target, qty = signal

                    PENDING_TRADES[symbol] = {
                        "side": side,
                        "entry": entry,
                        "sl": sl,
                        "target": target,
                        "qty": qty
                    }

                    send_telegram(
                        f"📊 SIGNAL: {symbol}\n"
                        f"{side}\nEntry: {entry}\nSL: {sl}\nTarget: {target}\n\n"
                        f"Reply: YES {symbol}"
                    )

            time.sleep(30)

        except:
            time.sleep(10)

@app.route("/")
def home():
    return "V4.2 Running"

threading.Thread(target=bot_loop, daemon=True).start()
threading.Thread(target=check_telegram_commands, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
