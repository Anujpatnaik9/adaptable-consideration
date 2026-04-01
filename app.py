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
        if "result" not in res: return
        for item in res["result"]:
            update_id = item["update_id"]
            if LAST_UPDATE_ID and update_id <= LAST_UPDATE_ID: continue
            LAST_UPDATE_ID = update_id
            if "message" not in item or "text" not in item["message"]: continue
            msg = item["message"]["text"].upper()
            words = msg.strip().split()
            if len(words) >= 2 and words[0] in SECTOR_STOCKS:
                sector, action = words[0], words[1]
                if action == "HIGH":
                    SELECTED_SECTORS.add(sector); DIRECTION = "LONG"
                    send_telegram(f"{sector} added for LONG")
                elif action == "LOW":
                    SELECTED_SECTORS.add(sector); DIRECTION = "SHORT"
                    send_telegram(f"{sector} added for SHORT")
            if msg.startswith("YES"):
                symbol = msg.split()[-1]
                if symbol in PENDING_SIGNALS: execute_trade(symbol)
            if msg.strip() == "STATUS": send_status()
    except Exception as e: print("Read telegram error:", e)

def send_status():
    msg = f"STATUS: Dir:{DIRECTION} | Sectors:{SELECTED_SECTORS} | Trades:{TRADES_COUNT}/{MAX_TRADES}"
    send_telegram(msg)

# ================= STRATEGY (FIXED VOLUME LOGIC) =================
def check_signal(df, symbol):
    if len(df) < 5: return None # Ensure we have enough data for the day
    
    # The candle that JUST closed (e.g., at 10:55 to 11:00)
    last_candle = df.iloc[-1]
    
    # ALL candles before the last one (from 9:15 AM onwards)
    previous_candles = df.iloc[:-1]
    
    # Logic: Current volume MUST be lower than the MINIMUM volume seen so far today
    hist_min_vol = previous_candles["volume"].min()
    
    if last_candle["volume"] >= hist_min_vol:
        return None # Volume filter failed

    is_sure_shot = symbol in PENDING_SIGNALS
    sig_type = "SURE SHOT!" if is_sure_shot else "DECISION CANDLE"
    
    # SHORT: Green Candle + Lowest Volume
    if DIRECTION == "SHORT" and last_candle["close"] > last_candle["open"]:
        risk = last_candle["high"] - last_candle["low"]
        if risk <= 0: return None
        return {"side":"SHORT", "entry":round(last_candle["low"],2), "sl":round(last_candle["high"],2), "risk":round(risk,2), "signal_type":sig_type}

    # LONG: Red Candle + Lowest Volume
    if DIRECTION == "LONG" and last_candle["close"] < last_candle["open"]:
        risk = last_candle["high"] - last_candle["low"]
        if risk <= 0: return None
        return {"side":"LONG", "entry":round(last_candle["high"],2), "sl":round(last_candle["low"],2), "risk":round(risk,2), "signal_type":sig_type}
    
    return None

# ================= EXECUTION =================
def execute_trade(symbol):
    global TRADES_COUNT
    if TRADES_COUNT >= MAX_TRADES or symbol not in PENDING_SIGNALS: return
    sig = PENDING_SIGNALS[symbol]; entry = sig["entry"]
    actual_risk = max(sig["risk"], entry * MIN_SL_PERCENT)
    qty = min(int(RISK_PER_TRADE / actual_risk), int(MAX_MARGIN_ALLOWED / entry))
    if qty <= 0: return
    try:
        side_main = kite.TRANSACTION_TYPE_BUY if sig["side"] == "LONG" else kite.TRANSACTION_TYPE_SELL
        side_sl = kite.TRANSACTION_TYPE_SELL if sig["side"] == "LONG" else kite.TRANSACTION_TYPE_BUY
        sl_p = round(entry - actual_risk, 1) if sig["side"] == "LONG" else round(entry + actual_risk, 1)
        t1_p = round(entry + (actual_risk*2), 1) if sig["side"] == "LONG" else round(entry - (actual_risk*2), 1)
        oid = kite.place_order(variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE, tradingsymbol=symbol, transaction_type=side_main, quantity=qty, order_type=kite.ORDER_TYPE_SLM, trigger_price=round(entry,1), product=kite.PRODUCT_MIS)
        sid = kite.place_order(variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE, tradingsymbol=symbol, transaction_type=side_sl, quantity=qty, order_type=kite.ORDER_TYPE_SLM, trigger_price=sl_p, product=kite.PRODUCT_MIS)
        ACTIVE_TRADES[symbol] = {"side":sig["side"], "entry":entry, "sl":sl_p, "t1":t1_p, "qty":qty, "main_id":oid, "sl_id":sid, "triggered":False, "half_done":False}
        TRADES_COUNT += 1
        send_telegram(f"✅ TRADING {symbol}\nQty: {qty}\nSL: {sl_p}\nT1: {t1_p}")
        del PENDING_SIGNALS[symbol]
    except Exception as e: send_telegram(f"❌ Error: {e}")

