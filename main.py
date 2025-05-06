# from flask import Flask, request, jsonify
# import os, re, json, requests, db

# app = Flask(__name__)

# # ─── Required env vars ────────────────────────────────────────────────────────
# GRAPH_API_TOKEN      = os.environ["GRAPH_API_TOKEN"]       # WhatsApp Cloud API
# WEBHOOK_VERIFY_TOKEN = os.environ["WEBHOOK_VERIFY_TOKEN"]  # Meta webhook verify
# ZULIP_API_KEY        = os.environ["ZULIP_API_KEY"]
# ZULIP_BOT_EMAIL      = os.environ["ZULIP_BOT_EMAIL"]       # outgoing‑webhook bot
# ZULIP_BOT_DM_EMAIL   = os.getenv("ZULIP_BOT_DM_EMAIL", "rt-test-bot@chat-test.filmlight.ltd.uk")
# PORT                 = int(os.getenv("PORT", 5000))

# # ─── Zulip API endpoint ───────────────────────────────────────────────────────
# ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"

# # ─── Engineer lookup (env var driven) ─────────────────────────────────────────
# # Set ENGINEER_EMAIL_JAMESK="james.kasaba@example.com"  etc.
# ENGINEER_EMAIL_MAP = {
#     k[len("ENGINEER_EMAIL_"):].lower(): v
#     for k, v in os.environ.items()
#     if k.startswith("ENGINEER_EMAIL_")
# }
# # fallback for your test account
# ENGINEER_EMAIL_MAP.setdefault("jamesk", "jamesk@filmlight.ltd.uk")

# # ─── Regexes ──────────────────────────────────────────────────────────────────
# INIT_RE  = re.compile(r"RT\s*#?(\d+)\s*\(([^)]+)\)", re.I)      # first WA message
# PHONE_RE = re.compile(r"^\s*(\+?\d{10,15})\s*:\s*", re.ASCII)   # optional DM prefix

# # ─── Helper: send WA text -----------------------------------------------------
# def _do_send_whatsapp(to: str, msg: str):
#     payload = {
#         "messaging_product": "whatsapp",
#         "to": to.lstrip("+"),
#         "type": "text",
#         "text": {"body": msg}
#     }
#     return requests.post(
#         "https://graph.facebook.com/v18.0/599049466632787/messages",
#         json=payload,
#         headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
#         timeout=10
#     )

# # ─── Helper: DM engineer (+bot) ----------------------------------------------
# def _send_zulip_dm(to_email: str, content: str):
#     # Zulip accepts comma‑sep string for private "to"
#     to_field = f"{to_email},{ZULIP_BOT_DM_EMAIL}"
#     data = {"type": "private", "to": to_field, "content": content}
#     return requests.post(
#         ZULIP_API_URL, data=data,
#         auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY), timeout=10
#     )

# # ─── Helper: register mapping -------------------------------------------------
# def _register_chat(phone, ticket_id, engineer_email):
#     db.state["phone_to_chat"][phone] = {"ticket": ticket_id, "engineer": engineer_email}
#     db.state["engineer_to_set"].setdefault(engineer_email, set()).add(phone)
#     db.save()

# # ───────────────────────── 1.  WhatsApp → bridge ─────────────────────────────
# @app.get("/webhook")
# def verify_webhook():
#     if (request.args.get("hub.mode") == "subscribe"
#         and request.args.get("hub.verify_token") == WEBHOOK_VERIFY_TOKEN):
#         return request.args.get("hub.challenge"), 200
#     return "Forbidden", 403


# @app.post("/webhook")
# def receive_whatsapp():
#     body = request.get_json(force=True)
#     msg  = (body.get("entry",[{}])[0].get("changes",[{}])[0]
#                   .get("value",{}).get("messages",[{}])[0])
#     if not msg or msg.get("type") != "text":
#         return "", 200

#     phone = msg["from"]                          # e.g. "14155551234"
#     text  = msg["text"]["body"].strip()

#     chat = db.state["phone_to_chat"].get(phone)
#     if not chat:                                 # first handshake
#         m = INIT_RE.match(text)
#         if not m:
#             # Ignore unknown chat until proper handshake comes in
#             return "", 200
#         ticket_id, eng_nick = m.groups()
#         eng_email = ENGINEER_EMAIL_MAP.get(eng_nick.lower())
#         if not eng_email:
#             # Unknown engineer, can't map
#             return "", 200

