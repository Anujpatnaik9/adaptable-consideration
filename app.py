
import os, time
import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect
import requests

# ================= CONFIG (From Railway Variables) =================
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

# YOUR 10 STOCKS
STOCKS = ["SBIN", "TCS", "INFY", "TATAMOTORS", "RELIANCE", "ICICIBANK", "TATASTEEL", "JSWSTEEL", "MARUTI", "ITC"]

RISK_PER_TRADE = 5000
DAYS_TO_TEST = 150

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def run_backtest():
    send_telegram(f"⏳ Backtest Started for {DAYS_TO_TEST} days...")
    total_wins = 0
    total_losses = 0
    total_profit = 0
   
    for symbol in STOCKS:
        try:
            inst = kite.ltp(f"NSE:{symbol}")
            token = inst[f"NSE:{symbol}"]["instrument_token"]
           
            # Fetch data in two chunks to avoid Zerodha limits
            to_date = datetime.now()
            from_date = to_date - timedelta(days=DAYS_TO_TEST)
            mid_date = to_date - timedelta(days=75)
           
            part1 = kite.historical_data(token, from_date, mid_date, "5minute")
            part2 = kite.historical_data(token, mid_date, to_date, "5minute")
            df = pd.DataFrame(part1 + part2)
            df['date'] = pd.to_datetime(df['date'])
           
            days = df.groupby(df['date'].dt.date)
            for date, day_data in days:
                if len(day_data) < 10: continue
                for i in range(3, len(day_data)):
                    current_candles = day_data.iloc[:i+1]
                    last_candle = current_candles.iloc[-1]
                    if last_candle['volume'] == current_candles['volume'].min():
                        # LONG Logic Check (Red candle + Lowest Vol)
                        if last_candle['close'] < last_candle['open']:
                            entry, sl = last_candle['high'], last_candle['low']
                            risk = entry - sl
                            target = entry + (risk * 2)
                            for _, future in day_data.iloc[i+1:].iterrows():
                                if future['high'] >= target:
                                    total_wins += 1
                                    total_profit += (RISK_PER_TRADE * 2); break
                                if future['low'] <= sl:
                                    total_losses += 1
                                    total_profit -= RISK_PER_TRADE; break
                            break
            time.sleep(0.5) # Avoid 'Too many requests' error
        except: continue

    # ================= FINAL REPORT TO TELEGRAM =================
    report = (f"📊 BACKTEST RESULTS\n"
              f"Stocks: {len(STOCKS)}\n"
              f"Period: {DAYS_TO_TEST} Days\n"
              f"-------------------\n"
              f"Total Trades: {total_wins + total_losses}\n"
              f"Wins: {total_wins} ✅\n"
              f"Losses: {total_losses} ❌\n"
              f"Win Rate: {(total_wins/(total_wins+total_losses)*100):.1f}%\n"
              f"Net Profit: Rs. {total_profit}")
    send_telegram(report)

if __name__ == "__main__":
    run_backtest()
