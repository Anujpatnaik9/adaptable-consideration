from flask import Flask
import requests
import yfinance as yf
import pandas as pd
import threading
import time
import os
from datetime import datetime
import pytz

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Capital settings
CAPITAL = 500000
RISK_PER_TRADE = 5000

# NIFTY 200 LIQUID STOCKS
STOCKS = [
"RELIANCE.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","TCS.NS",
"LT.NS","SBIN.NS","AXISBANK.NS","KOTAKBANK.NS","ITC.NS",
"TATAMOTORS.NS","BAJFINANCE.NS","MARUTI.NS","ASIANPAINT.NS",
"HCLTECH.NS","ULTRACEMCO.NS","SUNPHARMA.NS","TITAN.NS",
"NESTLEIND.NS","POWERGRID.NS","ADANIENT.NS","ADANIPORTS.NS",
"ONGC.NS","COALINDIA.NS","NTPC.NS","WIPRO.NS","TECHM.NS",
"INDUSINDBK.NS","JSWSTEEL.NS","HINDALCO.NS","DRREDDY.NS",
"CIPLA.NS","DIVISLAB.NS","BRITANNIA.NS","HEROMOTOCO.NS",
"EICHERMOT.NS","GRASIM.NS","TATACONSUM.NS","BPCL.NS",
"SHREECEM.NS","SBILIFE.NS","BAJAJFINSV.NS","UPL.NS",
"HAVELLS.NS","DABUR.NS","GODREJCP.NS","PIDILITIND.NS",
"COLPAL.NS","AMBUJACEM.NS","ADANIGREEN.NS","ADANITRANS.NS"
]

def send_telegram(message):

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, data=payload)
    except:
        print("Telegram error")

def calculate_vwap(df):

    tp = (df['High'] + df['Low'] + df['Close']) / 3
    vwap = (tp * df['Volume']).cumsum() / df['Volume'].cumsum()

    return vwap.iloc[-1]

def scan():

    send_telegram("✅ Intraday Scanner Started")

    ist = pytz.timezone("Asia/Kolkata")

    while True:

        now = datetime.now(ist)

        if now.hour < 9 or now.hour > 15:
            time.sleep(60)
            continue

        for stock in STOCKS:

            try:

                data = yf.download(
                    stock,
                    period="1d",
                    interval="5m",
                    progress=False
                )

                if data.empty or len(data) < 6:
                    continue

                df = data.tail(6)

                c1 = df.iloc[-3]
                c2 = df.iloc[-2]
                c3 = df.iloc[-1]

                vol_avg = df["Volume"].mean()
                rel_vol = c3["Volume"] / vol_avg

                vwap = calculate_vwap(df)

                open1, close1 = c1["Open"], c1["Close"]
                open2, close2 = c2["Open"], c2["Close"]
                open3, close3 = c3["Open"], c3["Close"]

                high3 = c3["High"]
                low3 = c3["Low"]

                green1 = close1 > open1
                green2 = close2 > open2
                red1 = close1 < open1
                red2 = close2 < open2

                green3 = close3 > open3
                red3 = close3 < open3

                # LONG SETUP
                if green1 and green2 and red3:

                    if c3["Volume"] < c1["Volume"] and c3["Volume"] < c2["Volume"]:

                        if close3 > vwap and rel_vol >= 1.5:

                            entry = high3
                            stop = low3
                            risk = entry - stop

                            if risk <= 0:
                                continue

                            target = entry + (risk * 2)

                            qty = int(RISK_PER_TRADE / risk)

                            probability = round(60 + (rel_vol * 10),1)

                            message = f"""
🚀 LONG TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {qty}

Relative Volume: {round(rel_vol,2)}
VWAP: {round(vwap,2)}

Probability: {probability}%
"""

                            send_telegram(message)

                # SHORT SETUP
                if red1 and red2 and green3:

                    if c3["Volume"] < c1["Volume"] and c3["Volume"] < c2["Volume"]:

                        if close3 < vwap and rel_vol >= 1.5:

                            entry = low3
                            stop = high3
                            risk = stop - entry

                            if risk <= 0:
                                continue

                            target = entry - (risk * 2)

                            qty = int(RISK_PER_TRADE / risk)

                            probability = round(60 + (rel_vol * 10),1)

                            message = f"""
🔻 SHORT TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {qty}

Relative Volume: {round(rel_vol,2)}
VWAP: {round(vwap,2)}

Probability: {probability}%
"""

                            send_telegram(message)

            except Exception as e:

                print("Error:", stock, e)

        print("Scanning market...")

        time.sleep(60)

@app.route("/")
def home():

    return "Intraday Scanner Running"

def start():

    scan()

thread = threading.Thread(target=start)
thread.start()

if __name__ == "__main__":
    app.run()
