#main.py  – WhatsApp ↔ Zulip bridge
from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

GRAPH_API_TOKEN     = os.environ["GRAPH_API_TOKEN"]      # WhatsApp Cloud API
WEBHOOK_VERIFY_TOKEN= os.environ["WEBHOOK_VERIFY_TOKEN"] # WhatsApp webhook verify
ZULIP_API_KEY       = os.environ["ZULIP_API_KEY"]
ZULIP_BOT_EMAIL     = os.environ["ZULIP_BOT_EMAIL"]
PORT                = int(os.getenv("PORT", 5000))       # Render sets this

ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
ZULIP_STREAM  = "rt-integration-test-channel"



def _do_send_whatsapp(to: str, msg: str):
    print("⬆️  Bridge→WA  to=%s msg=%r", to, msg)

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
    print("WA API response status=%s body=%s", resp.status_code, resp.text)
    return resp



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
    data = request.get_json(force=True) or {}
    to  = data.get("to")
    msg = data.get("message", "")
    if not to or not msg:
        return jsonify({"error": "to_and_message_required"}), 400

    resp = _do_send_whatsapp(to, msg)
    status = "sent" if resp.ok else "error"
    return jsonify({"status": status, "response": resp.json()}), (200 if resp.ok else 500)


# --------------------------------------------------------------------------- #
# 3. Zulip → WhatsApp                                                         #
# --------------------------------------------------------------------------- #
@app.post("/webhook/zulip")
def receive_zulip():
    payload = request.get_json(force=True)
    print("Raw Zulip payload: %s", payload)

    message = payload.get("message", {})
    topic   = message.get("subject", "")
    content = message.get("content", "")

    if topic.startswith("whatsapp:") and content:
        phone_number = topic.split("whatsapp:", 1)[1].strip()
        cleaned = (content
                   .replace("@**correspondence**", "")
                   .replace("@correspondence", "")
                   .strip())

        print("⬇️  Zulip→Bridge  to=%s msg=%r", phone_number, cleaned)
        resp = _do_send_whatsapp(phone_number, cleaned)
        status = "sent" if resp.ok else "error"
        return jsonify({"status": status, "response": resp.json()}), (200 if resp.ok else 500)

    print("Message ignored – not a WA relay")
    return jsonify({"status": "ignored"}), 200



@app.get("/health")
def health():
    return "OK", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False)