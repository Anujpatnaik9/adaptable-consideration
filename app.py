import os, time, requests
import pandas as pd
from datetime import datetime, timedelta
from kiteconnect import KiteConnect

# ================= CONFIG =================
API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

STOCKS = ["SBIN", "TCS", "INFY", "TATAMOTORS", "RELIANCE", "ICICIBANK", "TATASTEEL", "JSWSTEEL", "MARUTI", "ITC"]
RISK_PER_TRADE = 5000 
DAYS_TO_TEST = 150

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def run_backtest():
    send_telegram("🚀 Running FINAL Backtest (Time + Body Filter)...")
    total_wins, total_losses, total_profit = 0, 0, 0
    
    for symbol in STOCKS:
        try:
            inst = kite.ltp(f"NSE:{symbol}")
            token = inst[f"NSE:{symbol}"]["instrument_token"]
            last_price = inst[f"NSE:{symbol}"]["last_price"]
            
            # Fetch data
            to_date = datetime.now()
            from_date = to_date - timedelta(days=DAYS_TO_TEST)
            mid_date = to_date - timedelta(days=75)
            
            data = kite.historical_data(token, from_date, mid_date, "5minute") + \
                   kite.historical_data(token, mid_date, to_date, "5minute")
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            
            for date, day_data in df.groupby(df['date'].dt.date):
                trades_today = 0
                if len(day_data) < 10: continue
                
                for i in range(3, len(day_data)):
                    if trades_today >= 2: break
                    
                    curr = day_data.iloc[i]
                    c_time = curr['date'].time()
                    
                    # 1. TIME FILTER (9:30 - 10:30)
                    if datetime.strptime("09:30", "%H:%M").time() <= c_time <= datetime.strptime("10:30", "%H:%M").time():
                        
                        # 2. VOLUME FILTER (Lowest so far)
                        history = day_data.iloc[:i+1]
                        if curr['volume'] == history['volume'].min():
                            
                            # 3. BODY FILTER (Candle must be > 0.2% of stock price to avoid 'noise')
                            candle_range = curr['high'] - curr['low']
                            min_range = curr['close'] * 0.002 # 0.2%
                            
                            if candle_range >= min_range:
                                # Logic: Red Candle = LONG at High
                                if curr['close'] < curr['open']:
                                    entry, sl = curr['high'], curr['low']
                                    target = entry + ((entry - sl) * 2)
                                    
                                    for _, future in day_data.iloc[i+1:].iterrows():
                                        if future['high'] >= target:
                                            total_wins += 1
                                            total_profit += (RISK_PER_TRADE * 2)
                                            trades_today += 1
                                            break
                                        if future['low'] <= sl:
                                            total_losses += 1
                                            total_profit -= RISK_PER_TRADE
                                            trades_today += 1
                                            break
            time.sleep(0.6)
        except: continue

    win_rate = (total_wins/(total_wins+total_losses)*100) if (total_wins+total_losses) > 0 else 0
    report = (f"📊 FINAL CLEAN SCORECARD\n"
              f"Filters: 9:30-10:30 + 0.2% Body\n"
              f"Total Trades: {total_wins + total_losses}\n"
              f"Wins: {total_wins} | Losses: {total_losses}\n"
              f"Win Rate: {win_rate:.1f}%\n"
              f"Net Profit: Rs. {total_profit}")
    send_telegram(report)

if __name__ == "__main__":
    run_backtest()
