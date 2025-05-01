import requests
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
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
