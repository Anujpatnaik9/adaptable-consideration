from flask import Flask
import os
import time
import threading
import requests
import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

app = Flask(__name__)

# ENV VARIABLES
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# SETTINGS
CAPITAL = 500000
RISK_PER_TRADE = 0.01
MAX_TRADES = 2

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

TRADES_COUNT = 0
TRADED_TODAY = set()
ORDER_PLACED = set()

instrument_tokens = {}

# TELEGRAM
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# NIFTY200
def get_nifty200():
    url = "https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    df = pd.read_csv(url)
    return list(df["Symbol"])

# LOAD TOKENS
def load_tokens(symbols):
    instruments = kite.instruments("NSE")
    for i in instruments:
        if i["tradingsymbol"] in symbols:
            instrument_tokens[i["tradingsymbol"]] = i["instrument_token"]

# GET CANDLES
def get_candles(symbol):
    try:
        token = instrument_tokens[symbol]

        data = kite.historical_data(
            token,
            datetime.now() - timedelta(days=3),
            datetime.now(),
            "5minute"
        )

        df = pd.DataFrame(data)
        df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)

        return df
    except:
        return None

# 🔥 TREND DETECTION (NEW)
def get_trend(df_today):

    if len(df_today) < 10:
        return None

    recent = df_today.tail(10)

    # Higher highs & higher lows → LONG
    if recent['high'].iloc[-1] > recent['high'].iloc[0] and \
       recent['low'].iloc[-1] > recent['low'].iloc[0]:
        return "LONG"

    # Lower highs & lower lows → SHORT
    if recent['high'].iloc[-1] < recent['high'].iloc[0] and \
       recent['low'].iloc[-1] < recent['low'].iloc[0]:
        return "SHORT"

    return None

# 🔥 MAIN STRATEGY (UPGRADED)
def scan_stock(symbol):

    df = get_candles(symbol)

    if df is None or len(df) < 30:
        return None

    today = datetime.now().date()

    df_today = df[df['date'].dt.date == today].copy()

    if len(df_today) < 15:
        return None

    # Time filter
    now = datetime.now().time()
    if not (datetime.strptime("09:45","%H:%M").time() <= now <= datetime.strptime("15:00","%H:%M").time()):
        return None

    # 🔥 STEP 1: Detect Trend
    trend = get_trend(df_today)

    if trend is None:
        return None

    # 🔥 STEP 2: Find Pullback Zone (last 6 candles)
    recent = df_today.tail(6)

    # 🔥 STEP 3: Lowest volume candle
    candle = recent.loc[recent['volume'].idxmin()]

    entry = None
    sl = None
    side = None

    # 🔥 LONG SETUP
    if trend == "LONG" and candle.close < candle.open:

        entry = candle.high
        sl = candle.low
        side = "LONG"

    # 🔥 SHORT SETUP
    elif trend == "SHORT" and candle.close > candle.open:

        entry = candle.low
        sl = candle.high
        side = "SHORT"

    if entry is None:
        return None

    risk = abs(entry - sl)

    if risk <= 0:
        return None

    qty = int((CAPITAL * RISK_PER_TRADE) / risk)
    target = entry + (2 * risk) if side == "LONG" else entry - (2 * risk)

    return (side, entry, sl, target, max(qty, 1))

# PLACE TRADE
def place_trade(symbol, side, entry, sl, target, qty):

    global TRADES_COUNT

    if symbol in ORDER_PLACED:
        return

    ORDER_PLACED.add(symbol)

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

    send_telegram(f"✅ TRADE EXECUTED\n{symbol} | {side}\nQty: {qty}")

    TRADED_TODAY.add(symbol)
    TRADES_COUNT += 1

# BOT LOOP
def bot_loop():

    symbols = get_nifty200()
    load_tokens(symbols)

    send_telegram("🚀 Bot Started (TREND BASED)")

    while True:

        try:

            for symbol in symbols:

                if symbol in TRADED_TODAY:
                    continue

                if TRADES_COUNT >= MAX_TRADES:
                    continue

                signal = scan_stock(symbol)

                if signal:

                    side, entry, sl, target, qty = signal

                    # ALERT
                    send_telegram(
                        f"{'🟢 LONG' if side=='LONG' else '🔴 SHORT'} SETUP\n"
                        f"{symbol}\n"
                        f"Entry: {round(entry,2)}\n"
                        f"SL: {round(sl,2)}\n"
                        f"Target: {round(target,2)}\n"
                        f"Qty: {qty}"
                    )

                    # WAIT FOR BREAKOUT
                    ltp = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]

                    if side == "LONG" and ltp > entry:
                        place_trade(symbol, side, entry, sl, target, qty)

                    elif side == "SHORT" and ltp < entry:
                        place_trade(symbol, side, entry, sl, target, qty)

            time.sleep(30)

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

@app.route("/")
def home():
    return "Bot Running"

thread = threading.Thread(target=bot_loop)
thread.daemon = True
thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
