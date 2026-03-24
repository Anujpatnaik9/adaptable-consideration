import os, time, requests
import pandas as pd
from datetime import datetime
import pytz
from kiteconnect import KiteConnect
import threading


================= CONFIG =================


API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


TOTAL_CAPITAL = 500000
RISK_PER_TRADE = 5000
MAX_TRADES = 2
EXIT_TIME = "15:15"
IST = pytz.timezone("Asia/Kolkata")


kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)


================= GLOBALS =================


TRADES_TODAY = 0
ACTIVE_TRADES = {}
PENDING_ORDERS = {}
LAST_UPDATE_ID = None
DIRECTION = None
SELECTED_SECTORS = set()


================= FULL SECTORS =================


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


================= TELEGRAM =================


def send_telegram(msg):
try:
url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
except:
pass


def read_telegram():
global LAST_UPDATE_ID, DIRECTION, SELECTED_SECTORS


url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
res = requests.get(url).json()

for item in res.get("result", []):
    uid = item["update_id"]
    if LAST_UPDATE_ID and uid <= LAST_UPDATE_ID:
        continue

    LAST_UPDATE_ID = uid

    if "message" not in item:
        continue

    msg = item["message"]["text"].upper()
    words = msg.split()

    if len(words) >= 2:
        sector, action = words[0], words[1]

        if sector in SECTOR_STOCKS:
            SELECTED_SECTORS.add(sector)
            DIRECTION = "LONG" if action == "HIGH" else "SHORT"
            send_telegram(f"{sector} added for {DIRECTION}")

    if words[0] == "YES" and len(words) >= 2:
        execute_trade(words[1])



================= DATA =================


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



================= SIGNAL =================


def check_signal(df):
last = df.iloc[-1]
lowest_vol = df["volume"].min()


if DIRECTION == "LONG" and last["close"] < last["open"] and last["volume"] <= lowest_vol:
    return {"side":"LONG","entry":last["high"],"sl":last["low"]}

if DIRECTION == "SHORT" and last["close"] > last["open"] and last["volume"] <= lowest_vol:
    return {"side":"SHORT","entry":last["low"],"sl":last["high"]}

return None



================= EXECUTION =================


def place_entry(symbol, side, entry, qty):
return kite.place_order(
variety=kite.VARIETY_REGULAR,
exchange=kite.EXCHANGE_NSE,
tradingsymbol=symbol,
transaction_type=kite.TRANSACTION_TYPE_BUY if side=="LONG" else kite.TRANSACTION_TYPE_SELL,
quantity=qty,
order_type=kite.ORDER_TYPE_SL,
price=round(entry,1),
trigger_price=round(entry,1),
product=kite.PRODUCT_MIS
)


def place_sl(symbol, side, sl, qty):
return kite.place_order(
variety=kite.VARIETY_REGULAR,
exchange=kite.EXCHANGE_NSE,
tradingsymbol=symbol,
transaction_type=kite.TRANSACTION_TYPE_SELL if side=="LONG" else kite.TRANSACTION_TYPE_BUY,
quantity=qty,
order_type=kite.ORDER_TYPE_SLM,
trigger_price=round(sl,1),
product=kite.PRODUCT_MIS
)


def cancel(order_id):
try:
kite.cancel_order(variety=kite.VARIETY_REGULAR, order_id=order_id)
except:
pass


================= TRADE =================


def execute_trade(symbol):
global TRADES_TODAY


if TRADES_TODAY >= MAX_TRADES:
    return

if symbol not in PENDING_ORDERS:
    return

s = PENDING_ORDERS[symbol]

risk = abs(s['entry']-s['sl'])
qty = int(RISK_PER_TRADE / risk)
if qty <= 0:
    return

order_id = place_entry(symbol, s['side'], s['entry'], qty)

PENDING_ORDERS[symbol].update({"order_id":order_id,"qty":qty})
send_telegram(f"ORDER PLACED {symbol}")



================= MONITOR =================


def monitor():
global TRADES_TODAY


while True:
    try:
        orders = kite.orders()

        # Pending to Active
        for sym, p in list(PENDING_ORDERS.items()):
            if "order_id" not in p:
                continue

            o = next((x for x in orders if x['order_id']==p['order_id']), None)

            if o and o['status']=="COMPLETE":
                sl_id = place_sl(sym, p['side'], p['sl'], p['qty'])

                ACTIVE_TRADES[sym] = {**p, "sl_id":sl_id, "half":False}
                TRADES_TODAY += 1
                send_telegram(f"TRADE LIVE {sym}")
                del PENDING_ORDERS[sym]

        # Active trades
        for sym, t in list(ACTIVE_TRADES.items()):
            ltp = kite.ltp(f"NSE:{sym}")[f"NSE:{sym}"]["last_price"]

            risk = abs(t['entry']-t['sl'])
            target = t['entry']+2*risk if t['side']=="LONG" else t['entry']-2*risk

            if not t['half']:
                if (t['side']=="LONG" and ltp>=target) or (t['side']=="SHORT" and ltp<=target):
                    half = t['qty']//2
                    kite.place_order(
                        variety=kite.VARIETY_REGULAR,
                        exchange=kite.EXCHANGE_NSE,
                        tradingsymbol=sym,
                        transaction_type=kite.TRANSACTION_TYPE_SELL if t['side']=="LONG" else kite.TRANSACTION_TYPE_BUY,
                        quantity=half,
                        order_type=kite.ORDER_TYPE_MARKET,
                        product=kite.PRODUCT_MIS
                    )
                    kite.modify_order(variety=kite.VARIETY_REGULAR, order_id=t['sl_id'], trigger_price=t['entry'])
                    t['half']=True
                    send_telegram(f"TARGET HIT {sym}")

        time.sleep(5)

    except Exception as e:
        print(e)
        time.sleep(5)



================= SCANNER =================


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

            # Upgrade logic
            if sym in PENDING_ORDERS and "order_id" in PENDING_ORDERS[sym]:
                cancel(PENDING_ORDERS[sym]['order_id'])
                send_telegram(f"UPDATED {sym} OLD CANCELLED")

            PENDING_ORDERS[sym] = signal
            send_telegram(f"ALERT {sym} {signal['side']} Reply YES {sym}")

        time.sleep(60)

    except Exception as e:
        print(e)
        time.sleep(10)



================= START =================


threading.Thread(target=monitor).start()
scanner()

