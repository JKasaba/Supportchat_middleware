# import requests
# from flask import Flask, request, jsonify
# import os

# app = Flask(__name__)

# ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
# ZULIP_BOT_EMAIL = os.environ.get("ZULIP_BOT_EMAIL")
# ZULIP_API_KEY = os.environ.get("ZULIP_API_KEY")
# ZULIP_STREAM = "rt-integration-test-channel"

# @app.route("/webhook/whatsapp", methods=["POST"])
# def handle_whatsapp():
#     data = request.get_json(force=True)
#     print("WhatsApp message:", data)

#     wa_from = data.get("from", "unknown")
#     wa_name = data.get("name", "Unknown User")
#     wa_text = data.get("text", "")

#     zulip_msg = f"📲 Message from *{wa_name}* (`{wa_from}`):\n\n{wa_text}"

#     res = requests.post(ZULIP_API_URL, data={
#         "type": "stream",
#         "to": ZULIP_STREAM,
#         "subject": f"WA #{wa_from}",
#         "content": zulip_msg
#     }, auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY))

#     print("Zulip response:", res.status_code, res.text)
#     return jsonify({"status": "forwarded"}), 200

from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

ZULIP_WHATSAPP_MAP = {}  # Zulip topic → WhatsApp number
ZULIP_API_KEY = os.environ.get("ZULIP_API_KEY")
ZULIP_BOT_EMAIL = os.environ.get("ZULIP_BOT_EMAIL")
ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
WHATSAPP_SEND_ENDPOINT = "https://peppered-bubbly-glade.glitch.me/send"
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
        "subject": f"whatsapp:{wa_from}",
        "content": zulip_msg
    }, auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY))

    print("Zulip response:", res.status_code, res.text)
    return jsonify({"status": "forwarded"}), 200


@app.route("/webhook/zulip", methods=["POST"])
def receive_zulip():
    data = request.json
    topic = data.get("topic")
    message = data.get("content")

    print("Received from Zulip:", topic, message)

    if topic and topic.startswith("whatsapp:") and message:
        phone_number = topic.split("whatsapp:")[1]
        print("Forwarding to WhatsApp:", phone_number, message)
        resp = requests.post(WHATSAPP_SEND_ENDPOINT, json={
            "to": phone_number,
            "message": message
        })
        print("WhatsApp response:", resp.status_code, resp.text)

    return jsonify({"status": "delivered"})


@app.route("/health")
def health():
    return "OK", 200
