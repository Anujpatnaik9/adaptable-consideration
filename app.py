from flask import Flask
import requests
import yfinance as yf
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
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": msg}
        requests.post(url, data=data)
    except:
        print("Telegram send failed")

def scan_market():

    send_telegram("Bot is alive and scanning market")

    while True:

        print("Scanning market...")

        for stock in NIFTY200:

            try:

                data = yf.download(stock, period="1d", interval="5m", progress=False)

                if data is None or data.empty:
                    continue

                if len(data) < 6:
                    continue

                c1 = data.iloc[-3]
                c2 = data.iloc[-2]
                c3 = data.iloc[-1]

                o1 = float(c1["Open"])
                c1p = float(c1["Close"])
                v1 = float(c1["Volume"])

                o2 = float(c2["Open"])
                c2p = float(c2["Close"])
                v2 = float(c2["Volume"])

                o3 = float(c3["Open"])
                c3p = float(c3["Close"])
                v3 = float(c3["Volume"])

                green1 = c1p > o1
                green2 = c2p > o2
                green3 = c3p > o3

                red1 = c1p < o1
                red2 = c2p < o2
                red3 = c3p < o3

                # LONG SETUP
                if green1 and green2 and red3 and v3 < v1 and v3 < v2:

                    entry = float(c3["High"])
                    stop = float(c3["Low"])
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

                # SHORT SETUP
                if red1 and red2 and green3 and v3 < v1 and v3 < v2:

                    entry = float(c3["Low"])
                    stop = float(c3["High"])
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
                print(f"Error with {stock}: {e}")

        time.sleep(300)

@app.route("/")
def home():
    return "Scanner running"

def start_scanner():
    scan_market()

thread = threading.Thread(target=start_scanner)
thread.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
