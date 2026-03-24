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
# CHANGE 1: Ignore first 3 candles for trading
# Include first 3 candles for volume comparison
# CHANGE 2: Entry at candle HIGH/LOW not market price
def check_signal(df):
    if len(df) < 5:
        return None

    # Ignore first 3 candles for TRADING
    # But include them for volume comparison
    if len(df) <= 3:
        return None

    last = df.iloc[-1]

    # Volume comparison includes ALL candles
    # including first 3 candles!
    lowest_vol = df["volume"].min()

    if DIRECTION == "LONG":
        # Red candle + lowest volume = LONG signal
        if last["close"] < last["open"] and last["volume"] <= lowest_vol:

            # CHANGE 2: Entry at HIGH of candle
            # SL at LOW of candle
            entry = round(last["high"], 2)
            sl    = round(last["low"],  2)
            risk  = round(entry - sl,   2)

            if risk <= 0:
                return None

            # T1 = Entry + (Risk x 2)
            t1 = round(entry + risk * 2, 2)

            return {
                "side"  : "LONG",
                "entry" : entry,
                "sl"    : sl,
                "t1"    : t1,
                "risk"  : risk,
            }

    if DIRECTION == "SHORT":
        # Green candle + lowest volume = SHORT signal
        if last["close"] > last["open"] and last["volume"] <= lowest_vol:

            # CHANGE 2: Entry at LOW of candle
            # SL at HIGH of candle
            entry = round(last["low"],  2)
            sl    = round(last["high"], 2)
            risk  = round(sl - entry,   2)

            if risk <= 0:
                return None

            # T1 = Entry - (Risk x 2)
            t1 = round(entry - risk * 2, 2)

            return {
                "side"  : "SHORT",
                "entry" : entry,
                "sl"    : sl,
                "t1"    : t1,
                "risk"  : risk,
            }

    return None

# ================= EXECUTION =================
def execute_trade(symbol):
    global TRADES_COUNT

    if TRADES_COUNT >= MAX_TRADES:
        return

    if symbol not in PENDING_SIGNALS:
        return

    signal = PENDING_SIGNALS[symbol]
    side   = signal["side"]
    entry  = signal["entry"]
    sl     = signal["sl"]
    t1     = signal["t1"]
    risk   = signal["risk"]

    # Calculate quantity based on risk
    risk_per_share = abs(entry - sl)
    if risk_per_share == 0:
        return

    qty = int(RISK_PER_TRADE / risk_per_share)
    if qty <= 0:
        return

    # CHANGE 2: Place LIMIT order at candle high/low
    # NOT market order!
    # SHORT = SL-M order to SELL at LOW of candle
    # LONG  = SL-M order to BUY at HIGH of candle
    kite.place_order(
        variety          = kite.VARIETY_REGULAR,
        exchange         = kite.EXCHANGE_NSE,
        tradingsymbol    = symbol,
        transaction_type = kite.TRANSACTION_TYPE_BUY if side == "LONG" else kite.TRANSACTION_TYPE_SELL,
        quantity         = qty,
        order_type       = kite.ORDER_TYPE_SLM,
        trigger_price    = round(entry, 1),
        product          = kite.PRODUCT_MIS
    )

    # Place SL order immediately
    sl_id = kite.place_order(
        variety          = kite.VARIETY_REGULAR,
        exchange         = kite.EXCHANGE_NSE,
        tradingsymbol    = symbol,
        transaction_type = kite.TRANSACTION_TYPE_SELL if side == "LONG" else kite.TRANSACTION_TYPE_BUY,
        quantity         = qty,
        order_type       = kite.ORDER_TYPE_SLM,
        trigger_price    = round(sl, 1),
        product          = kite.PRODUCT_MIS
    )

    ACTIVE_TRADES[symbol] = {
        "side"     : side,
        "entry"    : entry,
        "sl"       : sl,
        "t1"       : t1,
        "risk"     : risk,
        "qty"      : qty,
        "sl_id"    : sl_id,
        "half_done": False
    }

    TRADES_COUNT += 1
    del PENDING_SIGNALS[symbol]

    # CHANGE 1: Better trade confirmation message
    send_telegram(
        f"TRADE PLACED!\n"
        f"Stock  : {symbol}\n"
        f"Side   : {side}\n"
        f"Entry  : Rs.{entry}\n"
        f"SL     : Rs.{sl}\n"
        f"T1     : Rs.{t1}\n"
        f"Risk   : Rs.{round(risk_per_share * qty, 0)}\n"
        f"Qty    : {qty} shares\n"
        f"Waiting for price to trigger..."
    )

