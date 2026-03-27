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

def run_backtest():
    send_telegram("🛡️ Running TREND-FILTERED Backtest (Price > 9:15 Open Only)...")
    total_pnl, wins, losses, breakevens = 0, 0, 0, 0
    
    for symbol in STOCKS:
        try:
            inst = kite.ltp(f"NSE:{symbol}")
            token = inst[f"NSE:{symbol}"]["instrument_token"]
            
            # Fetch 150 days in chunks
            to_date = datetime.now()
            from_date = to_date - timedelta(days=150)
            mid_date = to_date - timedelta(days=75)
            
            df = pd.DataFrame(kite.historical_data(token, from_date, mid_date, "5minute") + 
                             kite.historical_data(token, mid_date, to_date, "5minute"))
            if df.empty: continue
            df['date'] = pd.to_datetime(df['date'])
            
            for date, day_data in df.groupby(df['date'].dt.date):
                if len(day_data) < 5: continue
                
                # --- TREND FILTER: Get the 9:15 Opening Price ---
                opening_price = day_data.iloc[0]['open']
                trades_today = 0
                
                for i in range(3, len(day_data)):
                    if trades_today >= 2: break
                    curr = day_data.iloc[i]
                    
                    # 1. TIME FILTER (9:30 - 10:30)
                    if datetime.strptime("09:30", "%H:%M").time() <= curr['date'].time() <= datetime.strptime("10:30", "%H:%M").time():
                        
                        # 2. TREND FILTER: ONLY LONG IF PRICE > OPEN
                        if curr['close'] > opening_price:
                            
                            # 3. VOLUME SIGNAL (Lowest Volume)
                            if curr['volume'] == day_data.iloc[:i+1]['volume'].min():
                                if curr['close'] < curr['open']: # Look for the Red Candle signal
                                    entry, sl = curr['high'], curr['low']
                                    risk = entry - sl
                                    if risk <= 0: continue
                                    
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
                                            elif future['low'] <= entry:
                                                breakevens += 1; trades_today += 1; break
            time.sleep(0.4)
        except: continue

    report = (f"🏆 TREND-FILTERED RESULTS\n"
              f"Rule: Price > 9:15 Open\n"
              f"Full Wins (1:2): {wins}\n"
              f"Partial (1:1+Cost): {breakevens}\n"
              f"Full Losses: {losses}\n"
              f"-------------------\n"
              f"Net PnL: Rs. {total_pnl:.0f}")
    send_telegram(report)

if __name__ == "__main__":
    run_backtest()
