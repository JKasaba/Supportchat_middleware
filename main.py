# from flask import Flask, request, jsonify

# app = Flask(__name__)

# @app.route("/webhook/whatsapp", methods=["POST"])
# def handle_webhook():
#     data = request.get_json(force=True)
#     print("📩 Received WhatsApp webhook:", data)
#     return jsonify({"status": "received"}), 200

# @app.route("/", methods=["GET"])
# def index():
#     return "Flask WhatsApp webhook is running!", 200

# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=5000)

import requests
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

ZULIP_API_URL = "https://your-org.zulipchat.com/api/v1/messages"
ZULIP_BOT_EMAIL = os.environ.get("ZULIP_BOT_EMAIL")
ZULIP_API_KEY = os.environ.get("ZULIP_API_KEY")
ZULIP_STREAM = "rt-integration-test-channel"

@app.route("/webhook/whatsapp", methods=["POST"])
def handle_whatsapp():
    data = request.get_json(force=True)
    print("WhatsApp message:", data)

    wa_from = data.get("from", "unknown")
    wa_name = data.get("name", "Unknown User")
    wa_text = data.get("text", "")

    zulip_msg = f"📲 Message from *{wa_name}* (`{wa_from}`):\n\n{wa_text}"

    res = requests.post(ZULIP_API_URL, data={
        "type": "stream",
        "to": ZULIP_STREAM,
        "subject": f"WA #{wa_from}",
        "content": zulip_msg
    }, auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY))

    print("Zulip response:", res.status_code, res.text)
    return jsonify({"status": "forwarded"}), 200
