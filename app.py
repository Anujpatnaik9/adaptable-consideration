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
    send_telegram("⏳ Running STAGE 2 Backtest (9:30-10:30 Only)...")
    total_wins, total_losses, total_profit = 0, 0, 0
    
    for symbol in STOCKS:
        try:
            inst = kite.ltp(f"NSE:{symbol}")
            token = inst[f"NSE:{symbol}"]["instrument_token"]
            
            to_date = datetime.now()
            from_date = to_date - timedelta(days=DAYS_TO_TEST)
            mid_date = to_date - timedelta(days=75)
            
            df = pd.DataFrame(kite.historical_data(token, from_date, mid_date, "5minute") + 
                             kite.historical_data(token, mid_date, to_date, "5minute"))
            df['date'] = pd.to_datetime(df['date'])
            
            for date, day_data in df.groupby(df['date'].dt.date):
                trades_today = 0
                if len(day_data) < 10: continue
                
                # Scan candles
                for i in range(3, len(day_data)):
                    if trades_today >= 2: break # Max 2 trades per stock/day rule
                    
                    current_candle = day_data.iloc[i]
                    candle_time = current_candle['date'].time()
                    
                    # --- NEW TIME FILTER ---
                    if datetime.strptime("09:30", "%H:%M").time() <= candle_time <= datetime.strptime("10:30", "%H:%M").time():
                        
                        history_so_far = day_data.iloc[:i+1]
                        if current_candle['volume'] == history_so_far['volume'].min():
                            # Logic: If Red, try LONG at High
                            if current_candle['close'] < current_candle['open']:
                                entry, sl = current_candle['high'], current_candle['low']
                                risk = entry - sl
                                if risk <= 0: continue
                                target = entry + (risk * 2)
                                
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

    report = (f"📊 FINAL SCORECARD (STRICT)\n"
              f"Time: 9:30 - 10:30 AM\n"
              f"Trades: {total_wins + total_losses}\n"
              f"Wins: {total_wins} ✅ | Losses: {total_losses} ❌\n"
              f"Win Rate: {(total_wins/(total_wins+total_losses)*100 if total_wins+total_losses > 0 else 0):.1f}%\n"
              f"Net Profit: Rs. {total_profit}")
    send_telegram(report)

if __name__ == "__main__":
    run_backtest()
