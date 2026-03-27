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
    send_telegram("🧠 Running SMART Backtest (50% Square-off + Trail SL to Cost)...")
    total_pnl = 0
    wins, losses, breakevens = 0, 0, 0
    
    for symbol in STOCKS:
        try:
            inst = kite.ltp(f"NSE:{symbol}")
            token = inst[f"NSE:{symbol}"]["instrument_token"]
            
            df = pd.DataFrame(kite.historical_data(token, datetime.now()-timedelta(days=150), datetime.now(), "5minute"))
            df['date'] = pd.to_datetime(df['date'])
            
            for date, day_data in df.groupby(df['date'].dt.date):
                trades_today = 0
                for i in range(3, len(day_data)):
                    if trades_today >= 2: break
                    curr = day_data.iloc[i]
                    
                    # Filters: Time (9:30-10:30) + Low Vol + 0.2% Body
                    if datetime.strptime("09:30", "%H:%M").time() <= curr['date'].time() <= datetime.strptime("10:30", "%H:%M").time():
                        if curr['volume'] == day_data.iloc[:i+1]['volume'].min() and (curr['high']-curr['low']) >= (curr['close']*0.002):
                            
                            if curr['close'] < curr['open']: # LONG Scenario
                                entry = curr['high']
                                initial_sl = curr['low']
                                risk = entry - initial_sl
                                target1 = entry + risk       # 1:1 Ratio
                                target2 = entry + (risk * 2) # 1:2 Ratio
                                
                                # Track the trade
                                t1_hit = False
                                for _, future in day_data.iloc[i+1:].iterrows():
                                    # Case 1: Hit T1 (Book 50%, Move SL to Cost)
                                    if not t1_hit and future['high'] >= target1:
                                        t1_hit = True
                                        total_pnl += (RISK_PER_TRADE / 2) # Profit on first half
                                    
                                    # Case 2: Hit Initial SL (Before T1)
                                    if not t1_hit and future['low'] <= initial_sl:
                                        total_pnl -= RISK_PER_TRADE
                                        losses += 1; trades_today += 1; break
                                        
                                    # Case 3: Hit Target 2 (After T1)
                                    if t1_hit and future['high'] >= target2:
                                        total_pnl += (RISK_PER_TRADE) # Profit on second half (1:2)
                                        wins += 1; trades_today += 1; break
                                        
                                    # Case 4: Hit Trail SL at Cost (After T1)
                                    if t1_hit and future['low'] <= entry:
                                        # Second half exits at 0 profit/loss
                                        breakevens += 1; trades_today += 1; break
            time.sleep(0.5)
        except: continue

    report = (f"📈 SMART SCORECARD\n"
              f"Strategy: 50% Book @ 1:1 + Trail SL\n"
              f"Full Wins (1:2): {wins}\n"
              f"Partial Wins (Hit T1 then Cost): {breakevens}\n"
              f"Full Losses: {losses}\n"
              f"-------------------\n"
              f"Net PnL: Rs. {total_pnl:.0f}")
    send_telegram(report)

if __name__ == "__main__":
    run_backtest()
