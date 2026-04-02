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

RISK_PER_TRADE = 5000 # Risk only Rs.5000 per trade
MAX_TRADES = 2 # Maximum 2 trades per day
EXIT_TIME = datetime.strptime("15:15", "%H:%M").time()

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

IST = pytz.timezone("Asia/Kolkata")

# ================= GLOBALS =================
LAST_UPDATE_ID = None
SELECTED_SECTORS = set()
DIRECTION = None
LAST_PROCESSED_MINUTE = -1
ALERTED_STOCKS = set() # Prevents duplicate alerts!
TRADES_COUNT = 0
ACTIVE_TRADES = {}
PENDING_SIGNALS = {}

# ================= SECTORS =================
SECTOR_STOCKS = {
    "AUTO" : ["MARUTI","M&M","EICHERMOT","HEROMOTOCO","TVSMOTOR","ASHOKLEY","BAJAJ-AUTO","MRF","BALKRISIND","BOSCHLTD","MOTHERSON","EXIDEIND"],
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

            # CLEAR command = reset everything
            if msg == "CLEAR":
                SELECTED_SECTORS.clear()
                ALERTED_STOCKS.clear()
                PENDING_SIGNALS.clear()
                send_telegram("All sectors cleared! Fresh start!")
                return

            # STATUS command
            if msg == "STATUS":
                send_status()
                return

            # YES command = execute trade
            if msg.startswith("YES"):
                symbol = msg.split()[-1]
                if symbol in PENDING_SIGNALS:
                    execute_trade(symbol)
                return

            # SECTOR + DIRECTION command
            # Example: "BANK LOW" or "BANK HIGH"
            words = msg.split()
            if len(words) == 2 and words[0] in SECTOR_STOCKS:
                sector = words[0]
                direction = words[1]

                SELECTED_SECTORS.add(sector)
                DIRECTION = direction

                send_telegram(
                    f"Added {sector}\n"
                    f"Direction: {direction}\n"
                    f"Scanning {len(SECTOR_STOCKS[sector])} stocks!"
                )

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
# KUSHAL SIR'S EXACT RULES:
# 1. Scan from candle 4 onwards (9:30 AM)
# 2. Volume comparison includes ALL candles
# (including candles 1, 2, 3!)
# 3. Decision candle = GREEN + LOWEST volume (SHORT/LOW)
# = RED + LOWEST volume (LONG/HIGH)
# 4. Volume must be strictly lowest AND lower than previous!
# 5. Entry = LOW of candle (SHORT) / HIGH of candle (LONG)
# 6. SL = HIGH of candle (SHORT) / LOW of candle (LONG)

def check_signal(df):
    # Need at least a few candles to compare volume
    if len(df) < 2:
        return None

    # 1. GET DATA
    last = df.iloc[-1]       # The most recent CLOSED 5-minute candle
    previous_data = df.iloc[:-1] # Every candle before the current one today
    
    # 2. THE VOLUME RULE (The "Absolute Lowest" Audit)
    # If the current candle's volume is NOT the lowest of the day, REJECT.
    current_volume = last["volume"]
    lowest_volume_so_far = previous_data["volume"].min()

    if current_volume > lowest_volume_so_far:
        return None

    # 3. THE COLOR & DIRECTION RULE
    # Logic: Green Candle = Short Opportunity | Red Candle = Long Opportunity
    is_green = last["close"] > last["open"]
    is_red = last["close"] < last["open"]

    # --- SHORT SIDE (Looking for a Green 'Weakness' Candle) ---
    if DIRECTION == "LOW" and is_green:
        entry = round(last["low"], 2)
        sl = round(last["high"], 2)
        risk = round(sl - entry, 2)
        t1 = round(entry - (risk * 2), 2)
        return {"side": "SHORT", "entry": entry, "sl": sl, "t1": t1}

    # --- LONG SIDE (Looking for a Red 'Weakness' Candle) ---
    elif DIRECTION == "HIGH" and is_red:
        entry = round(last["high"], 2)
        sl = round(last["low"], 2)
        risk = round(entry - sl, 2)
        t1 = round(entry + (risk * 2), 2)
        return {"side": "LONG", "entry": entry, "sl": sl, "t1": t1}

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
    side = signal["side"]
    entry = signal["entry"]
    sl = signal["sl"]
    t1 = signal["t1"]

    # Calculate quantity
    # === NEW SAFE SL MATH START ===
    # 1. Calculate raw gap
    raw_gap = abs(entry - sl)
    
    # 2. Apply Accountant's Safety Floors (0.75 or 0.20%)
    min_gap = max(0.75, entry * 0.0020)
    
    # 3. Final Risk used for Qty and Target
    risk_per_share = max(raw_gap, min_gap)

    # 4. Update SL and T1 to match the new "Breathing Room"
    if side == "LONG":
        sl = round(entry - risk_per_share, 1)
        t1 = round(entry + (risk_per_share * 2), 1)
    else:
        sl = round(entry + risk_per_share, 1)
        t1 = round(entry - (risk_per_share * 2), 1)

    qty = int(RISK_PER_TRADE / risk_per_share)
    # === NEW SAFE SL MATH END ===

    try:
        
        # Place main entry order
        main_order_id = kite.place_order(
            variety = kite.VARIETY_REGULAR,
            exchange = kite.EXCHANGE_NSE,
            tradingsymbol = symbol,
            transaction_type = kite.TRANSACTION_TYPE_BUY if side == "LONG" else kite.TRANSACTION_TYPE_SELL,
            quantity = qty,
            order_type = kite.ORDER_TYPE_SLM,
            trigger_price = round(entry, 1),
            product = kite.PRODUCT_MIS
        )

        # Place SL order (Zerodha monitors this!)
        sl_order_id = kite.place_order(
            variety = kite.VARIETY_REGULAR,
            exchange = kite.EXCHANGE_NSE,
            tradingsymbol = symbol,
            transaction_type = kite.TRANSACTION_TYPE_SELL if side == "LONG" else kite.TRANSACTION_TYPE_BUY,
            quantity = qty,
            order_type = kite.ORDER_TYPE_SLM,
            trigger_price = round(sl, 1),
            product = kite.PRODUCT_MIS
        )

        # Track trade
        ACTIVE_TRADES[symbol] = {
            "side" : side,
            "entry" : entry,
            "sl" : sl,
            "t1" : t1,
            "qty" : qty,
            "qty_left" : qty,
            "main_id" : main_order_id,
            "sl_id" : sl_order_id,
            "triggered": False,
            "half_done": False,
        }

        TRADES_COUNT += 1
        del PENDING_SIGNALS[symbol]

        direction_word = "BUY ABOVE" if side == "LONG" else "SELL BELOW"
        actual_risk = round(risk_per_share * qty, 0)

        send_telegram(
            f"TRADE PLACED!\n"
            f"Stock : {symbol}\n"
            f"Side : {side}\n"
            f"Entry : {direction_word} Rs.{entry}\n"
            f"SL : Rs.{sl}\n"
            f"T1 : Rs.{t1}\n"
            f"Qty : {qty} shares\n"
            f"Risk : Rs.{actual_risk}\n"
            f"Waiting for trigger..."
        )

    except Exception as e:
        send_telegram(f"ORDER ERROR {symbol}: {str(e)}")

# ================= MONITOR =================
def monitor():
    """
    Runs every 5 seconds in background
    Checks:
    1. Trade triggered?
    2. T1 hit? Book 50% + move SL to entry
    3. SL hit by Zerodha?
    4. 3:15 PM? Exit all!
    """
    while True:
        try:
            now = datetime.now(IST)

            # Exit all at 3:15 PM
            if now.time() >= EXIT_TIME and ACTIVE_TRADES:
                exit_all_trades()
                time.sleep(60)
                continue

            if not ACTIVE_TRADES:
                time.sleep(5)
                continue

            orders = kite.orders()

            for symbol, trade in list(ACTIVE_TRADES.items()):

                # Check SL hit by Zerodha
                sl_order = next(
                    (o for o in orders if o["order_id"] == trade["sl_id"]),
                    None
                )
                if sl_order and sl_order["status"] == "COMPLETE":
                    send_telegram(
                        f"SL HIT!\n"
                        f"Stock : {symbol}\n"
                        f"SL : Rs.{trade['sl']}\n"
                        f"Loss booked! Moving on!"
                    )
                    del ACTIVE_TRADES[symbol]
                    continue

                # Get current price
                try:
                    ltp = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]
                except Exception:
                    continue

                # Check if main order triggered
                main_order = next(
                    (o for o in orders if o["order_id"] == trade["main_id"]),
                    None
                )
                if main_order and main_order["status"] == "COMPLETE":
                    if not trade["triggered"]:
                        trade["triggered"] = True
                        send_telegram(
                            f"TRADE TRIGGERED!\n"
                            f"Stock : {symbol}\n"
                            f"Entry : Rs.{trade['entry']}\n"
                            f"SL : Rs.{trade['sl']}\n"
                            f"T1 : Rs.{trade['t1']}\n"
                            f"Current : Rs.{ltp}\n"
                            f"Monitoring..."
                        )

                if not trade["triggered"]:
                    continue

                # Check T1
                if not trade["half_done"]:
                    t1_hit = (
                        (trade["side"] == "LONG" and ltp >= trade["t1"]) or
                        (trade["side"] == "SHORT" and ltp <= trade["t1"])
                    )

                    if t1_hit:
                        half_qty = trade["qty"] // 2
                        try:
                            # Book 50% at T1
                            kite.place_order(
                                variety = kite.VARIETY_REGULAR,
                                exchange = kite.EXCHANGE_NSE,
                                tradingsymbol = symbol,
                                transaction_type = kite.TRANSACTION_TYPE_SELL if trade["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY,
                                quantity = half_qty,
                                order_type = kite.ORDER_TYPE_MARKET,
                                product = kite.PRODUCT_MIS
                            )

                            # Move SL to entry = FREE TRADE!
                            kite.modify_order(
                                variety = kite.VARIETY_REGULAR,
                                order_id = trade["sl_id"],
                                trigger_price = round(trade["entry"], 1)
                            )

                            profit = abs(trade["t1"] - trade["entry"]) * half_qty

                            trade["half_done"] = True
                            trade["sl"] = trade["entry"]
                            trade["qty_left"] = trade["qty"] - half_qty

                            send_telegram(
                                f"T1 HIT! 50% BOOKED!\n"
                                f"Stock : {symbol}\n"
                                f"T1 : Rs.{trade['t1']}\n"
                                f"Booked : {half_qty} shares\n"
                                f"Profit : Rs.{round(profit, 0)}\n"
                                f"SL moved to ENTRY Rs.{trade['entry']}\n"
                                f"Remaining {trade['qty_left']} shares FREE!\n"
                                f"Running till 3:15 PM!"
                            )

                        except Exception as e:
                            send_telegram(f"T1 error {symbol}: {str(e)}")

            time.sleep(5)

        except Exception as e:
            print("Monitor Error:", e)
            time.sleep(5)

def exit_all_trades():
    """Exit all open positions at 3:15 PM"""
    for symbol, trade in list(ACTIVE_TRADES.items()):
        try:
            qty_left = trade.get("qty_left", trade["qty"])
            if qty_left > 0:
                kite.place_order(
                    variety = kite.VARIETY_REGULAR,
                    exchange = kite.EXCHANGE_NSE,
                    tradingsymbol = symbol,
                    transaction_type = kite.TRANSACTION_TYPE_SELL if trade["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY,
                    quantity = qty_left,
                    order_type = kite.ORDER_TYPE_MARKET,
                    product = kite.PRODUCT_MIS
                )
            del ACTIVE_TRADES[symbol]
            send_telegram(
                f"3:15 PM EXIT!\n"
                f"Stock : {symbol}\n"
                f"Exited {qty_left} shares!\n"
                f"Day complete! See you tomorrow!"
            )
        except Exception as e:
            print(f"Exit error {symbol}: {e}")

# ================= MAIN LOOP =================
def run_bot():
    global LAST_PROCESSED_MINUTE

    send_telegram(
        "V5.9 BOT STARTED!\n"
        "Kushal Sir's Exact Logic:\n"
        "1. Scanning from 9:30 AM (candle 4)\n"
        "2. Volume includes candles 1,2,3\n"
        "3. Strict lowest volume filter\n"
        "4. Entry at candle Low/High\n"
        "5. T1 = 2R | Book 50% | Free trade!\n"
        "6. Auto exit 3:15 PM\n"
        "\nCommands:\n"
        "BANK LOW = Short banking stocks\n"
        "BANK HIGH = Long banking stocks\n"
        "YES STOCK = Execute trade\n"
        "STATUS = See active trades\n"
        "CLEAR = Reset all sectors"
    )

    while True:
        try:
            read_telegram()

            if not SELECTED_SECTORS or not DIRECTION:
                time.sleep(1)
                continue

            now = datetime.now(IST)

            # Only scan during market hours
            # Stop scanning after 2:30 PM
            if now.hour > 14 or (now.hour == 14 and now.minute >= 30):
                time.sleep(60)
                continue

            # Run once per candle AFTER 45 seconds
            # 45 second delay ensures candle data
            # is fully updated in Zerodha!
            if (now.minute % 5 == 0 and
                now.second >= 45 and
                now.minute != LAST_PROCESSED_MINUTE):

                LAST_PROCESSED_MINUTE = now.minute

                if TRADES_COUNT >= 2:
                    time.sleep(1)
                    continue

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

                        if not data:
                            continue

                        df = pd.DataFrame(data)
                        df.columns = ["date","open","high","low","close","volume"]

                        sig = check_signal(df)

                        # Only alert if:
                        # 1. Signal found
                        # 2. Not already alerted for this stock today!
                        if sig and symbol not in ALERTED_STOCKS:
                            ALERTED_STOCKS.add(symbol)
                            PENDING_SIGNALS[symbol] = sig

                            direction_word = "BUY ABOVE" if sig["side"] == "LONG" else "SELL BELOW"

                            send_telegram(
                                f"ALERT: {symbol} {sig['side']}\n"
                                f"Entry : {direction_word} Rs.{sig['entry']}\n"
                                f"SL : Rs.{sig['sl']}\n"
                                f"T1 : Rs.{sig['t1']}\n"
                                f"Risk : Rs.{sig['risk']} per share\n"
                                f"Reply YES {symbol}"
                            )

                    except Exception as e:
                        print(f"Error {symbol}: {e}")

            time.sleep(1)

        except Exception as e:
            send_telegram(f"Main error: {e}")
            time.sleep(5)

# ================= START =================
if __name__ == "__main__":
    import threading
    threading.Thread(target=monitor, daemon=True).start()
    run_bot()
