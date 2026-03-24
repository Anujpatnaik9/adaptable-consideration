# ==============================================================
# KUSHAL VARSHNEY BOT - V5.6.1 FINAL (STABLE)
# ✔ SAME AS V5.6
# ✔ Added: Re-entry logic
# ✔ Added: Telegram duplicate fix
# ==============================================================

import time
import requests
import pandas as pd
from datetime import datetime
import pytz
from kiteconnect import KiteConnect

# ================= CONFIG =================
API_KEY = "YOUR_API_KEY"
ACCESS_TOKEN = "YOUR_ACCESS_TOKEN"
TELEGRAM_TOKEN = "YOUR_TELEGRAM_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

IST = pytz.timezone("Asia/Kolkata")

# ================= GLOBAL =================
LAST_UPDATE_ID = None
SELECTED_SECTORS = set()
DIRECTION = None
PENDING_ORDERS = {}
TRADES_TODAY = 0
MAX_TRADES = 2

# ================= SECTORS (FULL - SAME AS YOUR 5.6) =================
SECTOR_STOCKS = {
    "AUTO": ["MARUTI","TATAMOTORS","M&M","EICHERMOT","HEROMOTOCO",
             "BAJAJ-AUTO","ASHOKLEY","BOSCHLTD","MOTHERSON"],

    "BANK": ["HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK","SBIN",
             "INDUSINDBK","BANDHANBNK","FEDERALBNK","IDFCFIRSTB",
             "PNB","BANKBARODA","CANBK","AUBANK","RBLBANK"],

    "IT": ["TCS","INFY","HCLTECH","WIPRO","TECHM",
           "LTIM","PERSISTENT","MPHASIS","COFORGE"],

    "PHARMA": ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN",
               "AUROPHARMA","ALKEM","BIOCON","GLENMARK"],

    "METAL": ["TATASTEEL","JSWSTEEL","HINDALCO","VEDL","SAIL"],

    "FMCG": ["ITC","HINDUNILVR","NESTLEIND","BRITANNIA",
             "DABUR","GODREJCP","MARICO"],

    "ENERGY": ["RELIANCE","ONGC","IOC","BPCL","GAIL"],

    "REALTY": ["DLF","GODREJPROP","OBEROIRLTY","PHOENIXLTD","PRESTIGE"],

    "FINANCE": ["BAJFINANCE","BAJAJFINSV","CHOLAFIN","MUTHOOTFIN"]
}

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

def read_telegram():
    global LAST_UPDATE_ID, DIRECTION, SELECTED_SECTORS

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        res = requests.get(url).json()

        for item in res.get("result", []):
            uid = item["update_id"]

            if LAST_UPDATE_ID is not None and uid <= LAST_UPDATE_ID:
                continue

            LAST_UPDATE_ID = uid

            if "message" not in item or "text" not in item["message"]:
                continue

            msg = item["message"]["text"].upper().strip()
            words = msg.split()

            if len(words) >= 2:
                sector, action = words[0], words[1]

                if sector in SECTOR_STOCKS:
                    if sector not in SELECTED_SECTORS:
                        SELECTED_SECTORS.add(sector)
                        DIRECTION = "LONG" if action == "HIGH" else "SHORT"
                        send_telegram(f"{sector} added for {DIRECTION}")
    except:
        pass

# ================= DATA =================
def get_data(symbol):
    try:
        now = datetime.now(IST)

        token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

        data = kite.historical_data(
            token,
            now.replace(hour=9, minute=15),
            now,
            "5minute"
        )

        df = pd.DataFrame(data)
        return df if len(df) >= 4 else None
    except:
        return None

# ================= SIGNAL =================
def check_signal(df):
    last = df.iloc[-1]
    lowest = df["volume"].min()

    is_green = last["close"] > last["open"]
    is_red = last["close"] < last["open"]

    if DIRECTION == "LONG" and is_red and last["volume"] <= lowest:
        return {"side":"LONG","entry":last["high"],"sl":last["low"]}

    if DIRECTION == "SHORT" and is_green and last["volume"] <= lowest:
        return {"side":"SHORT","entry":last["low"],"sl":last["high"]}

    return None

# ================= EXECUTION =================
def execute_trade(symbol):
    global TRADES_TODAY

    if symbol not in PENDING_ORDERS or TRADES_TODAY >= MAX_TRADES:
        return

    s = PENDING_ORDERS[symbol]
    risk = abs(s['entry'] - s['sl'])

    qty = int(5000 / risk)
    if qty <= 0:
        return

    order_id = kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NSE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_BUY if s['side']=="LONG" else kite.TRANSACTION_TYPE_SELL,
        quantity=qty,
        order_type=kite.ORDER_TYPE_SL,
        price=round(s['entry'],1),
        trigger_price=round(s['entry'],1),
        product=kite.PRODUCT_MIS
    )

    PENDING_ORDERS[symbol]["order_id"] = order_id
    TRADES_TODAY += 1

    send_telegram(f"ORDER PLACED: {symbol}")

# ================= SCANNER =================
def scanner():
    while True:
        try:
            read_telegram()

            stocks = []
            for s in SELECTED_SECTORS:
                stocks += SECTOR_STOCKS[s]

            for sym in set(stocks):
                df = get_data(sym)
                if df is None:
                    continue

                signal = check_signal(df)
                if not signal:
                    continue

                # ===== RE-ENTRY LOGIC =====
                if sym in PENDING_ORDERS:
                    old = PENDING_ORDERS[sym]

                    if "order_id" in old:
                        orders = kite.orders()
                        o = next((x for x in orders if x['order_id']==old['order_id']), None)

                        if o and o['status'] != "COMPLETE":
                            kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=old['order_id'])
                            send_telegram(f"{sym} updated → old order cancelled")

                PENDING_ORDERS[sym] = signal

                send_telegram(
                    f"ALERT {sym} {signal['side']}\n"
                    f"Entry: {signal['entry']}\n"
                    f"SL: {signal['sl']}\n"
                    f"Reply YES {sym}"
                )

            time.sleep(60)

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

# ================= START =================
scanner()