# ================= MONITOR =================
def monitor():
    while True:
        try:
            orders = kite.orders()

            for symbol, trade in list(ACTIVE_TRADES.items()):

                # Check if SL hit by Zerodha
                sl_order = next(
                    (o for o in orders if o["order_id"] == trade["sl_id"]),
                    None
                )

                if sl_order and sl_order["status"] == "COMPLETE":
                    send_telegram(
                        f"SL HIT!\n"
                        f"Stock : {symbol}\n"
                        f"SL    : Rs.{trade['sl']}\n"
                        f"Loss booked. Moving on!"
                    )
                    ACTIVE_TRADES.pop(symbol)
                    continue

                # Get current price
                ltp = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]

                # Check T1
                if not trade["half_done"]:

                    t1_hit = (
                        (trade["side"] == "LONG"  and ltp >= trade["t1"]) or
                        (trade["side"] == "SHORT" and ltp <= trade["t1"])
                    )

                    if t1_hit:
                        qty_half = trade["qty"] // 2

                        # Book 50% at T1
                        kite.place_order(
                            variety          = kite.VARIETY_REGULAR,
                            exchange         = kite.EXCHANGE_NSE,
                            tradingsymbol    = symbol,
                            transaction_type = kite.TRANSACTION_TYPE_SELL if trade["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY,
                            quantity         = qty_half,
                            order_type       = kite.ORDER_TYPE_MARKET,
                            product          = kite.PRODUCT_MIS
                        )

                        # Move SL to entry (cost price)
                        kite.modify_order(
                            variety       = kite.VARIETY_REGULAR,
                            order_id      = trade["sl_id"],
                            trigger_price = round(trade["entry"], 1)
                        )

                        trade["half_done"] = True
                        trade["sl"]        = trade["entry"]

                        profit = abs(trade["t1"] - trade["entry"]) * qty_half

                        # CHANGE 1: Better T1 alert
                        send_telegram(
                            f"T1 HIT! 50% BOOKED!\n"
                            f"Stock   : {symbol}\n"
                            f"T1      : Rs.{trade['t1']}\n"
                            f"Booked  : {qty_half} shares\n"
                            f"Profit  : Rs.{round(profit, 0)}\n"
                            f"SL moved to ENTRY Rs.{trade['entry']}\n"
                            f"Remaining {trade['qty'] - qty_half} shares running FREE!\n"
                            f"Letting market decide till 3:15 PM!"
                        )

                # Exit at 3:15 PM
                if datetime.now(IST).time() >= EXIT_TIME:
                    qty_left = trade["qty"] // 2 if trade["half_done"] else trade["qty"]

                    kite.place_order(
                        variety          = kite.VARIETY_REGULAR,
                        exchange         = kite.EXCHANGE_NSE,
                        tradingsymbol    = symbol,
                        transaction_type = kite.TRANSACTION_TYPE_SELL if trade["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY,
                        quantity         = qty_left,
                        order_type       = kite.ORDER_TYPE_MARKET,
                        product          = kite.PRODUCT_MIS
                    )

                    send_telegram(
                        f"3:15 PM EXIT!\n"
                        f"Stock : {symbol}\n"
                        f"Exited {qty_left} shares at market price!\n"
                        f"Day complete!"
                    )

                    ACTIVE_TRADES.pop(symbol)

            time.sleep(5)

        except Exception as e:
            print("Monitor Error:", e)
            time.sleep(5)

# ================= CANDLE CLOSE FIX =================
def wait_for_candle_close():
    while True:
        now = datetime.now(IST)
        if now.minute % 5 == 0 and now.second < 3:
            return
        time.sleep(1)

# ================= MAIN =================
def run_bot():
    send_telegram("V5.7 BOT STARTED\nChanges:\n1. Better alerts with Entry/SL/T1\n2. Entry at candle High/Low\n3. Ignore first 3 candles for trading")

    while True:
        try:
            wait_for_candle_close()

            read_telegram()

            stocks_to_scan = []
            for sector in SELECTED_SECTORS:
                stocks_to_scan.extend(SECTOR_STOCKS.get(sector, []))

            for symbol in set(stocks_to_scan):

                if symbol in PENDING_SIGNALS:
                    continue

                if TRADES_COUNT >= MAX_TRADES:
                    break

                token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

                now = datetime.now(IST)

                data = kite.historical_data(
                    token,
                    now.replace(hour=9, minute=15),
                    now,
                    "5minute"
                )

                df = pd.DataFrame(data)

                if df.empty:
                    continue

                # Rename columns to lowercase
                df.columns = ["date", "open", "high", "low", "close", "volume"]

                signal = check_signal(df)

                if signal:
                    PENDING_SIGNALS[symbol] = signal

                    entry = signal["entry"]
                    sl    = signal["sl"]
                    t1    = signal["t1"]
                    risk  = signal["risk"]
                    side  = signal["side"]

                    # CHANGE 1: Detailed alert with all trade details
                    direction_word = "BUY ABOVE" if side == "LONG" else "SELL BELOW"

                    send_telegram(
                        f"ALERT: {symbol} {side}\n"
                        f"Entry  : {direction_word} Rs.{entry}\n"
                        f"SL     : Rs.{sl}\n"
                        f"T1     : Rs.{t1}\n"
                        f"Risk   : Rs.{risk} per share\n"
                        f"Reply YES {symbol}"
                    )

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

# ================= START =================
if __name__ == "__main__":
    import threading
    threading.Thread(target=monitor).start()
    run_bot()
