# from flask import Flask, request, jsonify
# import os
# import requests

# app = Flask(__name__)

# ZULIP_WHATSAPP_MAP = {}  # Zulip topic → WhatsApp number
# ZULIP_API_KEY = os.environ.get("ZULIP_API_KEY")
# ZULIP_BOT_EMAIL = os.environ.get("ZULIP_BOT_EMAIL")
# ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
# WHATSAPP_SEND_ENDPOINT = "https://peppered-bubbly-glade.glitch.me/send"
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
#         "subject": f"whatsapp:{wa_from}",
#         "content": zulip_msg
#     }, auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY))

#     print("Zulip response:", res.status_code, res.text)
#     return jsonify({"status": "forwarded"}), 200


# @app.route("/webhook/zulip", methods=["POST"])
# def receive_zulip():
#     payload = request.get_json(force=True)
#     print("Received from Zulip:", payload)

#     message = payload.get("message", {})
#     topic = message.get("subject")
#     content = message.get("content")

#     if topic and topic.startswith("whatsapp:") and content:
#         phone_number = topic.split("whatsapp:")[1]

#         cleaned_message = content.replace("@**correspondence**", "").replace("@correspondence", "").strip()


#         print("Forwarding to WhatsApp:", phone_number, cleaned_message)
#         resp = requests.post(WHATSAPP_SEND_ENDPOINT, json={
#             "to": phone_number,
#             "message": cleaned_message
#         })
#         print("WhatsApp response:", resp.status_code, resp.text)

#     return jsonify({"status": "delivered"})



# @app.route("/health")
# def health():
#     return "OK", 200

#main.py  – Render‑only WhatsApp ↔ Zulip bridge
from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

# ─── Env vars you must add in Render ───────────────────────────────────────────
GRAPH_API_TOKEN     = os.environ["GRAPH_API_TOKEN"]      # WhatsApp Cloud API
WEBHOOK_VERIFY_TOKEN= os.environ["WEBHOOK_VERIFY_TOKEN"] # WhatsApp webhook verify
ZULIP_API_KEY       = os.environ["ZULIP_API_KEY"]
ZULIP_BOT_EMAIL     = os.environ["ZULIP_BOT_EMAIL"]
PORT                = int(os.getenv("PORT", 5000))       # Render sets this

# ─── Constants you might tune ──────────────────────────────────────────────────
ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
ZULIP_STREAM  = "rt-integration-test-channel"

# -----------------------------------------------------------------------------#
# 1.  WhatsApp webhook  (GET for verification, POST for messages)
# -----------------------------------------------------------------------------#
@app.get("/webhook")
def verify_webhook():
    mode, token = request.args.get("hub.mode"), request.args.get("hub.verify_token")
    challenge   = request.args.get("hub.challenge")
    if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
        print("✅  WhatsApp webhook verified")
        return challenge, 200
    return "Forbidden", 403


@app.post("/webhook")
def receive_whatsapp():
    body = request.get_json(force=True)
    print("Incoming WhatsApp payload:", body)

    message = body.get("entry", [{}])[0].get("changes", [{}])[0]\
                  .get("value", {}).get("messages", [{}])[0]

    if message and message.get("type") == "text":
        phone_id  = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
        wa_from   = message["from"]
        wa_text   = message["text"]["body"]
        wa_name   = (body["entry"][0]["changes"][0]["value"]
                         .get("contacts", [{}])[0].get("profile", {}).get("name", "Unknown"))

        # 1‑a) Forward to Zulip --------------------------------------------------
        zulip_msg = f"📲 Message from *{wa_name}* ({wa_from}):\n\n{wa_text}"
        z = requests.post(
            ZULIP_API_URL,
            data = {
                "type": "stream",
                "to":   ZULIP_STREAM,
                "subject": f"whatsapp:{wa_from}",
                "content": zulip_msg
            },
            auth = (ZULIP_BOT_EMAIL, ZULIP_API_KEY),
            timeout = 10
        )
        print("Zulip →", z.status_code, z.text)

        # 1‑b) Echo (optional) + mark as read -----------------------------------
        graph_base = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
        headers    = {"Authorization": f"Bearer {GRAPH_API_TOKEN}"}

        echo_resp = requests.post(graph_base, headers=headers, json={
            "messaging_product": "whatsapp",
            "to": wa_from,
            "text": { "body": f"Echo: {wa_text}" },
            "context": { "message_id": message["id"] }
        })
        read_resp = requests.post(graph_base, headers=headers, json={
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message["id"]
        })
        print("Echo →", echo_resp.status_code, echo_resp.text)
        print("Read →", read_resp.status_code, read_resp.text)

    return "", 200


# -----------------------------------------------------------------------------#
# 2.  Outbound /send endpoint  (used by /webhook/zulip)                         #
# -----------------------------------------------------------------------------#
@app.post("/send")
def send_whatsapp():
    to  = request.json.get("to")
    msg = request.json.get("message", "")
    print("/send ⇢", { "to": to, "message": msg })

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": { "body": msg }
    }
    resp = requests.post(
        "https://graph.facebook.com/v18.0/599049466632787/messages",
        json = payload,
        headers = {
            "Authorization": f"Bearer {GRAPH_API_TOKEN}",
            "Content-Type": "application/json"
        },
        timeout = 10
    )
    print("Graph resp →", resp.status_code, resp.text)
    return jsonify({"status": "sent", "response": resp.json()}), 200


