import os
import requests
from flask import Flask

app = Flask(__name__)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

print("TOKEN:", TOKEN)
print("CHAT_ID:", CHAT_ID)

def send_message(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": text}
    r = requests.post(url, data=data)
    print("Telegram response:", r.text)

send_message("TEST FROM RAILWAY")

@app.route('/')
def home():
    return "Running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
