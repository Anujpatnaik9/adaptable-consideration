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

# ================= SECTORS =================
SECTOR_STOCKS = {
    "AUTO": ["MARUTI","TATAMOTORS","M&M","EICHERMOT","HEROMOTOCO","TVSMOTOR","ASHOKLEY","BAJAJ-AUTO","MRF","BALKRISIND","BOSCHLTD","MOTHERSON","EXIDEIND"],
    "PHARMA": ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN","AUROPHARMA","ALKEM","BIOCON","TORNTPHARM","ZYDUSLIFE","GLENMARK","ABBOTINDIA"],
    "BANK": ["HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK","SBIN","INDUSINDBK","BANDHANBNK","BAJFINANCE","LICHSGFIN","CHOLAFIN","BAJAJFINSV","RBLBANK","PNB","BANKBARODA","IDFCFIRSTB","FEDERALBNK","CANBK","MUTHOOTFIN","AUBANK","MANAPPURAM"],
    "IT": ["TCS","INFY","HCLTECH","WIPRO","TECHM","LTIM","PERSISTENT","MPHASIS","COFORGE"],
    "METAL": ["TATASTEEL","JSWSTEEL","HINDALCO","VEDL","SAIL"],
    "FMCG": ["ITC","HINDUNILVR","NESTLEIND","BRITANNIA","DABUR","GODREJCP","MARICO","COLPAL","UBL"],
    "ENERGY": ["RELIANCE","ONGC","IOC","BPCL","GAIL"],
    "REALTY": ["DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","PRESTIGE"],
    "FINANCE": ["BAJFINANCE","BAJAJFINSV","CHOLAFIN","MUTHOOTFIN"],
    "PSU": ["BEL","HAL","BHEL","COALINDIA"]
}

# ================= TELEGRAM =================
def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# ================= STRATEGY =================
def check_signal(df):
    if len(df) < 5:
        return None

    last = df.iloc[-1]
    lowest_vol = df["volume"].min()

    if DIRECTION == "LONG":
        if last["close"] < last["open"] and last["volume"] <= lowest_vol:
            return "LONG"

    if DIRECTION == "SHORT":
        if last["close"] > last["open"] and last["volume"] <= lowest_vol:
            return "SHORT"

    return None

# ================= MAIN =================
def run_bot():
    send_telegram("🚀 V5.6 BOT STARTED (DEBUG MODE)")

    while True:
        try:
            wait_for_candle_close()

            read_telegram()

            stocks_to_scan = []
            for sector in SELECTED_SECTORS:
                stocks_to_scan.extend(SECTOR_STOCKS.get(sector, []))

            for symbol in set(stocks_to_scan):

                token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

                now = datetime.now(IST)

                data = kite.historical_data(
                    token,
                    now.replace(hour=9, minute=15),
                    now,
                    "5minute"
                )

                df = pd.DataFrame(data)

                # ================= DEBUG ADDED =================
                print("\n============================")
                print("DEBUG:", symbol)
                print(df.tail(5))
                print("Lowest Volume:", df["volume"].min())
                print("Last Candle Volume:", df.iloc[-1]["volume"])
                print("============================\n")
                # ==============================================

                signal = check_signal(df)

                if signal and symbol not in PENDING_SIGNALS:

                    last = df.iloc[-1]

                    PENDING_SIGNALS[symbol] = {
                        "side": signal,
                        "sl": last["low"] if signal=="LONG" else last["high"]
                    }

                    send_telegram(f"📊 ALERT: {symbol} {signal}\nReply YES {symbol}")

        except Exception as e:
            print("Error:", e)
            time.sleep(10)
