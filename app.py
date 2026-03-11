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

# -------------------------------
# FETCH NIFTY 200 STOCK LIST
# -------------------------------

def get_nifty200():

    try:
        url = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%20200"

        headers = {"User-Agent": "Mozilla/5.0"}

        session = requests.Session()

        session.get("https://www.nseindia.com", headers=headers)

        data = session.get(url, headers=headers).json()

        stocks = []

        for item in data["data"]:
            stocks.append(item["symbol"] + ".NS")

        return stocks

    except Exception as e:
        print("Error loading Nifty200:", e)
        return []


STOCKS = get_nifty200()


# -------------------------------
# TELEGRAM FUNCTION
# -------------------------------

def send_telegram(message):

    try:

        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

        payload = {
            "chat_id": CHAT_ID,
            "text": message
        }

        requests.post(url, data=payload)

    except Exception as e:

        print("Telegram error:", e)


# -------------------------------
# VWAP CALCULATION
# -------------------------------

def calculate_vwap(df):

    tp = (df['High'] + df['Low'] + df['Close']) / 3

    vwap = (tp * df['Volume']).cumsum() / df['Volume'].cumsum()

    return float(vwap.iloc[-1])


# -------------------------------
# MAIN SCANNER
# -------------------------------

def scan():

    send_telegram("✅ Intraday Scanner Started")

    ist = pytz.timezone("Asia/Kolkata")

    while True:

        now = datetime.now(ist)

        # Market hours check
        if now.hour < 9 or now.hour > 15:

            time.sleep(60)
            continue

        # Ignore first 3 candles (before 9:30)
        if now.hour == 9 and now.minute < 30:

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

                open1 = float(c1["Open"])
                close1 = float(c1["Close"])

                open2 = float(c2["Open"])
                close2 = float(c2["Close"])

                open3 = float(c3["Open"])
                close3 = float(c3["Close"])

                vol1 = float(c1["Volume"])
                vol2 = float(c2["Volume"])
                vol3 = float(c3["Volume"])

                vol_avg = float(df["Volume"].mean())

                if vol_avg == 0:

                    continue

                rel_vol = vol3 / vol_avg

                vwap = calculate_vwap(df)

                high3 = float(c3["High"])
                low3 = float(c3["Low"])

                green1 = close1 > open1
                green2 = close2 > open2

                red1 = close1 < open1
                red2 = close2 < open2

                green3 = close3 > open3
                red3 = close3 < open3

                # -------------------------------
                # LONG SETUP
                # -------------------------------

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

                            message = f"""
🚀 LONG TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {qty}

Relative Volume: {round(rel_vol,2)}
VWAP: {round(vwap,2)}
"""

                            trade_list.append((rel_vol, stock, message))

                # -------------------------------
                # SHORT SETUP
                # -------------------------------

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

                            message = f"""
🔻 SHORT TRADE

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Position Size: {qty}

Relative Volume: {round(rel_vol,2)}
VWAP: {round(vwap,2)}
"""

                            trade_list.append((rel_vol, stock, message))

            except Exception as e:

                print("Error scanning", stock, e)

        trade_list.sort(reverse=True)

        top_trades = trade_list[:10]

        for trade in top_trades:

            score, stock, msg = trade

            if stock not in sent_alerts:

                send_telegram(msg)

                sent_alerts.add(stock)

        time.sleep(60)


# -------------------------------
# FLASK SERVER
# -------------------------------

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
