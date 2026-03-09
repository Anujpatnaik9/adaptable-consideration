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

    send_telegram("✅ Scanner started successfully")

    while True:

        for stock in NIFTY200:

            try:

                data = yf.download(stock, period="1d", interval="5m", progress=False)

                if data.empty or len(data) < 3:
                    continue

                # Last 3 candles
                c1 = data.iloc[-3]
                c2 = data.iloc[-2]
                c3 = data.iloc[-1]

                open1 = float(c1["Open"])
                close1 = float(c1["Close"])

                open2 = float(c2["Open"])
                close2 = float(c2["Close"])

                open3 = float(c3["Open"])
                close3 = float(c3["Close"])

                vol1 = float(c1["Volume"])
                vol2 = float(c2["Volume"])
                vol3 = float(c3["Volume"])

                high3 = float(c3["High"])
                low3 = float(c3["Low"])

                green1 = close1 > open1
                green2 = close2 > open2
                red3 = close3 < open3

                red1 = close1 < open1
                red2 = close2 < open2
                green3 = close3 > open3

                # LONG setup
                if green1 and green2 and red3:

                    if vol3 < vol1 and vol3 < vol2:

                        entry = high3
                        stop = low3
                        risk = entry - stop

                        if risk <= 0:
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

                # SHORT setup
                if red1 and red2 and green3:

                    if vol3 < vol1 and vol3 < vol2:

                        entry = low3
                        stop = high3
                        risk = stop - entry

                        if risk <= 0:
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

                print("Error with", stock, ":", e)

        print("Scanning market...")

        time.sleep(300)

@app.route("/")
def home():
    return "Scanner Running"

def start_scanner():
    scan_market()

thread = threading.Thread(target=start_scanner)
thread.start()

if __name__ == "__main__":
    app.run()
