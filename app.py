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
                symbol = msg.split()[-1]
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
# KUSHAL SIR'S EXACT LOGIC:
# Rule 1: Include ALL candles (1,2,3) for volume comparison
# Rule 2: Ignore first 3 candles for trading signals
# Rule 3: Decision candle = GREEN + LOWEST volume (SHORT)
# = RED + LOWEST volume (LONG)
# Rule 4: Wait for candle to CLOSE
# Rule 5: Entry = LOW of decision candle (SHORT)
# = HIGH of decision candle (LONG)
# Rule 6: SL = HIGH of decision candle (SHORT)
# = LOW of decision candle (LONG)
# Rule 7: If order didnt trigger + next candle also
# lowest volume = SURE SHOT! Cancel + update!

def check_signal(df, symbol):
    if len(df) < 5:
        return None

    if len(df) <= 3:
        return None

    last = df.iloc[-1]
    candle_no = len(df)

    lowest_vol = df["volume"].min()
    is_lowest = last["volume"] <= lowest_vol

    is_green = last["close"] > last["open"]
    is_red = last["close"] < last["open"]

    is_sure_shot = symbol in PENDING_SIGNALS
    signal_type = "SURE SHOT! Previous didnt trigger!" if is_sure_shot else "DECISION CANDLE"

    # SHORT SIDE
    if DIRECTION == "SHORT" and is_green and is_lowest:
        entry = round(last["low"], 2)
        sl = round(last["high"], 2)
        risk = round(sl - entry, 2)

        if risk <= 0:
            return None

        t1 = round(entry - risk * 2, 2)

        # ✅ DEBUG PRINT ADDED
        print(f"🔥 SIGNAL DETECTED on candle #{candle_no} for {symbol} (SHORT)")

        return {
            "side": "SHORT",
            "entry": entry,
            "sl": sl,
            "t1": t1,
            "risk": risk,
            "candle_no": candle_no,
            "signal_type": signal_type,
            "candle_time": last["date"],
        }

    # LONG SIDE
    if DIRECTION == "LONG" and is_red and is_lowest:
        entry = round(last["high"], 2)
        sl = round(last["low"], 2)
        risk = round(entry - sl, 2)

        if risk <= 0:
            return None

        t1 = round(entry + risk * 2, 2)

        # ✅ DEBUG PRINT ADDED
        print(f"🔥 SIGNAL DETECTED on candle #{candle_no} for {symbol} (LONG)")

        return {
            "side": "LONG",
            "entry": entry,
            "sl": sl,
            "t1": t1,
            "risk": risk,
            "candle_no": candle_no,
            "signal_type": signal_type,
            "candle_time": last["date"],
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
    side = signal["side"]
    entry = signal["entry"]
    sl = signal["sl"]
    t1 = signal["t1"]
    risk = signal["risk"]

    # Calculate quantity based on risk
    risk_per_share = abs(entry - sl)
    if risk_per_share == 0:
        return

    qty = int(RISK_PER_TRADE / risk_per_share)
    if qty <= 0:
        send_telegram(f"Quantity too low for {symbol}! Skipping.")
        return

    try:
        # Place main entry order (SLM = triggers at entry price)
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

        # Place SL order immediately
        # Zerodha monitors this 24/7!
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

        # Track this trade
        ACTIVE_TRADES[symbol] = {
            "side" : side,
            "entry" : entry,
            "sl" : sl,
            "sl_orig" : sl,
            "t1" : t1,
            "risk" : risk,
            "qty" : qty,
            "qty_left" : qty,
            "main_id" : main_order_id,
            "sl_id" : sl_order_id,
            "triggered" : False,
            "half_done" : False,
            "signal_type" : signal["signal_type"],
        }

        TRADES_COUNT += 1
        del PENDING_SIGNALS[symbol]

        direction_word = "BUY ABOVE" if side == "LONG" else "SELL BELOW"

        send_telegram(
            f"TRADE PLACED!\n"
            f"Stock : {symbol}\n"
            f"Side : {side}\n"
            f"Entry : {direction_word} Rs.{entry}\n"
            f"SL : Rs.{sl}\n"
            f"T1 : Rs.{t1}\n"
            f"Risk : Rs.{round(risk_per_share * qty, 0)}\n"
            f"Qty : {qty} shares\n"
            f"Type : {signal['signal_type']}\n"
            f"Waiting for price to trigger..."
        )

    except Exception as e:
        send_telegram(f"ORDER ERROR for {symbol}: {str(e)}")


def cancel_old_order(symbol):
    """Cancel old untriggered order when SURE SHOT appears"""
    if symbol not in ACTIVE_TRADES:
        return

    trade = ACTIVE_TRADES[symbol]

    try:
        # Cancel main entry order
        kite.cancel_order(
            variety = kite.VARIETY_REGULAR,
            order_id = trade["main_id"]
        )
        # Cancel SL order
        kite.cancel_order(
            variety = kite.VARIETY_REGULAR,
            order_id = trade["sl_id"]
        )

        del ACTIVE_TRADES[symbol]
        TRADES_COUNT -= 1 # Allow new trade

        send_telegram(
            f"OLD ORDER CANCELLED!\n"
            f"Stock : {symbol}\n"
            f"Reason : Price didnt trigger\n"
            f" New SURE SHOT signal found!\n"
            f"Placing updated order..."
        )

    except Exception as e:
        print(f"Cancel error for {symbol}: {e}")

# ================= MONITOR =================
def monitor():
    """
    Runs every 5 seconds in background
    Monitors:
    1. Has trade triggered?
    2. Has T1 been hit?
    3. Has SL been hit by Zerodha?
    4. Is it 3:15 PM?
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

                # Check if SL hit by Zerodha
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
                            f"Trade is ON! Monitoring..."
                        )

                # Only check T1 after trade triggered
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

                            # Move SL to entry (cost price)
                            # Now remaining trade is FREE!
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
                                f"Remaining {trade['qty_left']} shares = FREE TRADE!\n"
                                f"Letting market run till 3:15 PM!"
                            )

                        except Exception as e:
                            send_telegram(f"T1 booking error {symbol}: {str(e)}")

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

# ================= CANDLE CLOSE FIX =================
def wait_for_candle_close():
    """
    Wait until 5-min candle fully closes
    Candles close at: 9:20, 9:25, 9:30...
    """
    while True:
        now = datetime.now(IST)
        if now.minute % 5 == 0 and now.second < 3:
            return
        time.sleep(1)

# ================= MAIN =================
def run_bot():
    send_telegram(
        "V5.8 BOT STARTED!\n"
        "Kushal Sir's Exact Logic:\n"
        "1. First 3 candles ignored for trading\n"
        "2. All candles included for volume check\n"
        "3. Entry at candle Low/High (not market!)\n"
        "4. Sure Shot when previous didnt trigger\n"
        "5. T1 = 2R | Book 50% | Move SL to entry\n"
        "6. Auto exit at 3:15 PM\n"
        "\nSend: BANK LOW or BANK HIGH to start!"
    )

    while True:
        try:
            wait_for_candle_close()

            read_telegram()

            if not SELECTED_SECTORS or not DIRECTION:
                continue

            if TRADES_COUNT >= MAX_TRADES:
                continue

            # Get all stocks from selected sectors
            stocks_to_scan = []
            for sector in SELECTED_SECTORS:
                stocks_to_scan.extend(SECTOR_STOCKS.get(sector, []))

            for symbol in set(stocks_to_scan):

                try:
                    # Get instrument token
                    token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

                    now = datetime.now(IST)

                    # Download 5-min candles from 9:15 AM
                    data = kite.historical_data(
                        token,
                        now.replace(hour=9, minute=15, second=0, microsecond=0),
                        now,
                        "5minute"
                    )

                    if not data:
                        continue

                    df = pd.DataFrame(data)
                    df.columns = ["date", "open", "high", "low", "close", "volume"]

                    # Check Kushal sir's signal
                    signal = check_signal(df, symbol)

                    if signal is None:
                        continue

                    # SURE SHOT logic:
                    # If previous signal didnt trigger
                    # and new signal found = cancel old + place new!
                    if symbol in PENDING_SIGNALS:
                        # This is a SURE SHOT!
                        # Cancel old pending order if placed
                        if symbol in ACTIVE_TRADES:
                            cancel_old_order(symbol)

                    # Update pending signal
                    PENDING_SIGNALS[symbol] = signal

                    direction_word = "BUY ABOVE" if signal["side"] == "LONG" else "SELL BELOW"

                    # Send detailed Telegram alert
                    send_telegram(
                        f"ALERT: {symbol} {signal['side']}\n"
                        f"Type : {signal['signal_type']}\n"
                        f"Candle : #{signal['candle_no']}\n"
                        f"Entry : {direction_word} Rs.{signal['entry']}\n"
                        f"SL : Rs.{signal['sl']}\n"
                        f"T1 : Rs.{signal['t1']}\n"
                        f"Risk : Rs.{signal['risk']} per share\n"
                        f"Reply YES {symbol}"
                    )

                except Exception as e:
                    print(f"Error scanning {symbol}: {e}")
                    continue

                time.sleep(0.3)

        except Exception as e:
            print("Error:", e)
            time.sleep(10)

# ================= START =================
if __name__ == "__main__":
    import threading
    threading.Thread(target=monitor, daemon=True).start()
    run_bot()
