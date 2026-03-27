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
    send_telegram("🎯 Running Final UNFILTERED Backtest (Smart Exit Enabled)...")
    total_pnl, wins, losses, breakevens = 0, 0, 0, 0
    
    for symbol in STOCKS:
        try:
            # Fetch data (150 days)
            inst = kite.ltp(f"NSE:{symbol}")
            token = inst[f"NSE:{symbol}"]["instrument_token"]
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=150)
            
            # Simplified data fetch to ensure we get results
            data = kite.historical_data(token, from_dt, to_dt, "5minute")
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            
            for date, day_data in df.groupby(df['date'].dt.date):
                trades_today = 0
                for i in range(3, len(day_data)):
                    if trades_today >= 2: break
                    curr = day_data.iloc[i]
                    
                    # 1. TIME FILTER ONLY (9:30 - 10:30)
                    if datetime.strptime("09:30", "%H:%M").time() <= curr['date'].time() <= datetime.strptime("10:30", "%H:%M").time():
                        
                        # 2. LOW VOLUME SIGNAL
                        if curr['volume'] == day_data.iloc[:i+1]['volume'].min():
                            
                            # LONG Scenario: Entry @ High, SL @ Low
                            entry, sl = curr['high'], curr['low']
                            risk = entry - sl
                            if risk <= 0: continue
                            
                            t1, t2 = entry + risk, entry + (risk * 2)
                            t1_hit = False
                            
                            for _, future in day_data.iloc[i+1:].iterrows():
                                if not t1_hit:
                                    if future['high'] >= t1:
                                        t1_hit = True
                                        total_pnl += (RISK_PER_TRADE / 2) # Profit 50%
                                    elif future['low'] <= sl:
                                        total_pnl -= RISK_PER_TRADE # Full Loss
                                        losses += 1; trades_today += 1; break
                                else:
                                    if future['high'] >= t2:
                                        total_pnl += RISK_PER_TRADE # Profit other 50%
                                        wins += 1; trades_today += 1; break
                                    elif future['low'] <= entry: # Trailing SL at Cost
                                        breakevens += 1; trades_today += 1; break
            time.sleep(0.3)
        except: continue

    report = (f"📈 SMART UNFILTERED SCORE\n"
              f"Full Wins (1:2): {wins}\n"
              f"Partial Wins (1:1 + Cost): {breakevens}\n"
              f"Full Losses: {losses}\n"
              f"-------------------\n"
              f"Net PnL: Rs. {total_pnl:.0f}")
    send_telegram(report)

if __name__ == "__main__":
    run_backtest()