#         _register_chat(phone, int(ticket_id), eng_email)
#         _send_zulip_dm(
#             eng_email,
#             f"🆕 WhatsApp chat started for *RT #{ticket_id}*.\n"
#             f"(Customer is {phone}). Reply here to chat."
#         )
#         chat = db.state["phone_to_chat"][phone]

#     # Forward every WA text to the engineer DM
#     dm_body = f"📲 *RT #{chat['ticket']}* | **{phone}**:\n\n{text}"
#     _send_zulip_dm(chat["engineer"], dm_body)

#     # Mark read / echo (optional)
#     phone_id = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
#     requests.post(f"https://graph.facebook.com/v18.0/{phone_id}/messages",
#                   headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
#                   json={"messaging_product":"whatsapp",
#                         "status":"read", "message_id": msg["id"]})
#     return "", 200

# # ───────────────────────── 2.  Zulip → bridge ────────────────────────────────
# @app.post("/webhook/zulip")
# def receive_zulip():
#     payload = request.get_json(force=True)
#     message = payload.get("message", {})
#     if message.get("type") != "private":
#         return jsonify({"status": "ignored"}), 200

#     sender_email = message.get("sender_email")
#     if sender_email == ZULIP_BOT_EMAIL:          # ignore bot's own messages
#         return jsonify({"status": "ignored_bot"}), 200

#     content = message.get("content", "").strip()

#     # 1) Explicit phone prefix
#     m = PHONE_RE.match(content)
#     if m:
#         phone = m.group(1).lstrip("+")
#         content = PHONE_RE.sub("", content).strip()
#     else:
#         # 2) Infer if engineer has exactly one active phone
#         phones = db.state["engineer_to_set"].get(sender_email, set())
#         if len(phones) == 1:
#             phone = next(iter(phones))
#         else:
#             return jsonify({"error": "prefix_required"}), 200

#     chat = db.state["phone_to_chat"].get(phone)
#     if not chat or chat["engineer"] != sender_email:
#         return jsonify({"error": "no_mapping"}), 200

#     resp = _do_send_whatsapp(phone, content)
#     return jsonify({"status": "sent" if resp.ok else "error",
#                     "response": resp.json()}), (200 if resp.ok else 500)

# # ───────────────────────── Health check ──────────────────────────────────────
# @app.get("/health")
# def health(): return "OK", 200

# # ───────────────────────── Runner ────────────────────────────────────────────
# if __name__ == "__main__":
#     print("Bridge starting, listening on", PORT)
#     app.run(host="0.0.0.0", port=PORT)
# main.py  – WhatsApp ↔ Zulip bridge (two‑slot DM model)

from flask import Flask, request, jsonify
import os, re, requests, db, json, uuid

app = Flask(__name__)

# ─── Required bot / admin env vars ────────────────────────────────────────────
ZULIP_BOT_EMAIL       = os.environ["ZULIP_BOT_EMAIL"]          # support‑chat
ZULIP_API_KEY         = os.environ["ZULIP_API_KEY"]
ZULIP_BOT_DM_EMAIL    = os.environ["ZULIP_BOT_DM_EMAIL"]       # correspondence
ZULIP_EXTRA_BOT_EMAIL = os.environ["ZULIP_EXTRA_BOT_EMAIL"]    # support‑secondary
GRAPH_API_TOKEN       = os.environ["GRAPH_API_TOKEN"]
WEBHOOK_VERIFY_TOKEN  = os.environ["WEBHOOK_VERIFY_TOKEN"]
PORT                  = int(os.getenv("PORT", 5000))

ZULIP_API_URL = "https://chat-test.filmlight.ltd.uk/api/v1/messages"
MAX_CHATS     = 2                       # slot0 and slot1 only

# ─── Engineer ↔ email map (env‑driven) ───────────────────────────────────────
ENGINEER_EMAIL_MAP = {
    k[len("ENGINEER_EMAIL_"):].lower(): v
    for k, v in os.environ.items()
    if k.startswith("ENGINEER_EMAIL_")
}

# fallback test account
ENGINEER_EMAIL_MAP.setdefault("jamesk", "jamesk@filmlight.ltd.uk")

# ─── Regex helpers ───────────────────────────────────────────────────────────
INIT_RE  = re.compile(r"RT\s*#?(\d+)\s*\(([^)]+)\)", re.I)     # first WA text

# ─── WhatsApp sender ---------------------------------------------------------
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

