import os
import requests
from flask import Flask

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": text
    }
    r = requests.post(url, data=data)
    print("Telegram response:", r.text)

# SEND MESSAGE WHEN BOT STARTS
send_message("🚀 BOT STARTED SUCCESSFULLY")

@app.route('/')
def home():
    return "Bot is running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
