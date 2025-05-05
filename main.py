# #main.py  – WhatsApp ↔ Zulip bridge
# from flask import Flask, request, jsonify
# import os, requests

# app = Flask(__name__)

# GRAPH_API_TOKEN     = os.environ["GRAPH_API_TOKEN"]      # WhatsApp Cloud API
# WEBHOOK_VERIFY_TOKEN= os.environ["WEBHOOK_VERIFY_TOKEN"] # WhatsApp webhook verify
# ZULIP_API_KEY       = os.environ["ZULIP_API_KEY"]
# ZULIP_BOT_EMAIL     = os.environ["ZULIP_BOT_EMAIL"]
# PORT                = int(os.getenv("PORT", 5000))       # Render sets this

# ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
# ZULIP_STREAM  = "rt-integration-test-channel"



# def _do_send_whatsapp(to: str, msg: str):
#     print("⬆️  Bridge→WA  to=%s msg=%r", to, msg)

#     payload = {
#         "messaging_product": "whatsapp",
#         "to": to,
#         "type": "text",
#         "text": { "body": msg }
#     }
#     resp = requests.post(
#         "https://graph.facebook.com/v18.0/599049466632787/messages",
#         json = payload,
#         headers = {
#             "Authorization": f"Bearer {GRAPH_API_TOKEN}",
#             "Content-Type": "application/json"
#         },
#         timeout = 10
#     )
#     print("WA API response status=%s body=%s", resp.status_code, resp.text)
#     return resp



# # -----------------------------------------------------------------------------#
# # 1.  WhatsApp webhook  (GET for verification, POST for messages)
# # -----------------------------------------------------------------------------#
# @app.get("/webhook")
# def verify_webhook():
#     mode, token = request.args.get("hub.mode"), request.args.get("hub.verify_token")
#     challenge   = request.args.get("hub.challenge")
#     if mode == "subscribe" and token == WEBHOOK_VERIFY_TOKEN:
#         print("✅  WhatsApp webhook verified")
#         return challenge, 200
#     return "Forbidden", 403


# @app.post("/webhook")
# def receive_whatsapp():
#     body = request.get_json(force=True)
#     print("Incoming WhatsApp payload:", body)

#     message = body.get("entry", [{}])[0].get("changes", [{}])[0]\
#                   .get("value", {}).get("messages", [{}])[0]

#     if message and message.get("type") == "text":
#         phone_id  = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
#         wa_from   = message["from"]
#         wa_text   = message["text"]["body"]
#         wa_name   = (body["entry"][0]["changes"][0]["value"]
#                          .get("contacts", [{}])[0].get("profile", {}).get("name", "Unknown"))

#         # 1‑a) Forward to Zulip --------------------------------------------------
#         zulip_msg = f"📲 Message from *{wa_name}* ({wa_from}):\n\n{wa_text}"
#         z = requests.post(
#             ZULIP_API_URL,
#             data = {
#                 "type": "stream",
#                 "to":   ZULIP_STREAM,
#                 "subject": f"whatsapp:{wa_from}",
#                 "content": zulip_msg
#             },
#             auth = (ZULIP_BOT_EMAIL, ZULIP_API_KEY),
#             timeout = 10
#         )
#         print("Zulip →", z.status_code, z.text)

#         # 1‑b) Echo (optional) + mark as read -----------------------------------
#         graph_base = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
#         headers    = {"Authorization": f"Bearer {GRAPH_API_TOKEN}"}

#         echo_resp = requests.post(graph_base, headers=headers, json={
#             "messaging_product": "whatsapp",
#             "to": wa_from,
#             "text": { "body": f"Echo: {wa_text}" },
#             "context": { "message_id": message["id"] }
#         })
#         read_resp = requests.post(graph_base, headers=headers, json={
#             "messaging_product": "whatsapp",
#             "status": "read",
#             "message_id": message["id"]
#         })
#         print("Echo →", echo_resp.status_code, echo_resp.text)
#         print("Read →", read_resp.status_code, read_resp.text)

#     return "", 200


