from flask import Flask
import os
import time
import threading
import requests
import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

app = Flask(__name__)

# -----------------------------
# ENV VARIABLES
# -----------------------------

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CAPITAL = 500000
RISK_PER_TRADE = 0.01
MAX_TRADES = 2
MAX_DAILY_LOSS = 10000
SCAN_INTERVAL = 300

TRADES_COUNT = 0
ACTIVE_SYMBOLS = []
CRASH_MODE = False

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# -----------------------------
# TELEGRAM
# -----------------------------

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


# -----------------------------
# NIFTY 200
# -----------------------------

def get_nifty200():

    url="https://archives.nseindia.com/content/indices/ind_nifty200list.csv"

    df=pd.read_csv(url)

    return df["Symbol"].tolist()


# -----------------------------
# GET CANDLES
# -----------------------------

def get_candles(symbol):

    try:

        instrument=f"NSE:{symbol}"

        token=kite.ltp(instrument)[instrument]["instrument_token"]

        data=kite.historical_data(
            token,
            datetime.now()-timedelta(days=4),
            datetime.now(),
            "5minute"
        )

        df=pd.DataFrame(data)

        df['date']=pd.to_datetime(df['date']).dt.tz_localize(None)

        return df

    except:

        return None


# -----------------------------
# MARKET CRASH CHECK
# -----------------------------

def check_market_crash():

    global CRASH_MODE

    try:

        inst="NSE:NIFTY 50"

        token=kite.ltp(inst)[inst]["instrument_token"]

        data=kite.historical_data(
            token,
            datetime.now()-timedelta(minutes=15),
            datetime.now(),
            "5minute"
        )

        df=pd.DataFrame(data)

        if len(df)>=2:

            move=((df.iloc[-1].close-df.iloc[0].open)/df.iloc[0].open)*100

            if abs(move)>1.5:

                CRASH_MODE=True

                send_telegram("⚠ MARKET VOLATILITY DETECTED. Trades paused.")

    except:
        pass


# -----------------------------
# SCAN STOCK
# -----------------------------

def scan_stock(symbol):

    df=get_candles(symbol)

    if df is None or len(df)<50:
        return None

    today=datetime.now().date()

    df_today=df[df['date'].dt.date==today]

    df_prev=df[df['date'].dt.date<today]

    if df_today.empty or df_prev.empty:
        return None

    orb=df_today.between_time("09:15","09:30")

    if orb.empty:
        return None

    orb_high=orb.high.max()
    orb_low=orb.low.min()

    pdh=df_prev.high.max()
    pdl=df_prev.low.min()

    last=df_today.iloc[-1]
    prev=df_today.iloc[-2]

    vol_avg=df_today.volume.tail(10).mean()

    # LONG

    if last.close>orb_high and last.close>pdh and last.volume>vol_avg*1.5:

        risk=last.close-prev.low

        if risk<=0:
            return None

        qty=int((CAPITAL*RISK_PER_TRADE)/risk)

        return ("LONG",last.close,prev.low,last.close+risk*2,max(qty,1))

    # SHORT

    if last.close<orb_low and last.close<pdl and last.volume>vol_avg*1.5:

        risk=prev.high-last.close

        if risk<=0:
            return None

        qty=int((CAPITAL*RISK_PER_TRADE)/risk)

        return ("SHORT",last.close,prev.high,last.close-risk*2,max(qty,1))

    return None


# -----------------------------
# PLACE TRADE
# -----------------------------

def place_trade(symbol,side,entry,sl,target,qty):

    global TRADES_COUNT

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

    send_telegram(f"TRADE EXECUTED {symbol} {side} Qty {qty}")

    ACTIVE_SYMBOLS.append(symbol)

    TRADES_COUNT+=1

    threading.Thread(
        target=manage_trade,
        args=(symbol,side,entry,sl,target,qty)
    ).start()


# -----------------------------
# TRADE MANAGEMENT
# -----------------------------

def manage_trade(symbol,side,entry,sl,target,qty):

    half=False

    while True:

        try:

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

                    half=True

                    sl=entry

                    send_telegram(f"{symbol} TARGET HIT. 50% booked.")

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

                    send_telegram(f"{symbol} SL HIT")

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

                    half=True

                    sl=entry

                    send_telegram(f"{symbol} TARGET HIT. 50% booked.")

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

                    send_telegram(f"{symbol} SL HIT")

                    break

            time.sleep(10)

        except:
            break


# -----------------------------
# MAIN BOT LOOP
# -----------------------------

def bot_loop():

    global TRADES_COUNT

    symbols=get_nifty200()

    send_telegram("🤖 Trading Bot Started")

    update_id=None

    pending={}

    while True:

        now=datetime.now()

        check_market_crash()

        if now.strftime("%H:%M")<"09:30":

            time.sleep(30)
            continue

        if now.strftime("%H:%M")>"11:30" or TRADES_COUNT>=MAX_TRADES:

            time.sleep(60)
            continue

        if CRASH_MODE:

            time.sleep(60)
            continue

        for symbol in symbols:

            if symbol in ACTIVE_SYMBOLS:
                continue

            signal=scan_stock(symbol)

            if signal:

                side,entry,sl,target,qty=signal

                send_telegram(
                    f"SETUP {symbol}\n{side}\nEntry {entry}\nSL {sl}\nTarget {target}\nReply YES {symbol}"
                )

                pending[symbol]=signal

        updates=get_updates(update_id)

        for item in updates.get("result",[]):

            update_id=item["update_id"]+1

            text=item.get("message",{}).get("text","").upper()

            if text.startswith("YES"):

                sym=text.split()[-1]

                if sym in pending and TRADES_COUNT<MAX_TRADES:

                    side,entry,sl,target,qty=pending[sym]

                    place_trade(sym,side,entry,sl,target,qty)

                    del pending[sym]

        time.sleep(SCAN_INTERVAL)


# -----------------------------
# FLASK KEEP ALIVE
# -----------------------------

@app.route("/")

def home():

    return "Trading Bot Running"


thread=threading.Thread(target=bot_loop)

thread.daemon=True

thread.start()


if __name__=="__main__":

    app.run(host="0.0.0.0",port=8080)
