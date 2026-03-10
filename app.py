import os
import requests
import time

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

print("Bot started")

send("✅ SUCCESS: Railway deployment works and Telegram is connected")

while True:
    print("Bot running...")
    time.sleep(60)
