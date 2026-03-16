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

kite=KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

TRADES_COUNT=0
TRADED_TODAY=set()
ORDER_PLACED=set()

instrument_tokens={}
weakest=[]
strongest=[]

# TELEGRAM

def send_telegram(msg):
    try:
        url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url,data={"chat_id":CHAT_ID,"text":msg})
    except:
        pass


# GET NIFTY200

def get_nifty200():
    url="https://archives.nseindia.com/content/indices/ind_nifty200list.csv"
    df=pd.read_csv(url)
    return list(df["Symbol"])


# CACHE INSTRUMENT TOKENS

def load_tokens(symbols):
    instruments=kite.instruments("NSE")
    for i in instruments:
        if i["tradingsymbol"] in symbols:
            instrument_tokens[i["tradingsymbol"]]=i["instrument_token"]


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


# GET CANDLES

def get_candles(symbol):

    try:

        token=instrument_tokens[symbol]

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


# RELATIVE STRENGTH (RUNS EVERY 5 MIN)

def update_strength(symbols):

    global weakest,strongest

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

    send_telegram("Relative strength updated")


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

        if last.close<pdl and last.close>last.open and last.volume==lowest_vol:

            entry=last.low
            sl=last.high
            risk=sl-entry

            if risk<=0:
                return None

            qty=int((CAPITAL*RISK_PER_TRADE)/risk)

            target=entry-(risk*2)

            return("SHORT",entry,sl,target,max(qty,1))

    if direction=="LONG":

        if last.close>pdh and last.close<last.open and last.volume==lowest_vol:

            entry=last.high
            sl=last.low
            risk=entry-sl

            if risk<=0:
                return None

            qty=int((CAPITAL*RISK_PER_TRADE)/risk)

            target=entry+(risk*2)

            return("LONG",entry,sl,target,max(qty,1))

    return None


# PLACE TRADE

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

                send_telegram("Position closed 3:15")

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

                    send_telegram("Target hit 50% booked")

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

                    send_telegram("Stop Loss Hit")

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

                    send_telegram("Target hit 50% booked")

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

                    send_telegram("Stop Loss Hit")

                    break

            time.sleep(5)

        except:
            break


# BOT LOOP

def bot_loop():

    symbols=get_nifty200()

    load_tokens(symbols)

    send_telegram("🤖 Low Volume Strategy Bot Started – NIFTY200")

    last_strength_update=0

    while True:

        try:

            now=time.time()

            if now-last_strength_update>300:
                update_strength(symbols)
                last_strength_update=now

            direction=get_market_direction()

            scan_list=weakest if direction=="SHORT" else strongest

            for symbol in scan_list:

                if symbol in TRADED_TODAY:
                    continue

                if TRADES_COUNT>=MAX_TRADES:
                    continue

                signal=scan_stock(symbol,direction)

                if signal:

                    side,entry,sl,target,qty=signal

                    send_telegram(
                    f"SETUP {symbol}\n{side}\nEntry {entry}\nSL {sl}\nTarget {target}"
                    )

                    place_trade(symbol,side,entry,sl,target,qty)

            time.sleep(SCAN_INTERVAL)

        except:
            time.sleep(10)


@app.route("/")
def home():
    return "Trading Bot Running"


send_telegram("🚀 Trading Bot Deployed Successfully")

thread=threading.Thread(target=bot_loop)
thread.daemon=True
thread.start()

if __name__=="__main__":
    app.run(host="0.0.0.0",port=8080)
