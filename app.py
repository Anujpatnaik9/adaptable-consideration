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
"NESTLEIND.NS","POWERGRID.NS","ADANIENT.NS","ADANIPORTS.NS",
"ONGC.NS","COALINDIA.NS","NTPC.NS","WIPRO.NS","TECHM.NS",
"INDUSINDBK.NS","JSWSTEEL.NS","HINDALCO.NS",
"DIVISLAB.NS","BAJAJFINSV.NS","HEROMOTOCO.NS","EICHERMOT.NS",
"BRITANNIA.NS","SHREECEM.NS","CIPLA.NS","GRASIM.NS",
"TATACONSUM.NS","DRREDDY.NS","BPCL.NS","UPL.NS",
"SIEMENS.NS","ABB.NS","DLF.NS","GODREJCP.NS",
"PIDILITIND.NS","DABUR.NS","COLPAL.NS","INDIGO.NS",
"HAVELLS.NS","NAUKRI.NS","PAYTM.NS","POLYCAB.NS",
"TATAPOWER.NS","SAIL.NS","VEDL.NS"
]

def send_telegram(msg):

    try:
        url=f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        requests.post(url,data={"chat_id":CHAT_ID,"text":msg})
    except:
        print("Telegram error")

def get_nifty_trend():

    try:

        df=yf.download("^NSEI",period="1d",interval="5m",progress=False)

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

    send_telegram("🚀 PRO NIFTY SCANNER STARTED")

    while True:

        try:

            trend=get_nifty_trend()

            data=yf.download(
                tickers=" ".join(STOCKS),
                period="1d",
                interval="5m",
                group_by="ticker",
                progress=False
            )

        except:

            time.sleep(60)

            continue

        for stock in STOCKS:

            try:

                df=data[stock].dropna()

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

                open1,close1=c1["Open"],c1["Close"]
                open2,close2=c2["Open"],c2["Close"]
                open3,close3=c3["Open"],c3["Close"]

                high3=c3["High"]
                low3=c3["Low"]

                green1=close1>open1
                green2=close2>open2
                red3=close3<open3

                red1=close1<open1
                red2=close2<open2
                green3=close3>open3

                if trend=="BULLISH":

                    if green1 and green2 and red3 and close3>vwap:

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

Market Trend: {trend}
VWAP: Confirmed

Time: {datetime.now().strftime('%H:%M')}
"""

                        send_telegram(msg)

                if trend=="BEARISH":

                    if red1 and red2 and green3 and close3<vwap:

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

Market Trend: {trend}
VWAP: Confirmed

Time: {datetime.now().strftime('%H:%M')}
"""

                        send_telegram(msg)

            except:
                continue

        print("Scanning market...")

        time.sleep(60)

@app.route("/")

def home():

    return "Scanner Running"

threading.Thread(target=scan_market,daemon=True).start()

if __name__=="__main__":

    app.run(host="0.0.0.0",port=8080)
