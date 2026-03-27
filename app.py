import os, time, requests
import pandas as pd
from datetime import datetime
import pytz
from kiteconnect import KiteConnect

# ================= CONFIG =================
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TOTAL_CAPITAL = 500000
RISK_PER_TRADE = 5000
MAX_TRADES = 2
EXIT_TIME = datetime.strptime("15:15", "%H:%M").time()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

IST = pytz.timezone("Asia/Kolkata")

# ================= GLOBALS =================
TRADES_COUNT = 0
ACTIVE_TRADES = {}
PENDING_SIGNALS = {}
LAST_UPDATE_ID = None
SELECTED_SECTORS = set()
DIRECTION = None

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

# ================= STRATEGY =================
def check_signal(df, symbol):

    if len(df) < 5:
        return None

    last = df.iloc[-1]
    candle_no = len(df)

    # ===== DEBUG PRINTS =====
    day_low_vol = df["volume"].min()
    current_vol = last["volume"]

    print(f"\n📊 {symbol}")
    print(f"Candle #{candle_no}")
    print(f"Current Volume = {current_vol}")
    print(f"Day Lowest Volume = {day_low_vol}")

    # ORIGINAL LOGIC (UNCHANGED)
    is_lowest = current_vol <= day_low_vol

    is_green = last["close"] > last["open"]
    is_red = last["close"] < last["open"]

    print(f"Is Lowest? {is_lowest}")
    print(f"Is Green? {is_green} | Is Red? {is_red}")
    print(f"Direction = {DIRECTION}")

    # ===== SHORT =====
    if DIRECTION == "SHORT" and is_green and is_lowest:
        print(f"🔥 SIGNAL DETECTED (SHORT) on Candle #{candle_no}")

        entry = round(last["low"], 2)
        sl = round(last["high"], 2)
        risk = round(sl - entry, 2)

        if risk <= 0:
            return None

        t1 = round(entry - risk * 2, 2)

        return {
            "side": "SHORT",
            "entry": entry,
            "sl": sl,
            "t1": t1,
            "risk": risk,
            "candle_no": candle_no,
        }

    # ===== LONG =====
    if DIRECTION == "LONG" and is_red and is_lowest:
        print(f"🔥 SIGNAL DETECTED (LONG) on Candle #{candle_no}")

        entry = round(last["high"], 2)
        sl = round(last["low"], 2)
        risk = round(entry - sl, 2)

        if risk <= 0:
            return None

        t1 = round(entry + risk * 2, 2)

        return {
            "side": "LONG",
            "entry": entry,
            "sl": sl,
            "t1": t1,
            "risk": risk,
            "candle_no": candle_no,
        }

    print("❌ No Signal")
    return None

# ================= MAIN TEST LOOP =================
def run_debug(symbol="BANDHANBNK"):

    print("🚀 DEBUG MODE STARTED")

    global DIRECTION
    DIRECTION = "SHORT"  # Change to LONG if needed

    while True:
        try:
            now = datetime.now(IST)

            token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

            data = kite.historical_data(
                token,
                now.replace(hour=9, minute=15, second=0, microsecond=0),
                now,
                "5minute"
            )

            df = pd.DataFrame(data)
            df.columns = ["date", "open", "high", "low", "close", "volume"]

            check_signal(df, symbol)

            time.sleep(10)

        except Exception as e:
            print("Error:", e)
            time.sleep(5)

# ================= START =================
if __name__ == "__main__":
    run_debug()
