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

# MARKET DIRECTION
def get_market_direction():
    try:
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        headers = {"User-Agent": "Mozilla/5.0"}
        data = requests.get(url, headers=headers).json()

        adv = data["advance"]["advances"]
        dec = data["advance"]["declines"]

        if adv > dec:
            return "LONG"
        elif dec > adv:
            return "SHORT"
    except:
        pass

    return None

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

# MAIN STRATEGY
def scan_stock(symbol, direction):

    df = get_candles(symbol)

    if df is None or len(df) < 20:
        return None

    today = datetime.now().date()

    df_today = df[df['date'].dt.date == today].copy()
    df_today = df_today[df_today['date'].dt.time >= datetime.strptime("09:15","%H:%M").time()]

    if len(df_today) < 3:
        return None

    # Time filter
    now = datetime.now().time()
    if not (datetime.strptime("09:30","%H:%M").time() <= now <= datetime.strptime("12:55","%H:%M").time()):
        return None

    # Previous day levels
    df_prev = df[df['date'].dt.date < today]
    if df_prev.empty:
        return None

    pdh = df_prev.high.max()
    pdl = df_prev.low.min()

    # Find lowest volume candle
    candle = df_today.loc[df_today['volume'].idxmin()]

    # LONG
    if direction == "LONG":

        if candle.close < candle.open and candle.high >= (0.995 * pdh):

            entry = candle.high
            sl = candle.low
            risk = entry - sl

            if risk <= 0:
                return None

            qty = int((CAPITAL * RISK_PER_TRADE) / risk)
            target = entry + (2 * risk)

            return ("LONG", entry, sl, target, max(qty, 1))

    # SHORT
    if direction == "SHORT":

        if candle.close > candle.open and candle.low <= (1.005 * pdl):

            entry = candle.low
            sl = candle.high
            risk = sl - entry

            if risk <= 0:
                return None

            qty = int((CAPITAL * RISK_PER_TRADE) / risk)
            target = entry - (2 * risk)

            return ("SHORT", entry, sl, target, max(qty, 1))

    return None

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

    send_telegram(f"✅ TRADE EXECUTED: {symbol} | {side} | Qty: {qty}")

    TRADED_TODAY.add(symbol)
    TRADES_COUNT += 1

# BOT LOOP
def bot_loop():

    symbols = get_nifty200()
    load_tokens(symbols)

    send_telegram("🚀 Bot Started")

    while True:

        try:
            direction = get_market_direction()

            if direction is None:
                time.sleep(30)
                continue

            for symbol in symbols:

                if symbol in TRADED_TODAY:
                    continue

                if TRADES_COUNT >= MAX_TRADES:
                    continue

                signal = scan_stock(symbol, direction)

                if signal:

                    side, entry, sl, target, qty = signal

                    # Alert
                    send_telegram(
                        f"{'🟢 LONG' if side=='LONG' else '🔴 SHORT'} SETUP\n"
                        f"{symbol}\nEntry: {round(entry,2)}\nSL: {round(sl,2)}\nTarget: {round(target,2)}"
                    )

                    # WAIT FOR BREAKOUT
                    ltp = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]

                    if side == "LONG" and ltp > entry:
                        place_trade(symbol, side, entry, sl, target, qty)

                    elif side == "SHORT" and ltp < entry:
                        place_trade(symbol, side, entry, sl, target, qty)

            time.sleep(30)

        except:
            time.sleep(10)

@app.route("/")
def home():
    return "Bot Running"

thread = threading.Thread(target=bot_loop)
thread.daemon = True
thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
