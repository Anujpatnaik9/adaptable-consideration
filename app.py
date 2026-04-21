import time
import math
import requests
import os
from datetime import datetime, timedelta
import pytz
from kiteconnect import KiteConnect
from telegram.ext import Updater, MessageHandler, Filters

# ================= CONFIG =================
API_KEY = os.getenv("API_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not all([API_KEY, ACCESS_TOKEN, TELEGRAM_TOKEN, CHAT_ID]):
    raise Exception("Missing environment variables")

RISK_PER_TRADE = 1000
MAX_CAPITAL_PER_TRADE = 250000
BUFFER_PERCENT = 0.002
TICK_SIZE = 0.05
MAX_ACTIVE_TRADES = 2

TIMEZONE = pytz.timezone("Asia/Kolkata")

# ================= INIT =================
kite = KiteConnect(api_key=API_KEY)
kite.set_access_token(ACCESS_TOKEN)

active_trades = {}

# ================= TELEGRAM =================
def send_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    except:
        pass

# ================= RETRY =================
def retry(func, retries=3, delay=2):
    for i in range(retries):
        try:
            return func()
        except Exception as e:
            if i == retries - 1:
                send_telegram(f"ERROR: {str(e)}")
                raise
            time.sleep(delay)

# ================= UTIL =================
def round_to_tick(price, direction):
    if direction == "UP":
        return math.ceil(price / TICK_SIZE) * TICK_SIZE
    else:
        return math.floor(price / TICK_SIZE) * TICK_SIZE


def get_last_candle(symbol):
    inst = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["instrument_token"]

    now = datetime.now(TIMEZONE)
    end = now.replace(second=0, microsecond=0)
    start = end - timedelta(minutes=5)

    data = kite.historical_data(inst, start, end, "5minute")
    candle = data[-1]

    return candle["high"], candle["low"]


def calculate_qty(entry, sl):
    risk_per_share = abs(entry - sl)
    qty_risk = RISK_PER_TRADE / risk_per_share
    qty_cap = MAX_CAPITAL_PER_TRADE / entry
    return max(1, int(min(qty_risk, qty_cap)))


def cancel_order(order_id):
    try:
        retry(lambda: kite.cancel_order(
            variety=kite.VARIETY_REGULAR,
            order_id=order_id
        ))
        send_telegram("Previous order cancelled")
    except:
        pass

# ================= ORDER FUNCTIONS =================
def place_entry(symbol, direction, entry, qty):
    def order():
        return kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=kite.TRANSACTION_TYPE_BUY if direction == "LONG" else kite.TRANSACTION_TYPE_SELL,
            quantity=qty,
            order_type=kite.ORDER_TYPE_SL,
            price=entry,
            trigger_price=entry,
            product=kite.PRODUCT_MIS
        )
    order_id = retry(order)
    send_telegram(f"{symbol} {direction} Order Placed | Entry: {entry} Qty: {qty}")
    return order_id


def place_sl(symbol, direction, sl, qty):
    def order():
        return kite.place_order(
            variety=kite.VARIETY_REGULAR,
            exchange=kite.EXCHANGE_NSE,
            tradingsymbol=symbol,
            transaction_type=kite.TRANSACTION_TYPE_SELL if direction == "LONG" else kite.TRANSACTION_TYPE_BUY,
            quantity=qty,
            order_type=kite.ORDER_TYPE_SLM,
            trigger_price=sl,
            product=kite.PRODUCT_MIS
        )
    retry(order)
    send_telegram(f"SL Placed at {sl}")


def wait_for_execution(order_id):
    while True:
        orders = kite.orders()
        for o in orders:
            if o["order_id"] == order_id and o["status"] == "COMPLETE":
                return o["average_price"]
        time.sleep(2)

# ================= TRADE MANAGEMENT =================
def manage_trade(symbol, direction, entry, sl, qty):
    target = entry + 2 * (entry - sl) if direction == "LONG" else entry - 2 * (sl - entry)
    half_qty = qty // 2

    sl_moved = False

    while True:
        ltp = kite.ltp(f"NSE:{symbol}")[f"NSE:{symbol}"]["last_price"]

        if not sl_moved:
            if (direction == "LONG" and ltp >= target) or (direction == "SHORT" and ltp <= target):
                retry(lambda: kite.place_order(
                    variety=kite.VARIETY_REGULAR,
                    exchange=kite.EXCHANGE_NSE,
                    tradingsymbol=symbol,
                    transaction_type=kite.TRANSACTION_TYPE_SELL if direction == "LONG" else kite.TRANSACTION_TYPE_BUY,
                    quantity=half_qty,
                    order_type=kite.ORDER_TYPE_MARKET,
                    product=kite.PRODUCT_MIS
                ))

                send_telegram(f"{symbol} Target hit | 50% booked")
                place_sl(symbol, direction, entry, qty - half_qty)
                send_telegram("SL moved to Cost")
                sl_moved = True

        now = datetime.now(TIMEZONE)
        if now.hour == 15 and now.minute >= 15:
            retry(lambda: kite.place_order(
                variety=kite.VARIETY_REGULAR,
                exchange=kite.EXCHANGE_NSE,
                tradingsymbol=symbol,
                transaction_type=kite.TRANSACTION_TYPE_SELL if direction == "LONG" else kite.TRANSACTION_TYPE_BUY,
                quantity=qty,
                order_type=kite.ORDER_TYPE_MARKET,
                product=kite.PRODUCT_MIS
            ))
            send_telegram(f"{symbol} closed at 3:15")
            active_trades.pop(symbol, None)
            break
        time.sleep(2)

# ================= TELEGRAM HANDLER =================
def handle_message(update, context):
    global active_trades
    try:
        text = update.message.text.strip().upper()
        parts = text.split()
        if len(parts) != 2:
            return

        direction, symbol = parts
        send_telegram(f"Signal Received: {direction} {symbol}")

        if len(active_trades) >= MAX_ACTIVE_TRADES:
            send_telegram("Max 2 active trades reached")
            return

        if symbol in active_trades:
            cancel_order(active_trades[symbol]["order_id"])

        high, low = get_last_candle(symbol)

        if direction == "LONG":
            entry = round_to_tick(high, "UP")
            sl = round_to_tick(low * (1 - BUFFER_PERCENT), "DOWN")
        else:
            entry = round_to_tick(low, "DOWN")
            sl = round_to_tick(high * (1 + BUFFER_PERCENT), "UP")

        qty = calculate_qty(entry, sl)
        order_id = place_entry(symbol, direction, entry, qty)

        active_trades[symbol] = {
            "order_id": order_id,
            "direction": direction
        }

        entry_price = wait_for_execution(order_id)
        send_telegram(f"{symbol} Executed at {entry_price}")
        place_sl(symbol, direction, sl, qty)
        manage_trade(symbol, direction, entry_price, sl, qty)

    except Exception as e:
        send_telegram(f"CRITICAL ERROR: {str(e)}")

# ================= RUN =================
send_telegram("Bot Restarted & Running")

updater = Updater(TELEGRAM_TOKEN)
dp = updater.dispatcher
dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

updater.start_polling()
updater.idle()
