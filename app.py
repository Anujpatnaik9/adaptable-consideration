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

def read_telegram():
    global LAST_UPDATE_ID, DIRECTION, SELECTED_SECTORS

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    res = requests.get(url).json()

    for item in res["result"]:
        update_id = item["update_id"]

        if LAST_UPDATE_ID and update_id <= LAST_UPDATE_ID:
            continue

        LAST_UPDATE_ID = update_id

        if "message" not in item or "text" not in item["message"]:
            continue

        msg = item["message"]["text"].upper()
        lines = msg.split("\n")

        for line in lines:
            words = line.strip().split()
            if len(words) < 2:
                continue

            sector = words[0]
            action = words[1]

            if sector in SECTOR_STOCKS:

                if action == "HIGH":
                    SELECTED_SECTORS.add(sector)
                    DIRECTION = "LONG"
                    send_telegram(f"{sector} added for LONG")

                elif action == "LOW":
                    SELECTED_SECTORS.add(sector)
                    DIRECTION = "SHORT"
                    send_telegram(f"{sector} added for SHORT")

        if msg.startswith("YES"):
            symbol = msg.split()[-1]
            if symbol in PENDING_SIGNALS:
                execute_trade(symbol)

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

# ================= EXECUTION =================
def execute_trade(symbol):
    global TRADES_COUNT

    if TRADES_COUNT >= MAX_TRADES:
        return

    data = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]
    ltp = data["last_price"]

    side = PENDING_SIGNALS[symbol]["side"]
    sl_price = PENDING_SIGNALS[symbol]["sl"]

    risk_per_share = abs(ltp - sl_price)
    if risk_per_share == 0:
        return

    qty = int(RISK_PER_TRADE / risk_per_share)
    if qty <= 0:
        return

    kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NSE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_BUY if side=="LONG" else kite.TRANSACTION_TYPE_SELL,
        quantity=qty,
        order_type=kite.ORDER_TYPE_MARKET,
        product=kite.PRODUCT_MIS
    )

    send_telegram(f"TRADE EXECUTED: {symbol} | Qty: {qty}")
    TRADES_COUNT += 1

# ================= TIME =================
def wait_for_candle_close():
    while True:
        now = datetime.now(IST)
        if now.minute % 5 == 0 and now.second < 3:
            return
        time.sleep(1)

# ================= MAIN =================
def run_bot():
    send_telegram("🚀 V5.6 BOT STARTED")

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

                signal = check_signal(df)

                if signal and symbol not in PENDING_SIGNALS:

                    last = df.iloc[-1]

                    entry = round(last["high"], 2) if signal=="LONG" else round(last["low"], 2)
                    sl = round(last["low"], 2) if signal=="LONG" else round(last["high"], 2)

                    risk = abs(entry - sl)
                    if risk == 0:
                        continue

                    qty = int(RISK_PER_TRADE / risk)
                    if qty <= 0:
                        continue

                    capital = int(entry * qty)
                    target = round(entry + 2*risk, 2) if signal=="LONG" else round(entry - 2*risk, 2)

                    PENDING_SIGNALS[symbol] = {
                        "side": signal,
                        "sl": sl
                    }

                    send_telegram(
                        f"📊 ALERT: {symbol} {signal}\n\n"
                        f"Entry : {entry}\n"
                        f"SL : {sl}\n"
                        f"Risk : {round(risk,2)}\n\n"
                        f"Qty : {qty}\n"
                        f"Capital : ₹{capital}\n\n"
                        f"Target (2R) : {target}\n\n"
                        f"Reply YES {symbol}"
                    )

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

# ================= START =================
if __name__ == "__main__":
    run_bot()
