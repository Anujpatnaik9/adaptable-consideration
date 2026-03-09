from flask import Flask
import requests
import yfinance as yf
import pandas as pd
import threading
import time

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

NIFTY200 = [
"RELIANCE.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","TCS.NS",
"LT.NS","SBIN.NS","AXISBANK.NS","KOTAKBANK.NS","ITC.NS"
]

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    requests.post(url, data=data)

def scan_market():
    while True:
        for stock in NIFTY200:
            try:
                data = yf.download(stock, period="3mo", interval="1d")

                data["MA20"] = data["Close"].rolling(20).mean()
                data["MA50"] = data["Close"].rolling(50).mean()

                last = data.iloc[-1]

                if last["MA20"] > last["MA50"]:
                    send_telegram(f"BUY SIGNAL: {stock}")

            except:
                pass

        time.sleep(3600)

@app.route("/")
def home():
    return "NIFTY200 Scanner Running"

def start_scanner():
    scan_market()

thread = threading.Thread(target=start_scanner)
thread.start()

if __name__ == "__main__":
    app.run()
