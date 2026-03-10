from flask import Flask
import requests
import os

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": msg
    })

@app.route("/")
def home():
    return "Bot running"

if __name__ == "__main__":

    print("Sending telegram test message...")

    send_telegram("✅ BOT SUCCESSFULLY CONNECTED TO TELEGRAM")

    app.run(host="0.0.0.0", port=8080)
