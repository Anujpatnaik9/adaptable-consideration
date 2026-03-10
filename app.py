from flask import Flask
import requests
import yfinance as yf
import threading
import time
import os
from datetime import datetime
import pytz

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

RISK_PER_TRADE = 5000

sent_alerts = set()

# Fetch NIFTY200 stocks
def get_nifty200():

    url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20200"

    headers = {"User-Agent": "Mozilla/5.0"}

    session = requests.Session()

    session.get("https://www.nseindia.com", headers=headers)

    data = session.get(url, headers=headers).json()

    stocks = []

    for item in data["data"]:
        stocks.append(item["symbol"] + ".NS")

    return stocks

STOCKS = get_nifty200()

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

        trade_list = []

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

                open1, close1 = c1["Open"], c1["Close"]
                open2, close2 = c2["Open"], c2["Close"]
                open3, close3 = c3["Open"], c3["Close"]

                vol1 = c1["Volume"]
                vol2 = c2["Volume"]
                vol3 = c3["Volume"]

                vol_avg = df["Volume"].mean()

                rel_vol = vol3 / vol_avg

                vwap = calculate_vwap(df)

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

                    if vol3 < vol1 and vol3 < vol2:

                        if close3 > vwap and rel_vol >= 1.5:

                            entry = high3
                            stop = low3

                            risk = entry - stop

                            if risk <= 0:
                                continue

                            target = entry + (risk * 2)

                            qty = int(RISK_PER_TRADE / risk)

                            score = rel_vol

                            trade_list.append(
                                (score, f"""
🚀 LONG TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {qty}

Relative Volume: {round(rel_vol,2)}
VWAP: {round(vwap,2)}
""")
                            )

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

                            score = rel_vol

                            trade_list.append(
                                (score, f"""
🔻 SHORT TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {qty}

Relative Volume: {round(rel_vol,2)}
VWAP: {round(vwap,2)}
""")
                            )

            except Exception as e:

                print("Error", stock, e)

        trade_list.sort(reverse=True)

        top_trades = trade_list[:10]

        for trade in top_trades:

            msg = trade[1]

            if msg not in sent_alerts:

                send_telegram(msg)

                sent_alerts.add(msg)

        time.sleep(60)

@app.route("/")
def home():

    return "Scanner Running"

def start():

    scan()

thread = threading.Thread(target=start)

thread.start()

if __name__ == "__main__":

    app.run()