# # -----------------------------------------------------------------------------#
# # 2.  Outbound /send endpoint  (used by /webhook/zulip)                         #
# # -----------------------------------------------------------------------------#
# @app.post("/send")
# def send_whatsapp():
#     data = request.get_json(force=True) or {}
#     to  = data.get("to")
#     msg = data.get("message", "")
#     if not to or not msg:
#         return jsonify({"error": "to_and_message_required"}), 400

#     resp = _do_send_whatsapp(to, msg)
#     status = "sent" if resp.ok else "error"
#     return jsonify({"status": status, "response": resp.json()}), (200 if resp.ok else 500)


# # --------------------------------------------------------------------------- #
# # 3. Zulip → WhatsApp                                                         #
# # --------------------------------------------------------------------------- #
# @app.post("/webhook/zulip")
# def receive_zulip():
#     payload = request.get_json(force=True)
#     print("Raw Zulip payload: %s", payload)

#     message = payload.get("message", {})
#     topic   = message.get("subject", "")
#     content = message.get("content", "")

#     if topic.startswith("whatsapp:") and content:
#         phone_number = topic.split("whatsapp:", 1)[1].strip()
#         cleaned = (content
#                    .replace("@**correspondence**", "")
#                    .replace("@correspondence", "")
#                    .strip())

#         print("⬇️  Zulip→Bridge  to=%s msg=%r", phone_number, cleaned)
#         resp = _do_send_whatsapp(phone_number, cleaned)
#         status = "sent" if resp.ok else "error"
#         return jsonify({"status": status, "response": resp.json()}), (200 if resp.ok else 500)

#     print("Message ignored – not a WA relay")
#     return jsonify({"status": "ignored"}), 200



# @app.get("/health")
# def health():
#     return "OK", 200


# if __name__ == "__main__":
#     app.run(host="0.0.0.0", port=PORT, debug=False)

from flask import Flask, request, jsonify
import os, re, json, requests, db

app = Flask(__name__)

# ─── Required env vars ────────────────────────────────────────────────────────
GRAPH_API_TOKEN      = os.environ["GRAPH_API_TOKEN"]       # WhatsApp Cloud API
WEBHOOK_VERIFY_TOKEN = os.environ["WEBHOOK_VERIFY_TOKEN"]  # Meta webhook verify
ZULIP_API_KEY        = os.environ["ZULIP_API_KEY"]
ZULIP_BOT_EMAIL      = os.environ["ZULIP_BOT_EMAIL"]       # outgoing‑webhook bot
ZULIP_BOT_DM_EMAIL   = os.getenv("ZULIP_BOT_DM_EMAIL", ZULIP_BOT_EMAIL)
PORT                 = int(os.getenv("PORT", 5000))

# ─── Zulip API endpoint ───────────────────────────────────────────────────────
ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"

# ─── Engineer lookup (env var driven) ─────────────────────────────────────────
# Set ENGINEER_EMAIL_JAMESK="james.kasaba@example.com"  etc.
ENGINEER_EMAIL_MAP = {
    k[len("ENGINEER_EMAIL_"):].lower(): v
    for k, v in os.environ.items()
    if k.startswith("ENGINEER_EMAIL_")
}
# fallback for your test account
ENGINEER_EMAIL_MAP.setdefault("jamesk", "jamesk@filmlight.ltd.uk")

# ─── Regexes ──────────────────────────────────────────────────────────────────
INIT_RE  = re.compile(r"RT\s*#?(\d+)\s*\(([^)]+)\)", re.I)      # first WA message
PHONE_RE = re.compile(r"^\s*(\+?\d{10,15})\s*:\s*", re.ASCII)   # optional DM prefix

# ─── Helper: send WA text -----------------------------------------------------
def _do_send_whatsapp(to: str, msg: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to.lstrip("+"),
        "type": "text",
        "text": {"body": msg}
    }
    return requests.post(
        "https://graph.facebook.com/v18.0/599049466632787/messages",
        json=payload,
        headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
        timeout=10
    )

# ─── Helper: DM engineer (+bot) ----------------------------------------------
def _send_zulip_dm(to_email: str, content: str):
    # Zulip accepts comma‑sep string for private "to"
    to_field = f"{to_email},{ZULIP_BOT_DM_EMAIL}"
    data = {"type": "private", "to": to_field, "content": content}
    return requests.post(
        ZULIP_API_URL, data=data,
        auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY), timeout=10
    )

