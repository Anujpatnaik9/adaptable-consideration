import os
import pandas as pd
from datetime import datetime
import pytz
import requests
from kiteconnect import KiteConnect

# ================= CONFIG =================
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

IST = pytz.timezone("Asia/Kolkata")

def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except Exception as e:
        print("Telegram error:", e)

symbol = "BANDHANBNK"

try:
    token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

    now = datetime.now(IST)
    from_time = now.replace(hour=9, minute=15, second=0, microsecond=0)

    data = kite.historical_data(token, from_time, now, "5minute")

    df = pd.DataFrame(data)
    df.columns = ["date", "open", "high", "low", "close", "volume"]

    lowest_vol = df["volume"].min()

    msg = f"📊 BANDHANBNK ANALYSIS\nLowest Volume: {lowest_vol}\n\n"

    for i, row in df.iterrows():
        time_str = row["date"].strftime("%H:%M")

        is_green = row["close"] > row["open"]
        is_lowest = row["volume"] <= lowest_vol

        msg += (
            f"{time_str} | "
            f"O:{row['open']} C:{row['close']} "
            f"V:{row['volume']} "
            f"{'GREEN' if is_green else 'RED'} | "
            f"{'LOWEST' if is_lowest else ''}\n"
        )

    send_telegram(msg)

except Exception as e:
    send_telegram(f"Error: {str(e)}")
