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

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

def run_backtest_s5():
    send_telegram("🔥 Running S5 MOMENTUM Backtest (9:15-9:25 Breakout)...")
    total_pnl, wins, losses, breakevens = 0, 0, 0, 0
    
    for symbol in STOCKS:
        try:
            inst = kite.ltp(f"NSE:{symbol}")
            token = inst[f"NSE:{symbol}"]["instrument_token"]
            
            # Fetch 150 days
            df = pd.DataFrame(kite.historical_data(token, datetime.now()-timedelta(days=150), datetime.now(), "5minute"))
            if df.empty: continue
            df['date'] = pd.to_datetime(df['date'])
            
            for date, day_data in df.groupby(df['date'].dt.date):
                if len(day_data) < 10: continue
                
                # 1. SET S5 RANGE (9:15 to 9:25 - first two 5-min candles)
                s5_range_data = day_data.iloc[:2] 
                s5_high = s5_range_data['high'].max()
                s5_low = s5_range_data['low'].min()
                
                trades_today = 0
                # 2. LOOK FOR BREAKOUT (After 9:25)
                for i in range(2, len(day_data)):
                    if trades_today >= 1: break # S5 is usually one strong move
                    curr = day_data.iloc[i]
                    
                    # Entry: Candle closes above 9:25 High
                    if curr['close'] > s5_high:
                        entry = curr['close']
                        sl = s5_low # Stop loss at the bottom of the opening range
                        risk = entry - sl
                        if risk <= 0 or risk > (entry * 0.02): continue # Skip if risk is too high (>2%)
                        
                        t1, t2 = entry + risk, entry + (risk * 2)
                        t1_hit = False
                        
                        for _, future in day_data.iloc[i+1:].iterrows():
                            if not t1_hit:
                                if future['high'] >= t1:
                                    t1_hit = True
                                    total_pnl += (RISK_PER_TRADE / 2)
                                elif future['low'] <= sl:
                                    total_pnl -= RISK_PER_TRADE
                                    losses += 1; trades_today += 1; break
                            else:
                                if future['high'] >= t2:
                                    total_pnl += RISK_PER_TRADE
                                    wins += 1; trades_today += 1; break
                                elif future['low'] <= entry: # Trail to Cost
                                    breakevens += 1; trades_today += 1; break
            time.sleep(0.3)
        except: continue

    report = (f"🚀 S5 SCORECARD (150 DAYS)\n"
              f"Strategy: 9:15-9:25 Breakout\n"
              f"Full Wins (1:2): {wins}\n"
              f"Partial (1:1+Cost): {breakevens}\n"
              f"Full Losses: {losses}\n"
              f"-------------------\n"
              f"Net PnL: Rs. {total_pnl:.0f}")
    send_telegram(report)

if __name__ == "__main__":
    run_backtest_s5()