# ─── Zulip DM sender ---------------------------------------------------------
def _send_zulip_dm(recipients: list[str], content: str):
    to_field = ",".join(recipients)           # "user1@example.com,user2@…"
    return requests.post(
        ZULIP_API_URL,
        data={"type": "private", "to": to_field, "content": content},
        auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY),
        timeout=10
    )

# ─── recipient helpers -------------------------------------------------------
def _recip_list(chat: dict) -> list[str]:
    base = [chat["engineer"], ZULIP_BOT_DM_EMAIL]
    if chat["slot"] == 1:
        base.append(ZULIP_EXTRA_BOT_EMAIL)
    return base

# ─── chat registration -------------------------------------------------------
def _register_chat(phone: str, ticket_id: int, eng_email: str):
    active = db.state["engineer_to_set"].get(eng_email, set())

    if len(active) >= MAX_CHATS:
        _do_send_whatsapp(phone, "All agents busy, please try again later.")
        raise RuntimeError("engineer_busy")

    slot = 0 if not active else 1            # slot0 first, slot1 second
    chat = {
        "ticket": ticket_id,
        "engineer": eng_email,
        "slot": slot
    }
    db.state["phone_to_chat"][phone] = chat
    active.add(phone)
    db.state["engineer_to_set"][eng_email] = active
    db.save()
    return chat

def _end_chat(phone: str, chat: dict):
    eng = chat["engineer"]
    db.state["phone_to_chat"].pop(phone, None)
    db.state["engineer_to_set"].get(eng, set()).discard(phone)
    db.save()
    _do_send_whatsapp(phone, "Chat closed by engineer. Thank you!")
    _send_zulip_dm(_recip_list(chat), f"🔚 Chat with **{phone}** closed.")

# ─── 1. WhatsApp webhook ------------------------------------------------------
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

    phone = msg["from"]
    text  = msg["text"]["body"].strip()

    chat = db.state["phone_to_chat"].get(phone)
    if not chat:
        m = INIT_RE.match(text)
        if not m:
            return "", 200          # wait for proper handshake
        ticket_id, eng_nick = m.groups()
        eng_email = ENGINEER_EMAIL_MAP.get(eng_nick.lower())
        if not eng_email:
            _do_send_whatsapp(phone, "Engineer unknown. Please try later.")
            return "", 200

        try:
            chat = _register_chat(phone, int(ticket_id), eng_email)
        except RuntimeError:
            return "", 200

        _send_zulip_dm(
            _recip_list(chat),
            f"🆕 WhatsApp chat for *RT #{ticket_id}* (**{phone}**).\n"
            "Send `!end` to close this chat."
        )

    # forward message
    dm_body = f"📲 *RT #{chat['ticket']}* | **{phone}**:\n\n{text}"
    _send_zulip_dm(_recip_list(chat), dm_body)

    # mark read
    phone_id = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
    requests.post(f"https://graph.facebook.com/v18.0/{phone_id}/messages",
                  headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
                  json={"messaging_product":"whatsapp",
                        "status":"read", "message_id": msg["id"]})
    return "", 200

# ─── 2. Zulip webhook ---------------------------------------------------------
@app.post("/webhook/zulip")
def receive_zulip():
    payload = request.get_json(force=True)
    msg     = payload.get("message", {})
    if msg.get("type") != "private":
        return jsonify({"status":"ignored"}), 200

    sender  = msg.get("sender_email")
    if sender == ZULIP_BOT_EMAIL:
        return jsonify({"status":"ignored_bot"}), 200

    phones = db.state["engineer_to_set"].get(sender, set())
    if not phones:
        return jsonify({"status":"no_active"}), 200

    # figure out which DM tab (slot) this message belongs to
    recips = [p["email"] for p in msg["display_recipient"]]
    slot = 1 if ZULIP_EXTRA_BOT_EMAIL in recips else 0
    phone = next((p for p in phones if db.state["phone_to_chat"][p]["slot"] == slot), None)
    if not phone:
        return jsonify({"error":"no_slot_match"}), 200

    chat = db.state["phone_to_chat"][phone]
    content = msg["content"].strip()

    if content.lower() == "!end":
        _end_chat(phone, chat)
        return jsonify({"status":"ended"}), 200

    resp = _do_send_whatsapp(phone, content)
    return jsonify({"status":"sent" if resp.ok else "error",
                    "response":resp.json()}), (200 if resp.ok else 500)

# ─── Health -------------------------------------------------------------------
@app.get("/health")
def health(): return "OK", 200

# ─── main ---------------------------------------------------------------------
if __name__ == "__main__":
    print("Bridge starting on port", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