# ─── Helper: register mapping -------------------------------------------------
def _register_chat(phone, ticket_id, engineer_email):
    db.state["phone_to_chat"][phone] = {"ticket": ticket_id, "engineer": engineer_email}
    db.state["engineer_to_set"].setdefault(engineer_email, set()).add(phone)
    db.save()

# ───────────────────────── 1.  WhatsApp → bridge ─────────────────────────────
@app.get("/webhook")
def verify_webhook():
    if (request.args.get("hub.mode") == "subscribe"
        and request.args.get("hub.verify_token") == WEBHOOK_VERIFY_TOKEN):
        return request.args.get("hub.challenge"), 200
    return "Forbidden", 403


@app.post("/webhook")
def receive_whatsapp():
    body = request.get_json(force=True)
    msg  = (body.get("entry",[{}])[0].get("changes",[{}])[0]
                  .get("value",{}).get("messages",[{}])[0])
    if not msg or msg.get("type") != "text":
        return "", 200

    phone = msg["from"]                          # e.g. "14155551234"
    text  = msg["text"]["body"].strip()

    chat = db.state["phone_to_chat"].get(phone)
    if not chat:                                 # first handshake
        m = INIT_RE.match(text)
        if not m:
            # Ignore unknown chat until proper handshake comes in
            return "", 200
        ticket_id, eng_nick = m.groups()
        eng_email = ENGINEER_EMAIL_MAP.get(eng_nick.lower())
        if not eng_email:
            # Unknown engineer, can't map
            return "", 200

        _register_chat(phone, int(ticket_id), eng_email)
        _send_zulip_dm(
            eng_email,
            f"🆕 WhatsApp chat started for *RT #{ticket_id}*.\n"
            f"(Customer is {phone}). Reply here to chat."
        )
        chat = db.state["phone_to_chat"][phone]

    # Forward every WA text to the engineer DM
    dm_body = f"📲 *RT #{chat['ticket']}* | **{phone}**:\n\n{text}"
    _send_zulip_dm(chat["engineer"], dm_body)

    # Mark read / echo (optional)
    phone_id = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
    requests.post(f"https://graph.facebook.com/v18.0/{phone_id}/messages",
                  headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
                  json={"messaging_product":"whatsapp",
                        "status":"read", "message_id": msg["id"]})
    return "", 200

# ───────────────────────── 2.  Zulip → bridge ────────────────────────────────
@app.post("/webhook/zulip")
def receive_zulip():
    payload = request.get_json(force=True)
    message = payload.get("message", {})
    if message.get("type") != "private":
        return jsonify({"status": "ignored"}), 200

    sender_email = message.get("sender_email")
    if sender_email == ZULIP_BOT_EMAIL:          # ignore bot's own messages
        return jsonify({"status": "ignored_bot"}), 200

    content = message.get("content", "").strip()

    # 1) Explicit phone prefix
    m = PHONE_RE.match(content)
    if m:
        phone = m.group(1).lstrip("+")
        content = PHONE_RE.sub("", content).strip()
    else:
        # 2) Infer if engineer has exactly one active phone
        phones = db.state["engineer_to_set"].get(sender_email, set())
        if len(phones) == 1:
            phone = next(iter(phones))
        else:
            return jsonify({"error": "prefix_required"}), 200

    chat = db.state["phone_to_chat"].get(phone)
    if not chat or chat["engineer"] != sender_email:
        return jsonify({"error": "no_mapping"}), 200

    resp = _do_send_whatsapp(phone, content)
    return jsonify({"status": "sent" if resp.ok else "error",
                    "response": resp.json()}), (200 if resp.ok else 500)

# ───────────────────────── Health check ──────────────────────────────────────
@app.get("/health")
def health(): return "OK", 200

# ───────────────────────── Runner ────────────────────────────────────────────
if __name__ == "__main__":
    print("Bridge starting, listening on", PORT)
    app.run(host="0.0.0.0", port=PORT)
