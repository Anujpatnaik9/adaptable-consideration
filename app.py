from flask import Flask
import requests
import yfinance as yf
import threading
import time
import os

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

sent_signals = set()

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
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        print("Telegram error")


def scan_market():

    send_telegram("✅ Scanner Started")

    while True:

        for stock in NIFTY200:

            try:

                df = yf.download(
                    stock,
                    period="1d",
                    interval="5m",
                    progress=False,
                    threads=False
                )

                if df is None or df.empty:
                    continue

                df = df.tail(3)

                if len(df) < 3:
                    continue

                # SAFE value extraction
                c1 = df.iloc[-3]
                c2 = df.iloc[-2]
                c3 = df.iloc[-1]

                open1 = float(c1["Open"].item())
                close1 = float(c1["Close"].item())

                open2 = float(c2["Open"].item())
                close2 = float(c2["Close"].item())

                open3 = float(c3["Open"].item())
                close3 = float(c3["Close"].item())

                vol1 = float(c1["Volume"].item())
                vol2 = float(c2["Volume"].item())
                vol3 = float(c3["Volume"].item())

                high3 = float(c3["High"].item())
                low3 = float(c3["Low"].item())

                green1 = close1 > open1
                green2 = close2 > open2
                red3 = close3 < open3

                red1 = close1 < open1
                red2 = close2 < open2
                green3 = close3 > open3

                # LONG
                if green1 and green2 and red3 and vol3 < vol1 and vol3 < vol2:

                    entry = high3
                    stop = low3
                    risk = entry - stop

                    if risk <= 0:
                        continue

                    target = entry + risk * 2

                    signal = f"{stock}_LONG"

                    if signal not in sent_signals:

                        sent_signals.add(signal)

                        msg = f"""
🚀 LONG SETUP
Stock: {stock}

Entry: {round(entry,2)}
Stop: {round(stop,2)}
Target: {round(target,2)}
"""

                        send_telegram(msg)

                # SHORT
                if red1 and red2 and green3 and vol3 < vol1 and vol3 < vol2:

                    entry = low3
                    stop = high3
                    risk = stop - entry

                    if risk <= 0:
                        continue

                    target = entry - risk * 2

                    signal = f"{stock}_SHORT"

                    if signal not in sent_signals:

                        sent_signals.add(signal)

                        msg = f"""
🔻 SHORT SETUP
Stock: {stock}

Entry: {round(entry,2)}
Stop: {round(stop,2)}
Target: {round(target,2)}
"""

                        send_telegram(msg)

            except Exception as e:
                print("Error with", stock, e)

        print("Scanning market...")
        time.sleep(300)


@app.route("/")
def home():
    return "Scanner Running"


def start_scanner():
    scan_market()


threading.Thread(target=start_scanner, daemon=True).start()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
