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
MAX_MARGIN_ALLOWED = 2000000  # 20 Lakh Limit
MIN_SL_PERCENT = 0.003        # 0.3% Breathing room
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
LAST_PROCESSED_MINUTE = -1

# ================= SECTORS =================
SECTOR_STOCKS = {
    "AUTO" : ["MARUTI","TATAMOTORS","M&M","EICHERMOT","HEROMOTOCO","TVSMOTOR","ASHOKLEY","BAJAJ-AUTO","MRF","BALKRISIND","BOSCHLTD","MOTHERSON","EXIDEIND"],
    "PHARMA" : ["SUNPHARMA","DRREDDY","CIPLA","DIVISLAB","LUPIN","AUROPHARMA","ALKEM","BIOCON","TORNTPHARM","ZYDUSLIFE","GLENMARK","ABBOTINDIA"],
    "BANK" : ["HDFCBANK","ICICIBANK","AXISBANK","KOTAKBANK","SBIN","INDUSINDBK","BANDHANBNK","BAJFINANCE","LICHSGFIN","CHOLAFIN","BAJAJFINSV","RBLBANK","PNB","BANKBARODA","IDFCFIRSTB","FEDERALBNK","CANBK","MUTHOOTFIN","AUBANK","MANAPPURAM"],
    "IT" : ["TCS","INFY","HCLTECH","WIPRO","TECHM","LTIM","PERSISTENT","MPHASIS","COFORGE"],
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
    global LAST_UPDATE_ID, DIRECTION, SELECTED_SECTORS

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        res = requests.get(url, timeout=10).json()

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

            # YES command to execute trade
            if msg.startswith("YES"):
                msg_parts = msg.split()
                if len(msg_parts) > 1:
                    symbol = msg_parts[-1]
                    if symbol in PENDING_SIGNALS:
                        execute_trade(symbol)

            # STATUS command
            if msg.strip() == "STATUS":
                send_status()

    except Exception as e:
        print("Read telegram error:", e)

def send_status():
    msg = "STATUS REPORT\n"
    msg += f"Direction : {DIRECTION}\n"
    msg += f"Sectors : {SELECTED_SECTORS}\n"
    msg += f"Trades : {TRADES_COUNT}/{MAX_TRADES}\n"
    if ACTIVE_TRADES:
        msg += "\nACTIVE TRADES:\n"
        for sym, t in ACTIVE_TRADES.items():
            msg += f"{sym} | Entry:{t['entry']} | SL:{t['sl']} | T1:{t['t1']}\n"
    else:
        msg += "\nNo active trades"
    send_telegram(msg)

# ================= STRATEGY =================
def check_signal(df, symbol):
    if len(df) < 5:
        return None

    if len(df) <= 3:
        return None

    last = df.iloc[-1]
    candle_no = len(df)
    historical_data = df.iloc[:-1] 
    historical_min = historical_data["volume"].min()
    is_lowest = last["volume"] < historical_min
    
    is_green = last["close"] > last["open"]
    is_red = last["close"] < last["open"]
    is_sure_shot = symbol in PENDING_SIGNALS
    signal_type = "SURE SHOT! Previous didnt trigger!" if is_sure_shot else "DECISION CANDLE"

    if DIRECTION == "SHORT" and is_green and is_lowest:
        entry = round(last["low"], 2)
        sl = round(last["high"], 2)
        risk = round(sl - entry, 2)
        if risk <= 0: return None
        t1 = round(entry - risk * 2, 2)
        return {
            "side" : "SHORT", "entry" : entry, "sl" : sl, "t1" : t1,
            "risk" : risk, "candle_no" : candle_no, "signal_type" : signal_type, "candle_time" : last["date"],
        }

    if DIRECTION == "LONG" and is_red and is_lowest:
        entry = round(last["high"], 2)
        sl = round(last["low"], 2)
        risk = round(entry - sl, 2)
        if risk <= 0: return None
        t1 = round(entry + risk * 2, 2)
        return {
            "side" : "LONG", "entry" : entry, "sl" : sl, "t1" : t1,
            "risk" : risk, "candle_no" : candle_no, "signal_type" : signal_type, "candle_time" : last["date"],
        }
    return None

# ================= EXECUTION =================
def execute_trade(symbol):
    global TRADES_COUNT

    if TRADES_COUNT >= MAX_TRADES:
        send_telegram(f"MAX {MAX_TRADES} TRADES reached! No more trades today!")
        return

    if symbol not in PENDING_SIGNALS:
        return

    signal = PENDING_SIGNALS[symbol]
    entry = signal["entry"]
    
    # --- SMART BUFFER LOGIC ---
    min_buffer = entry * MIN_SL_PERCENT
    original_risk = abs(entry - signal["sl"])
    actual_risk = max(original_risk, min_buffer)
    
    if signal["side"] == "LONG":
        sl = round(entry - actual_risk, 1)
        t1 = round(entry + (actual_risk * 2), 1) 
    else:
        sl = round(entry + actual_risk, 1)
        t1 = round(entry - (actual_risk * 2), 1)

    # --- POCKET CHECK (MARGIN) ---
    qty_by_risk = int(RISK_PER_TRADE / actual_risk)
    qty_by_margin = int(MAX_MARGIN_ALLOWED / entry)
    qty = min(qty_by_risk, qty_by_margin)

    if qty <= 0:
        send_telegram(f"Quantity too low for {symbol}! Skipping.")
        return

    try:
        main_order_id = kite.place_order(
            variety = kite.VARIETY_REGULAR,
            exchange = kite.EXCHANGE_NSE,
            tradingsymbol = symbol,
            transaction_type = kite.TRANSACTION_TYPE_BUY if signal["side"] == "LONG" else kite.TRANSACTION_TYPE_SELL,
            quantity = qty,
            order_type = kite.ORDER_TYPE_SLM,
            trigger_price = round(entry, 1),
            product = kite.PRODUCT_MIS
        )

        sl_order_id = kite.place_order(
            variety = kite.VARIETY_REGULAR,
            exchange = kite.EXCHANGE_NSE,
            tradingsymbol = symbol,
            transaction_type = kite.TRANSACTION_TYPE_SELL if signal["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY,
            quantity = qty,
            order_type = kite.ORDER_TYPE_SLM,
            trigger_price = round(sl, 1),
            product = kite.PRODUCT_MIS
        )

        ACTIVE_TRADES[symbol] = {
            "side" : signal["side"], "entry" : entry, "sl" : sl, "t1" : t1,
            "qty" : qty, "main_id" : main_order_id, "sl_id" : sl_order_id,
            "triggered" : False, "half_done" : False
        }

        TRADES_COUNT += 1
        send_telegram(f"✅ TRADE PLACED: {symbol}\nQty: {qty}\nSL: {sl}\nT1: {t1}\nMargin: Approx Rs.{int(qty*entry)}")

    except Exception as e:
        send_telegram(f"❌ ORDER ERROR: {str(e)}")

def cancel_old_order(symbol):
    if symbol not in ACTIVE_TRADES: return
    trade = ACTIVE_TRADES[symbol]
    try:
        kite.cancel_order(variety = kite.VARIETY_REGULAR, order_id = trade["main_id"])
        kite.cancel_order(variety = kite.VARIETY_REGULAR, order_id = trade["sl_id"])
        del ACTIVE_TRADES[symbol]
        global TRADES_COUNT
        TRADES_COUNT -= 1
        send_telegram(f"OLD ORDER CANCELLED for {symbol} due to SURE SHOT update!")
    except Exception as e:
        print(f"Cancel error: {e}")

# ================= MONITOR =================
def monitor():
    while True:
        try:
            now = datetime.now(IST)
            if now.time() >= EXIT_TIME and ACTIVE_TRADES:
                exit_all_trades()
                time.sleep(60)
                continue

            if not ACTIVE_TRADES:
                time.sleep(5)
                continue

            orders = kite.orders()
            for symbol, trade in list(ACTIVE_TRADES.items()):
                sl_order = next((o for o in orders if o["order_id"] == trade["sl_id"]), None)
                if sl_order and sl_order["status"] == "COMPLETE":
                    send_telegram(f"SL HIT! {symbol} at Rs.{trade['sl']}")
                    del ACTIVE_TRADES[symbol]
                    continue

                try:
                    ltp = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]
                except: continue

                main_order = next((o for o in orders if o["order_id"] == trade["main_id"]), None)
                if main_order and main_order["status"] == "COMPLETE":
                    if not trade["triggered"]:
                        trade["triggered"] = True
                        send_telegram(f"TRADE TRIGGERED! {symbol} at Rs.{trade['entry']}")

                if not trade["triggered"]: continue

                if not trade["half_done"]:
                    t1_hit = (trade["side"] == "LONG" and ltp >= trade["t1"]) or (trade["side"] == "SHORT" and ltp <= trade["t1"])
                    if t1_hit:
                        half_qty = trade["qty"] // 2
                        try:
                            kite.place_order(
                                variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE,
                                tradingsymbol=symbol, transaction_type=kite.TRANSACTION_TYPE_SELL if trade["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY,
                                quantity=half_qty, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS
                            )
                            kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=trade["sl_id"], trigger_price=round(trade["entry"], 1))
                            trade["half_done"] = True
                            trade["sl"] = trade["entry"]
                            trade["qty_left"] = trade["qty"] - half_qty
                            send_telegram(f"T1 HIT! {symbol}. 50% Booked. SL moved to Entry.")
                        except Exception as e:
                            send_telegram(f"T1 Error: {e}")
            time.sleep(5)
        except Exception as e:
            print("Monitor Error:", e)
            time.sleep(5)

def exit_all_trades():
    for symbol, trade in list(ACTIVE_TRADES.items()):
        try:
            qty_left = trade.get("qty_left", trade["qty"])
            kite.place_order(
                variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE,
                tradingsymbol=symbol, transaction_type=kite.TRANSACTION_TYPE_SELL if trade["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY,
                quantity=qty_left, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS
            )
            del ACTIVE_TRADES[symbol]
            send_telegram(f"3:15 PM EXIT! {symbol} closed.")
        except Exception as e:
            print(f"Exit error: {e}")

def wait_for_candle_close():
    global LAST_PROCESSED_MINUTE
    while True:
        now = datetime.now(IST)
        if now.minute % 5 == 0 and now.minute != LAST_PROCESSED_MINUTE:
            time.sleep(4)
            LAST_PROCESSED_MINUTE = now.minute
            return
        time.sleep(1)

def run_bot():
    send_telegram("V5.8 BOT STARTED! Buffered SL and Margin Guard Active.")
    while True:
        try:
            wait_for_candle_close()
            read_telegram()
            if not SELECTED_SECTORS or not DIRECTION: continue
            if TRADES_COUNT >= MAX_TRADES: continue

            stocks_to_scan = []
            for sector in SELECTED_SECTORS:
                stocks_to_scan.extend(SECTOR_STOCKS.get(sector, []))

            for symbol in set(stocks_to_scan):
                try:
                    token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]
                    now = datetime.now(IST)
                    data = kite.historical_data(token, now.replace(hour=9, minute=15, second=0, microsecond=0), now, "5minute")
                    if not data: continue
                    df = pd.DataFrame(data)
                    df.columns = ["date", "open", "high", "low", "close", "volume"]
                    signal = check_signal(df, symbol)
                    if signal is None: continue
                    if symbol in PENDING_SIGNALS and symbol in ACTIVE_TRADES:
                        cancel_old_order(symbol)
                    PENDING_SIGNALS[symbol] = signal
                    dir_word = "BUY ABOVE" if signal["side"] == "LONG" else "SELL BELOW"
                    send_telegram(f"ALERT: {symbol}\nType: {signal['signal_type']}\nEntry: {dir_word} {signal['entry']}\nReply YES {symbol}")
                except Exception as e:
                    print(f"Error scanning {symbol}: {e}")
                time.sleep(0.3)
        except Exception as e:
            print("Main Error:", e)
            time.sleep(10)

if __name__ == "__main__":
    import threading
    threading.Thread(target=monitor, daemon=True).start()
    run_bot()
