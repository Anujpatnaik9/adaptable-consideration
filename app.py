from flask import Flask
import os
import time
import threading
import requests
import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

app = Flask(__name__)

# ================= SETTINGS =================
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CAPITAL = 500000
RISK_PER_TRADE = 0.01
MAX_TRADES = 2

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

TRADES_COUNT = 0
TRADED_TODAY = set()
instrument_tokens = {}

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ================= NIFTY200 =================
def get_nifty200():
    url = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    df = pd.read_csv(url)
    return list(df["Symbol"])

# ================= LOAD TOKENS =================
def load_tokens(symbols):
    instruments = kite.instruments("NSE")
    for i in instruments:
        if i["tradingsymbol"] in symbols:
            instrument_tokens[i["tradingsymbol"]] = i["instrument_token"]

# ================= MARKET BIAS =================
def get_market_bias():
    try:
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        headers = {"User-Agent": "Mozilla/5.0"}
        data = requests.get(url, headers=headers).json()

        adv = data["advance"]["advances"]
        dec = data["advance"]["declines"]

        if adv - dec >= 300:
            return "LONG"
        elif dec - adv >= 300:
            return "SHORT"
    except:
        pass

    return None

# ================= CANDLES =================
def get_candles(symbol):
    try:
        token = instrument_tokens[symbol]

        data = kite.historical_data(
            token,
            datetime.now() - timedelta(days=2),
            datetime.now(),
            "5minute"
        )

        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
        return df

    except:
        return None

# ================= LOW VOLUME LOGIC =================
def check_signal(symbol, direction):

    df = get_candles(symbol)
    if df is None or len(df) < 10:
        return None

    today = datetime.now().date()
    df_today = df[df['date'].dt.date == today]

    if len(df_today) < 7:
        return None

    # Ignore first 3 candles for trading
    df_trade = df_today[df_today['date'].dt.time >= datetime.strptime("09:30","%H:%M").time()]

    if df_trade.empty:
        return None

    current = df_today.iloc[-1]

    # Volume condition (from 9:15 till now)
    if current.volume != df_today.volume.min():
        return None

    # LONG
    if direction == "LONG":
        if current.close < current.open:  # RED candle

            entry = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]
            sl = current.low

            risk = entry - sl
            if risk <= 0:
                return None

            qty = int((CAPITAL * RISK_PER_TRADE) / risk)
            return ("LONG", entry, sl, max(qty,1))

    # SHORT
    if direction == "SHORT":
        if current.close > current.open:  # GREEN candle

            entry = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]
            sl = current.high

            risk = sl - entry
            if risk <= 0:
                return None

            qty = int((CAPITAL * RISK_PER_TRADE) / risk)
            return ("SHORT", entry, sl, max(qty,1))

    return None

# ================= PLACE TRADE =================
def place_trade(symbol, side, entry, sl, qty):

    global TRADES_COUNT

    if symbol in TRADED_TODAY:
        return

    try:

        # ENTRY ORDER
        ttype = kite.TRANSACTION_TYPE_BUY if side == "LONG" else kite.TRANSACTION_TYPE_SELL

        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=ttype,
            quantity=qty,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_MIS
        )

        # STOP LOSS ORDER (SL-M)
        sl_type = kite.TRANSACTION_TYPE_SELL if side == "LONG" else kite.TRANSACTION_TYPE_BUY

        kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=sl_type,
            quantity=qty,
            order_type=kite.ORDER_TYPE_SL,
            trigger_price=round(sl,2),
            product=kite.PRODUCT_MIS
        )

        send_telegram(
            f"🚨 TRADE EXECUTED\n{symbol}\n{side}\nEntry: {round(entry,2)}\nSL: {round(sl,2)}\nQty: {qty}"
        )

        TRADED_TODAY.add(symbol)
        TRADES_COUNT += 1

    except Exception as e:
        send_telegram(f"Error placing trade {symbol}")

# ================= BOT LOOP =================
def bot_loop():

    symbols = get_nifty200()
    load_tokens(symbols)

    send_telegram("🚀 Bot Started V3 (Final Strategy)")

    while True:

        try:
            now = datetime.now().time()

            # Only trade between 9:30 and 10:30
            if not (datetime.strptime("09:30","%H:%M").time() <= now <= datetime.strptime("10:30","%H:%M").time()):
                time.sleep(30)
                continue

            if TRADES_COUNT >= MAX_TRADES:
                time.sleep(30)
                continue

            direction = get_market_bias()

            if direction is None:
                time.sleep(30)
                continue

            for symbol in symbols:

                if symbol in TRADED_TODAY:
                    continue

                signal = check_signal(symbol, direction)

                if signal:
                    side, entry, sl, qty = signal
                    place_trade(symbol, side, entry, sl, qty)

            time.sleep(30)

        except:
            time.sleep(10)

@app.route("/")
def home():
    return "V3 Bot Running"

thread = threading.Thread(target=bot_loop)
thread.daemon = True
thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
