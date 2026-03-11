from flask import Flask
import requests
import threading
import time
import os
from datetime import datetime
import pytz
import pandas as pd
from kiteconnect import KiteConnect

app = Flask(__name__)

# ---------------------------------
# ENV VARIABLES
# ---------------------------------

API_KEY = os.environ.get("KITE_API_KEY")
API_SECRET = os.environ.get("KITE_API_SECRET")
REQUEST_TOKEN = os.environ.get("REQUEST_TOKEN")

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

RISK_PER_TRADE = 5000

sent_alerts = set()

# ---------------------------------
# ZERODHA LOGIN
# ---------------------------------

kite = KiteConnect(api_key=API_KEY)

data = kite.generate_session(REQUEST_TOKEN, api_secret=API_SECRET)

kite.set_access_token(data["access_token"])

# ---------------------------------
# TELEGRAM
# ---------------------------------

def send_telegram(msg):

    try:

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg
        }

        requests.post(url, data=payload)

    except Exception as e:

        print("Telegram error:", e)


# ---------------------------------
# GET NIFTY200
# ---------------------------------

def get_nifty200():

    try:

        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20200"

        headers = {"User-Agent": "Mozilla/5.0"}

        session = requests.Session()

        session.get("https://www.nseindia.com", headers=headers)

        data = session.get(url, headers=headers).json()

        stocks = []

        for item in data["data"]:

            stocks.append("NSE:" + item["symbol"])

        return stocks

    except Exception as e:

        print("Error loading Nifty200:", e)

        return []


STOCKS = get_nifty200()


# ---------------------------------
# VWAP
# ---------------------------------

def calculate_vwap(df):

    tp = (df['high'] + df['low'] + df['close']) / 3

    vwap = (tp * df['volume']).cumsum() / df['volume'].cumsum()

    return float(vwap.iloc[-1])


# ---------------------------------
# SCANNER
# ---------------------------------

def scan():

    send_telegram("✅ Zerodha Intraday Scanner Started")

    ist = pytz.timezone("Asia/Kolkata")

    while True:

        now = datetime.now(ist)

        if now.hour < 9 or now.hour > 15:

            time.sleep(60)

            continue

        if now.hour == 9 and now.minute < 30:

            time.sleep(60)

            continue

        trades = []

        for stock in STOCKS:

            try:

                instrument = kite.ltp(stock)

                instrument_token = list(instrument.values())[0]["instrument_token"]

                data = kite.historical_data(

                    instrument_token,

                    from_date=datetime.now() - pd.Timedelta("1D"),

                    to_date=datetime.now(),

                    interval="5minute"

                )

                df = pd.DataFrame(data)

                if len(df) < 6:

                    continue

                df = df.tail(6)

                c1 = df.iloc[-3]
                c2 = df.iloc[-2]
                c3 = df.iloc[-1]

                open1, close1 = c1["open"], c1["close"]
                open2, close2 = c2["open"], c2["close"]
                open3, close3 = c3["open"], c3["close"]

                vol1, vol2, vol3 = c1["volume"], c2["volume"], c3["volume"]

                vwap = calculate_vwap(df)

                high3 = c3["high"]
                low3 = c3["low"]

                green1 = close1 > open1
                green2 = close2 > open2
                red3 = close3 < open3

                red1 = close1 < open1
                red2 = close2 < open2
                green3 = close3 > open3

                vol_avg = df["volume"].mean()

                if vol_avg == 0:

                    continue

                rel_vol = vol3 / vol_avg

                # LONG SETUP
                if green1 and green2 and red3:

                    if vol3 < vol1 and vol3 < vol2:

                        if close3 > vwap and rel_vol >= 1.5:

                            entry = high3
                            stop = low3

                            risk = entry - stop

                            if risk <= 0:

                                continue

                            target = entry + (risk * 2)

                            qty = int(RISK_PER_TRADE / risk)

                            msg = f"""
🚀 LONG TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Qty: {qty}
"""

                            trades.append((rel_vol, stock, msg))

                # SHORT SETUP
                if red1 and red2 and green3:

                    if vol3 < vol1 and vol3 < vol2:

                        if close3 < vwap and rel_vol >= 1.5:

                            entry = low3
                            stop = high3

                            risk = stop - entry

                            if risk <= 0:

                                continue

                            target = entry - (risk * 2)

                            qty = int(RISK_PER_TRADE / risk)

                            msg = f"""
🔻 SHORT TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Qty: {qty}
"""

                            trades.append((rel_vol, stock, msg))

            except Exception as e:

                print("Scan error:", stock, e)

        trades.sort(reverse=True)

        top = trades[:10]

        for t in top:

            score, stock, msg = t

            if stock not in sent_alerts:

                send_telegram(msg)

                sent_alerts.add(stock)

        time.sleep(60)


# ---------------------------------
# FLASK
# ---------------------------------

@app.route("/")
def home():

    return "Scanner Running"


def start():

    scan()


thread = threading.Thread(target=start)

thread.daemon = True

thread.start()

if __name__ == "__main__":

    app.run(host="0.0.0.0", port=8080)
