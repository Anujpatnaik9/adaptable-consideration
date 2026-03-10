from flask import Flask
import requests
import yfinance as yf
import pandas as pd
import threading
import time
import os
from datetime import datetime

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

sent_signals=set()

STOCKS=[
"RELIANCE.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","TCS.NS",
"LT.NS","SBIN.NS","AXISBANK.NS","KOTAKBANK.NS","ITC.NS",
"TATAMOTORS.NS","BAJFINANCE.NS","MARUTI.NS","ASIANPAINT.NS",
"HCLTECH.NS","ULTRACEMCO.NS","SUNPHARMA.NS","TITAN.NS",
"NESTLEIND.NS","POWERGRID.NS","ONGC.NS","COALINDIA.NS",
"NTPC.NS","WIPRO.NS","TECHM.NS","INDUSINDBK.NS","JSWSTEEL.NS",
"HINDALCO.NS","DIVISLAB.NS","CIPLA.NS"
]

def send_telegram(msg):

    try:
        url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url,data={"chat_id":CHAT_ID,"text":msg})
    except:
        print("Telegram error")


def get_nifty_trend():

    try:

        df=yf.download("^NSEI",period="5d",interval="5m",progress=False)

        df["EMA20"]=df["Close"].ewm(span=20).mean()

        last=df.iloc[-1]

        if last["Close"]>last["EMA20"]:
            return "BULLISH"
        else:
            return "BEARISH"

    except:
        return "NEUTRAL"


def candle_strength(candle):

    body=abs(candle["Close"]-candle["Open"])
    rng=candle["High"]-candle["Low"]

    if rng==0:
        return False

    return body/rng>0.6


def calculate_vwap(df):

    tp=(df["High"]+df["Low"]+df["Close"])/3
    vwap=(tp*df["Volume"]).cumsum()/df["Volume"].cumsum()

    return vwap.iloc[-1]


def scan_market():

    send_telegram("🚀 3-CANDLE SCANNER STARTED")

    while True:

        now=datetime.now()

        if now.hour<9 or (now.hour==9 and now.minute<15) or now.hour>=16:
            time.sleep(60)
            continue

        trend=get_nifty_trend()

        for stock in STOCKS:

            try:

                df=yf.download(
                    stock,
                    period="5d",
                    interval="5m",
                    progress=False
                ).dropna()

                if len(df)<20:
                    continue

                vwap=calculate_vwap(df)

                df=df.tail(3)

                c1=df.iloc[0]
                c2=df.iloc[1]
                c3=df.iloc[2]

                if not candle_strength(c1):
                    continue

                if not candle_strength(c2):
                    continue

                vol1=c1["Volume"]
                vol2=c2["Volume"]
                vol3=c3["Volume"]

                if vol3>vol2:
                    continue

                open1,close1=c1["Open"],c1["Close"]
                open2,close2=c2["Open"],c2["Close"]
                open3,close3=c3["Open"],c3["Close"]

                high3=c3["High"]
                low3=c3["Low"]

                signal_key=f"{stock}-{now.strftime('%H:%M')}"

                if signal_key in sent_signals:
                    continue


                if trend=="BULLISH":

                    if close1>open1 and close2>open2 and close3<open3 and close3>vwap:

                        entry=high3
                        stop=low3
                        risk=entry-stop

                        if risk<=0:
                            continue

                        target=entry+risk*2

                        msg=f"""
🚀 LONG SETUP

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Trend: {trend}
VWAP: Confirmed

Time: {now.strftime('%H:%M')}
"""

                        send_telegram(msg)

                        sent_signals.add(signal_key)


                if trend=="BEARISH":

                    if close1<open1 and close2<open2 and close3>open3 and close3<vwap:

                        entry=low3
                        stop=high3
                        risk=stop-entry

                        if risk<=0:
                            continue

                        target=entry-risk*2

                        msg=f"""
🔻 SHORT SETUP

Stock: {stock}

Entry: {round(entry,2)}
Stop Loss: {round(stop,2)}
Target: {round(target,2)}

Trend: {trend}
VWAP: Confirmed

Time: {now.strftime('%H:%M')}
"""

                        send_telegram(msg)

                        sent_signals.add(signal_key)

            except Exception as e:

                print(stock,e)

        print("Scanning market...")

        time.sleep(60)


@app.route("/")

def home():

    return "Scanner Running"


threading.Thread(target=scan_market,daemon=True).start()

if __name__=="__main__":

    app.run(host="0.0.0.0",port=8080)
