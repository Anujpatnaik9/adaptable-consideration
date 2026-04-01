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

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

IST = pytz.timezone("Asia/Kolkata")

# ================= GLOBALS =================
LAST_UPDATE_ID = None
SELECTED_SECTORS = set()
DIRECTION = None
LAST_PROCESSED_MINUTE = -1
ALERTED_STOCKS = set()

# ================= SECTORS =================
SECTOR_STOCKS = {
    "AUTO" : ["MARUTI","M&M","EICHERMOT","HEROMOTOCO","TVSMOTOR","ASHOKLEY","BAJAJ-AUTO","MRF","BALKRISIND","BOSCHLTD","MOTHERSON","EXIDEIND"],
    "PHARMA" : ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN","AUROPHARMA","ALKEM","BIOCON","TORNTPHARM","ZYDUSLIFE","GLENMARK","ABBOTINDIA"],
    "BANK" : ["HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK","SBIN","INDUSINDBK","BANDHANBNK","BAJFINANCE","LICHSGFIN","CHOLAFIN","BAJAJFINSV","RBLBANK","PNB","BANKBARODA","IDFCFIRSTB","FEDERALBNK","CANBK","MUTHOOTFIN","AUBANK","MANAPPURAM"],
    "IT" : ["TCS","INFY","HCLTECH","WIPRO","TECHM","LTM","PERSISTENT","MPHASIS","COFORGE"],
    "METAL" : ["TATASTEEL","JSWSTEEL","HINDALCO","VEDL","SAIL"],
    "FMCG" : ["ITC","HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","GODREJCP","MARICO","COLPAL","UBL"],
    "ENERGY" : ["RELIANCE","ONGC","IOC","BPCL","GAIL"],
    "REALTY" : ["DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","PRESTIGE"],
    "FINANCE": ["BAJFINANCE","BAJAJFINSV","CHOLAFIN","MUTHOOTFIN"],
    "PSU" : ["BEL","HAL","BHEL","COALINDIA"]
}

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

def read_telegram():
    global LAST_UPDATE_ID, DIRECTION

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        res = requests.get(url, timeout=10).json()

        if "result" not in res:
            return

        for item in res["result"]:
            uid = item["update_id"]

            if LAST_UPDATE_ID and uid <= LAST_UPDATE_ID:
                continue

            LAST_UPDATE_ID = uid

            if "message" not in item:
                continue

            msg = item["message"].get("text", "").upper().strip()

            if msg == "CLEAR":
                SELECTED_SECTORS.clear()
                send_telegram("❌ All sectors cleared")
                return

            words = msg.split()

            if len(words) == 2 and words[0] in SECTOR_STOCKS:
                sector = words[0]
                direction = words[1]

                SELECTED_SECTORS.add(sector)
                DIRECTION = direction

                send_telegram(f"✅ Added {sector} | Direction: {direction}")

    except Exception as e:
        send_telegram(f"Telegram error: {e}")

# ================= STRATEGY =================
def check_signal(df):
    if len(df) < 7:
        return None

    # ✅ Remove last unstable candle
    df = df[:-1]

    last = df.iloc[-1]
    prev = df.iloc[:-1]

    # ✅ Strict lowest volume of day
    if last["volume"] != prev["volume"].min():
        return None

    # ✅ Extra safety: must be lower than previous candle
    if last["volume"] >= df.iloc[-2]["volume"]:
        return None

    # LONG (HIGH)
    if DIRECTION == "HIGH" and last["close"] < last["open"]:
        return {
            "side": "LONG",
            "entry": last["high"],
            "sl": last["low"]
        }

    # SHORT (LOW)
    if DIRECTION == "LOW" and last["close"] > last["open"]:
        return {
            "side": "SHORT",
            "entry": last["low"],
            "sl": last["high"]
        }

    return None

# ================= MAIN LOOP =================
def run_bot():
    global LAST_PROCESSED_MINUTE

    send_telegram("🚀 PRO BOT STARTED (45s DELAY | ACCURATE MODE)")

    while True:
        try:
            read_telegram()

            if not SELECTED_SECTORS or not DIRECTION:
                time.sleep(1)
                continue

            now = datetime.now(IST)

            # ✅ Run once per candle AFTER 45 sec
            if now.minute % 5 == 0 and now.second >= 45 and now.minute != LAST_PROCESSED_MINUTE:
                LAST_PROCESSED_MINUTE = now.minute

                stocks = []
                for s in SELECTED_SECTORS:
                    stocks.extend(SECTOR_STOCKS.get(s, []))

                for symbol in set(stocks):
                    try:
                        token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

                        data = kite.historical_data(
                            token,
                            now.replace(hour=9, minute=15, second=0, microsecond=0),
                            now,
                            "5minute"
                        )

                        df = pd.DataFrame(data)
                        df.columns = ["date","open","high","low","close","volume"]

                        sig = check_signal(df)

                        if sig and symbol not in ALERTED_STOCKS:
                            ALERTED_STOCKS.add(symbol)

                            send_telegram(
                                f"🚨 ALERT: {symbol} {sig['side']}\n"
                                f"Strict Lowest Volume\n"
                                f"Entry: {sig['entry']} | SL: {sig['sl']}"
                            )

                    except Exception as e:
                        send_telegram(f"Data error {symbol}: {e}")

            time.sleep(1)

        except Exception as e:
            send_telegram(f"Main error: {e}")
            time.sleep(5)

# ================= START =================
if __name__ == "__main__":
    run_bot()
