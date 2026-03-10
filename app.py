import os
import time
import requests
import yfinance as yf

# Telegram credentials from Railway variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Stocks to scan
stocks = [
    "RELIANCE.NS",
    "HDFCBANK.NS",
    "ICICIBANK.NS",
    "TCS.NS",
    "INFY.NS",
    "SBIN.NS",
    "AXISBANK.NS",
    "ITC.NS",
    "LT.NS",
    "BAJFINANCE.NS"
]


def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("Telegram error:", e)


def scan_market():
    print("Scanner started...")

    while True:
        try:
            for stock in stocks:

                data = yf.download(stock, period="1d", interval="5m")

                if len(data) < 2:
                    continue

                last_close = data["Close"].iloc[-1]
                prev_close = data["Close"].iloc[-2]

                change = ((last_close - prev_close) / prev_close) * 100

                if change > 1:
                    message = f"📈 BUY SIGNAL\n\nStock: {stock}\nMove: {round(change,2)}%"
                    print(message)
                    send_telegram(message)

                if change < -1:
                    message = f"📉 SELL SIGNAL\n\nStock: {stock}\nMove: {round(change,2)}%"
                    print(message)
                    send_telegram(message)

            print("Scan complete. Waiting 60 seconds...\n")

        except Exception as e:
            print("Scanner error:", e)

        time.sleep(60)


if __name__ == "__main__":
    scan_market()