def cancel_old_order(symbol):
    if symbol in ACTIVE_TRADES:
        trade = ACTIVE_TRADES[symbol]
        try:
            kite.cancel_order(kite.VARIETY_REGULAR, trade["main_id"])
            kite.cancel_order(kite.VARIETY_REGULAR, trade["sl_id"])
            global TRADES_COUNT; TRADES_COUNT -= 1; del ACTIVE_TRADES[symbol]
        except: pass

# ================= MONITOR =================
def monitor():
    while True:
        try:
            now = datetime.now(IST).time()
            if now >= EXIT_TIME and ACTIVE_TRADES: exit_all_trades(); break
            if ACTIVE_TRADES:
                orders = kite.orders()
                for sym, t in list(ACTIVE_TRADES.items()):
                    sl_ord = next((o for o in orders if o["order_id"] == t["sl_id"]), None)
                    if sl_ord and sl_ord["status"] == "COMPLETE":
                        send_telegram(f"SL HIT: {sym}"); del ACTIVE_TRADES[sym]; continue
                    if not t["triggered"]:
                        m_ord = next((o for o in orders if o["order_id"] == t["main_id"]), None)
                        if m_ord and m_ord["status"] == "COMPLETE":
                            t["triggered"] = True; send_telegram(f"TRIGGERED: {sym}")
                    if t["triggered"] and not t["half_done"]:
                        ltp = kite.ltp(f"NSE:{sym}")[f"NSE:{sym}"]["last_price"]
                        hit = (t["side"]=="LONG" and ltp>=t["t1"]) or (t["side"]=="SHORT" and ltp<=t["t1"])
                        if hit:
                            kite.place_order(variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE, tradingsymbol=sym, transaction_type=kite.TRANSACTION_TYPE_SELL if t["side"]=="LONG" else kite.TRANSACTION_TYPE_BUY, quantity=t["qty"]//2, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
                            kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t["sl_id"], trigger_price=round(t["entry"],1))
                            t["half_done"] = True; send_telegram(f"T1 DONE: {sym}. SL at Entry.")
            time.sleep(10)
        except: time.sleep(10)

def exit_all_trades():
    for sym, t in list(ACTIVE_TRADES.items()):
        try:
            q = t["qty"]//2 if t["half_done"] else t["qty"]
            kite.place_order(variety=kite.VARIETY_REGULAR, exchange=kite.EXCHANGE_NSE, tradingsymbol=sym, transaction_type=kite.TRANSACTION_TYPE_SELL if t["side"]=="LONG" else kite.TRANSACTION_TYPE_BUY, quantity=q, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS)
            send_telegram(f"EXIT 3:15: {sym}")
        except: pass
    ACTIVE_TRADES.clear()

# ================= RUNNER (FIXED DELAY) =================
def run_bot():
    global LAST_PROCESSED_MINUTE
    send_telegram("V5.8.2 BOT LIVE! Fixed Volume Check & 15s Settle Delay.")
    while True:
        try:
            now = datetime.now(IST)
            if now.minute % 5 == 0 and now.minute != LAST_PROCESSED_MINUTE:
                time.sleep(15) # CRITICAL: Wait 15s for volume data to finalize
                LAST_PROCESSED_MINUTE = now.minute
                read_telegram()
                if not SELECTED_SECTORS or TRADES_COUNT >= MAX_TRADES: continue
                stocks = []
                for s in SELECTED_SECTORS: stocks.extend(SECTOR_STOCKS.get(s, []))
                for symbol in set(stocks):
                    try:
                        token = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]
                        d = kite.historical_data(token, now.replace(hour=9,minute=15,second=0,microsecond=0), now, "5minute")
                        df = pd.DataFrame(d)
                        df.columns = ["date","open","high","low","close","volume"]
                        sig = check_signal(df, symbol)
                        if sig:
                            if symbol in ACTIVE_TRADES and not ACTIVE_TRADES[symbol]["triggered"]: cancel_old_order(symbol)
                            PENDING_SIGNALS[symbol] = sig
                            actual_r = max(sig["risk"], sig["entry"] * MIN_SL_PERCENT)
                            preview_q = min(int(RISK_PER_TRADE/actual_r), int(MAX_MARGIN_ALLOWED/sig["entry"]))
                            disp_sl = round(sig["entry"]-actual_r, 1) if sig["side"]=="LONG" else round(sig["entry"]+actual_r, 1)
                            send_telegram(f"ALERT: {symbol} {sig['side']}\nType: {sig['signal_type']}\nEntry: Rs.{sig['entry']}\nSL: Rs.{disp_sl}\nPlan: {preview_q} Shares\nMargin: Rs.{int(preview_q * sig['entry'])}\nReply YES {symbol}")
                    except: continue
            time.sleep(1)
        except: time.sleep(10)

if __name__ == "__main__":
    import threading
    threading.Thread(target=monitor, daemon=True).start()
    run_bot()
