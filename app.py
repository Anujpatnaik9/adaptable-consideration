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

# ===== TIMEZONE FIX =====
IST = pytz.timezone("Asia/Kolkata")

# ================= GLOBALS =================
TRADES_COUNT = 0
ACTIVE_TRADES = {}
PENDING_SIGNALS = {}
LAST_UPDATE_ID = None
SELECTED_SECTORS = set()   # ✅ FIX (no duplicates)
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

        # ✅ FIX: MULTI-LINE SUPPORT
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

        # YES execution
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

    sl_id = kite.place_order(
        variety=kite.VARIETY_REGULAR,
        exchange=kite.EXCHANGE_NSE,
        tradingsymbol=symbol,
        transaction_type=kite.TRANSACTION_TYPE_SELL if side=="LONG" else kite.TRANSACTION_TYPE_BUY,
        quantity=qty,
        order_type=kite.ORDER_TYPE_SLM,
        trigger_price=round(sl_price,1),
        product=kite.PRODUCT_MIS
    )

    ACTIVE_TRADES[symbol] = {
        "side": side,
        "entry": ltp,
        "sl": sl_price,
        "qty": qty,
        "sl_id": sl_id,
        "half_done": False
    }

    TRADES_COUNT += 1
    send_telegram(f"TRADE EXECUTED: {symbol} | Qty: {qty}")

# ================= MONITOR =================
def monitor():
    while True:
        try:
            orders = kite.orders()

            for symbol, trade in list(ACTIVE_TRADES.items()):

                sl_order = next((o for o in orders if o["order_id"] == trade["sl_id"]), None)

                if sl_order and sl_order["status"] == "COMPLETE":
                    send_telegram(f"🛑 SL HIT: {symbol}")
                    ACTIVE_TRADES.pop(symbol)
                    continue

                ltp = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]

                risk = abs(trade["entry"] - trade["sl"])
                target = trade["entry"] + 2*risk if trade["side"]=="LONG" else trade["entry"] - 2*risk

                if not trade["half_done"]:
                    if (trade["side"]=="LONG" and ltp >= target) or (trade["side"]=="SHORT" and ltp <= target):

                        qty_half = trade["qty"] // 2

                        kite.place_order(
                            variety=kite.VARIETY_REGULAR,
                            exchange=kite.EXCHANGE_NSE,
                            tradingsymbol=symbol,
                            transaction_type=kite.TRANSACTION_TYPE_SELL if trade["side"]=="LONG" else kite.TRANSACTION_TYPE_BUY,
                            quantity=qty_half,
                            order_type=kite.ORDER_TYPE_MARKET,
                            product=kite.PRODUCT_MIS
                        )

                        kite.modify_order(
                            variety=kite.VARIETY_REGULAR,
                            order_id=trade["sl_id"],
                            trigger_price=round(trade["entry"],1)
                        )

                        trade["half_done"] = True
                        send_telegram(f"🎯 TARGET HIT: {symbol}")

                if datetime.now(IST).time() >= EXIT_TIME:
                    kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        exchange=kite.EXCHANGE_NSE,
                        tradingsymbol=symbol,
                        transaction_type=kite.TRANSACTION_TYPE_SELL if trade["side"]=="LONG" else kite.TRANSACTION_TYPE_BUY,
                        quantity=trade["qty"],
                        order_type=kite.ORDER_TYPE_MARKET,
                        product=kite.PRODUCT_MIS
                    )
                    ACTIVE_TRADES.pop(symbol)

            time.sleep(5)

        except Exception as e:
            print("Monitor Error:", e)
            time.sleep(5)

# ================= MAIN =================
def run_bot():
    send_telegram("🚀 V5.5 BOT STARTED (FINAL FIXED)")

    while True:
        try:
            read_telegram()

            stocks_to_scan = []
            for sector in SELECTED_SECTORS:
                stocks_to_scan.extend(SECTOR_STOCKS.get(sector, []))

            for symbol in set(stocks_to_scan):

                token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

                now = datetime.now(IST)  # ✅ FIX

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

                    PENDING_SIGNALS[symbol] = {
                        "side": signal,
                        "sl": last["low"] if signal=="LONG" else last["high"]
                    }

                    send_telegram(f"📊 ALERT: {symbol} {signal}\nReply YES {symbol}")

            time.sleep(60)

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

# ================= START =================
if __name__ == "__main__":
    import threading
    threading.Thread(target=monitor).start()
    run_bot()