# -----------------------------------------------------------------------------#
# 3.  Zulip → WhatsApp hook                                                     #
# -----------------------------------------------------------------------------#
@app.post("/webhook/zulip")
def receive_zulip():
    payload = request.get_json(force=True)
    print("Incoming Zulip payload:", payload)

    message = payload.get("message", {})
    topic   = message.get("subject", "")
    content = message.get("content", "")

    if topic.startswith("whatsapp:") and content:
        phone_number = topic.split("whatsapp:", 1)[1].strip()

        cleaned = (content
                   .replace("@**correspondence**", "")
                   .replace("@correspondence", "")
                   .strip())

        print("Forwarding Zulip → WhatsApp:", phone_number, cleaned)
        # Local call to /send so we keep one code path
        return send_whatsapp.__wrapped__(to=phone_number, message=cleaned)  # type: ignore

    return jsonify({"status": "ignored"}), 200


# -----------------------------------------------------------------------------#
@app.get("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)

# from flask import Flask, request, jsonify
# import os
# import requests

# app = Flask(__name__)

# # Environment variables
# ZULIP_API_KEY = os.environ.get("ZULIP_API_KEY")
# ZULIP_BOT_EMAIL = os.environ.get("ZULIP_BOT_EMAIL")
# ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
# ZULIP_STREAM = "rt-integration-test-channel"
# GRAPH_API_TOKEN = os.environ.get("GRAPH_API_TOKEN")
# BUSINESS_PHONE_NUMBER_ID = os.environ.get("BUSINESS_PHONE_NUMBER_ID")
# WEBHOOK_VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN")


# @app.route("/webhook", methods=["POST"])
# def whatsapp_webhook():
#     data = request.get_json(force=True)
#     print("Incoming webhook message:", data)

#     message = data.get("entry", [{}])[0].get("changes", [{}])[0].get("value", {}).get("messages", [{}])[0]

#     if message.get("type") == "text":
#         wa_from = message.get("from")
#         wa_text = message["text"]["body"]
#         wa_name = data["entry"][0]["changes"][0]["value"]["contacts"][0]["profile"].get("name", "Unknown")
#         business_phone_number_id = data["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]

#         # Forward to Zulip
#         requests.post(f"{request.url_root}webhook/whatsapp", json={
#             "from": wa_from,
#             "name": wa_name,
#             "text": wa_text
#         })

#         # Optional echo reply
#         echo_payload = {
#             "messaging_product": "whatsapp",
#             "to": wa_from,
#             "text": {"body": f"Echo: {wa_text}"},
#             "context": {"message_id": message["id"]}
#         }

#         headers = {
#             "Authorization": f"Bearer {GRAPH_API_TOKEN}",
#             "Content-Type": "application/json"
#         }

#         requests.post(
#             f"https://graph.facebook.com/v18.0/{business_phone_number_id}/messages",
#             json=echo_payload,
#             headers=headers
#         )

#         # Mark as read
#         requests.post(
#             f"https://graph.facebook.com/v18.0/{business_phone_number_id}/messages",
#             json={
#                 "messaging_product": "whatsapp",
#                 "status": "read",
#                 "message_id": message["id"]
#             },
#             headers=headers
#         )

#     return jsonify({"status": "received"}), 200


# @app.route("/webhook", methods=["GET"])
# def verify_webhook():
#     mode = request.args.get("hub.mode")
#     token = request.args.get("hub.verify_token")
#     challenge = request.args.get("hub.challenge")

#     if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
#         print("Webhook verified successfully!")
#         return challenge, 200
#     else:
#         return "Forbidden", 403


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
#         "subject": f"whatsapp:{wa_from}",
#         "content": zulip_msg
#     }, auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY))

#     print("Zulip response:", res.status_code, res.text)
#     return jsonify({"status": "forwarded"}), 200


# @app.route("/webhook/zulip", methods=["POST"])
# def receive_zulip():
#     payload = request.get_json(force=True)
#     print("Received from Zulip:", payload)

#     message = payload.get("message", {})
#     topic = message.get("subject")
#     content = message.get("content")

#     if topic and topic.startswith("whatsapp:") and content:
#         phone_number = topic.split("whatsapp:")[1]
#         cleaned_message = content.replace("@**correspondence**", "").replace("@correspondence", "").strip()

#         print("Forwarding to WhatsApp:", phone_number, cleaned_message)
#         resp = requests.post(f"{request.url_root}send", json={
#             "to": phone_number,
#             "message": cleaned_message
#         })
#         print("WhatsApp response:", resp.status_code, resp.text)

#     return jsonify({"status": "delivered"})


# @app.route("/send", methods=["POST"])
# def send_whatsapp():
#     data = request.get_json(force=True)
#     to = data.get("to")
#     message = data.get("message")

#     print("/send endpoint hit")
#     print("Payload received:", {"to": to, "message": message})

#     payload = {
#         "messaging_product": "whatsapp",
#         "to": to,
#         "type": "text",
#         "text": {"body": message}
#     }

#     try:
#         response = requests.post(
#             f"https://graph.facebook.com/v18.0/{BUSINESS_PHONE_NUMBER_ID}/messages",
#             json=payload,
#             headers={
#                 "Authorization": f"Bearer {GRAPH_API_TOKEN}",
#                 "Content-Type": "application/json"
#             }
#         )
#         print("WhatsApp API response:", response.status_code, response.text)
#         return jsonify({"status": "sent", "response": response.json()})
#     except Exception as e:
#         print("Failed to send:", str(e))
#         return jsonify({"error": "Failed to send"}), 500


# @app.route("/health")
# def health():
#     return "OK", 200

