from flask import Flask
import os
import time
import threading
import requests
import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

app = Flask(__name__)

API_KEY=os.getenv("KITE_API_KEY")
ACCESS_TOKEN=os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("TELEGRAM_CHAT_ID")

CAPITAL=500000
RISK_PER_TRADE=0.01
MAX_TRADES=2
SCAN_INTERVAL=60

TRADES_COUNT=0
ACTIVE_SYMBOLS=[]
TRADED_TODAY=set()
SIGNALLED_SYMBOLS=set()
ORDER_PLACED=set()

kite=KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# TELEGRAM

def send_telegram(msg):
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url,data={"chat_id":CHAT_ID,"text":msg})
    except:
        pass

def get_updates(offset=None):
    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params={"timeout":1,"offset":offset}
    return requests.get(url,params=params).json()

# NIFTY200 LIST

def get_nifty200():

    url="https://archives.nseindia.com/content/indices/ind_nifty200list.csv"

    df=pd.read_csv(url)

    return list(df["Symbol"])

# MARKET DIRECTION

def get_market_direction():

    try:

        url="https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
        headers={"User-Agent":"Mozilla/5.0"}

        data=requests.get(url,headers=headers).json()

        adv=data["advance"]["advances"]
        dec=data["advance"]["declines"]

        if dec>adv:
            return "SHORT"

        if adv>dec:
            return "LONG"

    except:
        pass

    return None

# CANDLES

def get_candles(symbol):

    try:

        inst=f"NSE:{symbol}"
        token=kite.ltp(inst)[inst]["instrument_token"]

        data=kite.historical_data(
        token,
        datetime.now()-timedelta(days=3),
        datetime.now(),
        "5minute"
        )

        df=pd.DataFrame(data)
        df['date']=pd.to_datetime(df['date']).dt.tz_localize(None)

        return df

    except:
        return None

# RELATIVE STRENGTH

def rank_relative_strength(symbols):

    scores=[]

    for s in symbols:

        df=get_candles(s)

        if df is None or len(df)<5:
            continue

        change=(df.close.iloc[-1]-df.close.iloc[-5])/df.close.iloc[-5]

        scores.append((s,change))

    ranked=sorted(scores,key=lambda x:x[1])

    weakest=[x[0] for x in ranked[:20]]
    strongest=[x[0] for x in ranked[-20:]]

    return weakest,strongest

# SCANNER

def scan_stock(symbol,direction):

    df=get_candles(symbol)

    if df is None or len(df)<20:
        return None

    today=datetime.now().date()

    df_today=df[df['date'].dt.date==today]
    df_prev=df[df['date'].dt.date<today]

    if df_today.empty or df_prev.empty:
        return None

    now=datetime.now().time()

    if not(now>=datetime.strptime("09:30","%H:%M").time() and now<=datetime.strptime("10:30","%H:%M").time()):
        return None

    pdh=df_prev.high.max()
    pdl=df_prev.low.min()

    lowest_vol=df_today.volume.min()

    last=df_today.iloc[-1]

    if direction=="SHORT":

        if last.close<pdl and last.close>last.open:

            if last.volume==lowest_vol:

                entry=last.low
                sl=last.high
                risk=sl-entry

                if risk<=0:
                    return None

                qty=int((CAPITAL*RISK_PER_TRADE)/risk)
                target=entry-(risk*2)

                return("SHORT",entry,sl,target,max(qty,1))

    if direction=="LONG":

        if last.close>pdh and last.close<last.open:

            if last.volume==lowest_vol:

                entry=last.high
                sl=last.low
                risk=entry-sl

                if risk<=0:
                    return None

                qty=int((CAPITAL*RISK_PER_TRADE)/risk)
                target=entry+(risk*2)

                return("LONG",entry,sl,target,max(qty,1))

    return None

# TRADE

def place_trade(symbol,side,entry,sl,target,qty):

    global TRADES_COUNT

    if symbol in ORDER_PLACED:
        return

    ORDER_PLACED.add(symbol)

    ttype=kite.TRANSACTION_TYPE_BUY if side=="LONG" else kite.TRANSACTION_TYPE_SELL

    kite.place_order(
    variety=kite.VARIETY_REGULAR,
    exchange=kite.EXCHANGE_NSE,
    tradingsymbol=symbol,
    transaction_type=ttype,
    quantity=qty,
    order_type=kite.ORDER_TYPE_MARKET,
    product=kite.PRODUCT_MIS
    )

    send_telegram(f"TRADE EXECUTED {symbol}")

    ACTIVE_SYMBOLS.append(symbol)
    TRADED_TODAY.add(symbol)

    TRADES_COUNT+=1

    threading.Thread(
    target=manage_trade,
    args=(symbol,side,entry,sl,target,qty)
    ).start()

# TRADE MANAGEMENT

def manage_trade(symbol,side,entry,sl,target,qty):

    half=False

    while True:

        try:

            now=datetime.now()

            if now.strftime("%H:%M")>"15:15":

                kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=kite.EXCHANGE_NSE,
                tradingsymbol=symbol,
                transaction_type=kite.TRANSACTION_TYPE_SELL if side=="LONG" else kite.TRANSACTION_TYPE_BUY,
                quantity=qty,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS
                )

                send_telegram("Force exit 3:15")

                break

            ltp=kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]

            if side=="LONG":

                if ltp>=target and not half:

                    kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=qty//2,
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                    )

                    sl=entry
                    half=True

                if ltp<=sl:

                    kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=kite.TRANSACTION_TYPE_SELL,
                    quantity=qty,
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                    )

                    break

            if side=="SHORT":

                if ltp<=target and not half:

                    kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=qty//2,
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                    )

                    sl=entry
                    half=True

                if ltp>=sl:

                    kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=kite.TRANSACTION_TYPE_BUY,
                    quantity=qty,
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                    )

                    break

            time.sleep(5)

        except:
            break

# BOT LOOP

def bot_loop():

    global TRADES_COUNT

    symbols=get_nifty200()

    weakest,strongest=rank_relative_strength(symbols)

    send_telegram("BOT STARTED")

    update_id=None
    pending={}

    while True:

        direction=get_market_direction()

        if direction=="SHORT":
            scan_list=weakest
        else:
            scan_list=strongest

        for symbol in scan_list:

            if symbol in TRADED_TODAY:
                continue

            if symbol in SIGNALLED_SYMBOLS:
                continue

            if TRADES_COUNT>=MAX_TRADES:
                continue

            signal=scan_stock(symbol,direction)

            if signal:

                side,entry,sl,target,qty=signal

                send_telegram(
                f"SETUP {symbol}\n{side}\nEntry {entry}\nSL {sl}\nTarget {target}\nReply YES {symbol}"
                )

                SIGNALLED_SYMBOLS.add(symbol)
                pending[symbol]=signal

        updates=get_updates(update_id)

        for item in updates.get("result",[]):

            update_id=item["update_id"]+1

            text=item.get("message",{}).get("text","").upper()

            if text.startswith("YES"):

                sym=text.split()[-1]

                if sym in pending:

                    side,entry,sl,target,qty=pending[sym]

                    place_trade(sym,side,entry,sl,target,qty)

                    del pending[sym]

        time.sleep(SCAN_INTERVAL)

@app.route("/")

def home():
    return "Trading Bot Running"

thread=threading.Thread(target=bot_loop)
thread.daemon=True
thread.start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080)
