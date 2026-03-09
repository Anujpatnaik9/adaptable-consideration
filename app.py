from flask import Flask
import requests
import yfinance as yf
import pandas as pd
import threading
import time
import os

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

NIFTY200 = [
"RELIANCE.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","TCS.NS",
"LT.NS","SBIN.NS","AXISBANK.NS","KOTAKBANK.NS","ITC.NS",
"TATAMOTORS.NS","BAJFINANCE.NS","MARUTI.NS","ASIANPAINT.NS",
"HCLTECH.NS","ULTRACEMCO.NS","SUNPHARMA.NS","TITAN.NS",
"NESTLEIND.NS","POWERGRID.NS","ADANIENT.NS","ADANIPORTS.NS",
"ONGC.NS","COALINDIA.NS","NTPC.NS","WIPRO.NS","TECHM.NS",
"INDUSINDBK.NS","JSWSTEEL.NS","HINDALCO.NS"
]

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    requests.post(url, data=data)

def scan_market():
    while True:
        for stock in NIFTY200:
            try:
                data = yf.download(stock, period="1d", interval="5m")

                if len(data) < 6:
                    continue

                # Last 3 candles
                c1 = data.iloc[-3]
                c2 = data.iloc[-2]
                c3 = data.iloc[-1]

                # Candle colors
                green1 = c1["Close"] > c1["Open"]
                green2 = c2["Close"] > c2["Open"]
                green3 = c3["Close"] > c3["Open"]

                red1 = c1["Close"] < c1["Open"]
                red2 = c2["Close"] < c2["Open"]
                red3 = c3["Close"] < c3["Open"]

                # LONG pattern
                if green1 and green2 and red3:
                    if c3["Volume"] < c1["Volume"] and c3["Volume"] < c2["Volume"]:

                        entry = c3["High"]
                        stop = c3["Low"]
                        risk = entry - stop

                        if risk == 0:
                            continue

                        target = entry + (risk * 2)
                        position_size = int(5000 / risk)

                        msg = f"""
🚀 LONG SETUP

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {position_size} shares
"""

                        send_telegram(msg)

                # SHORT pattern
                if red1 and red2 and green3:
                    if c3["Volume"] < c1["Volume"] and c3["Volume"] < c2["Volume"]:

                        entry = c3["Low"]
                        stop = c3["High"]
                        risk = stop - entry

                        if risk == 0:
                            continue

                        target = entry - (risk * 2)
                        position_size = int(5000 / risk)

                        msg = f"""
🔻 SHORT SETUP

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {position_size} shares
"""

                        send_telegram(msg)

            except Exception as e:
                print(e)

        # Scan every 5 minutes
        time.sleep(300)

@app.route("/")
def home():
    return "NIFTY Scanner Running"

def start_scanner():
    scan_market()

thread = threading.Thread(target=start_scanner)
thread.start()

if __name__ == "__main__":
    app.run()
