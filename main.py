from flask import Flask, request, jsonify
import os, re, requests, db, json, uuid
import textwrap
import re
import mimetypes


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
CLOSED_REPLY = "Chat closed, please contact support to start a new chat."
# ─── Engineer ↔ email map (env‑driven) ───────────────────────────────────────
ENGINEER_EMAIL_MAP = {
    k[len("ENGINEER_EMAIL_"):].lower(): v
    for k, v in os.environ.items()
    if k.startswith("ENGINEER_EMAIL_")
}

# fallback test account
#ENGINEER_EMAIL_MAP.setdefault("jamesk", "jamesk@filmlight.ltd.uk")

# ─── Regex helpers ───────────────────────────────────────────────────────────
INIT_RE  = re.compile(r"RT\s*#?(\d+)\s*\(([^)]+)\)", re.I)     # first WA text



def _log_line(ticket_id: int, line: str):
    db.state["transcripts"].setdefault(str(ticket_id), []).append(line)



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

def _push_transcript(ticket_id: int):
    lines = db.state["transcripts"].get(str(ticket_id), [])
    if not lines:
        return

    lines_text = "\n\n".join(lines)
    body = (
        "Chat transcript imported by WA-Zulip bridge.\n\n"
        + "-"*60 + "\n"
        + lines_text + "\n"
        + "-"*60
    )

    resp = requests.post(
        f"{os.environ['RT_BASE_URL'].rstrip('/')}/ticket/{ticket_id}/comment",
        headers={
            "Authorization": f"token {os.environ['RT_TOKEN']}",
            "Content-Type": "text/plain",     
                 },
        data = body.encode("utf-8)")
    )
    if resp.status_code != 201:
        print("⚠️  RT comment failed:", resp.status_code, resp.text)
        return

    # on success, drop transcript
    db.state["transcripts"].pop(str(ticket_id), None)


def _end_chat(phone: str, chat: dict):
    ticket_id = chat["ticket"]
    eng = chat["engineer"]

    # tell customer + engineer
    _do_send_whatsapp(phone, "Chat closed by engineer. Thank you!")
    _send_zulip_dm(_recip_list(chat), f"✌️ Chat with **{phone}** closed.")

    # post transcript to RT
    try:
        _push_transcript(ticket_id)
        print("Pushing Transcript to RT")
    except Exception as e:
        print("⚠️  Could not push transcript to RT:", e)

    # clean up state
    db.state["phone_to_chat"].pop(phone, None)
    db.state["engineer_to_set"].get(eng, set()).discard(phone)
    db.save()


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
    # if not msg or msg.get("type") != "text":
    #     return "", 200
    
    if not msg:
        return "", 200

    msg_type = msg.get("type")
    phone = msg["from"]

    if msg_type == "text":
        text = msg["text"]["body"].strip()
    elif msg_type == "image":
        media_id = msg["image"]["id"]
        caption = msg["image"].get("caption", "")

        # Step 1: Get media URL
        media_resp = requests.get(
            f"https://graph.facebook.com/v18.0/{media_id}",
            headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"}
        )
        media_url = media_resp.json().get("url")

        # Step 2: Download image
        image_resp = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
            stream=True,
            timeout=10
        )

        # Save to temp file
        fname = f"/tmp/{uuid.uuid4()}.jpg"
        with open(fname, "wb") as f:
            for chunk in image_resp.iter_content(chunk_size=8192):
                f.write(chunk)

    #
    #
    #

    elif msg_type == "document":
        media_id = msg["document"]["id"]
        filename = msg["document"]["filename"]
        caption = msg["document"].get("caption", "")

        # Step 1: Get media URL
        media_resp = requests.get(
            f"https://graph.facebook.com/v18.0/{media_id}",
            headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"}
        )
        media_url = media_resp.json().get("url")

        # Step 2: Download document
        doc_resp = requests.get(
            media_url,
            headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
            stream=True,
            timeout=10
        )

        # Save to temp file
        fname = f"/tmp/{uuid.uuid4()}_{filename}"
        with open(fname, "wb") as f:
            for chunk in doc_resp.iter_content(chunk_size=8192):
                f.write(chunk)


        #
        #
        #

    else:
        return "", 200


    chat = db.state["phone_to_chat"].get(phone)
    if not chat:
        m = INIT_RE.match(text)
        if not m:
            _do_send_whatsapp(phone, CLOSED_REPLY)
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
            f"WhatsApp chat for *RT #{ticket_id}* (**{phone}**).\n"
            "Send `!end` to close this chat."
        )

    # forward message
    
    if msg_type == "text":
        dm_body = text
        _log_line(chat["ticket"], f"Customer to ENG: {text}")
        _send_zulip_dm(_recip_list(chat), dm_body)

    elif msg_type == "image":
        # Upload image to Zulip
        zulip_upload = requests.post(
            "https://chat-test.filmlight.ltd.uk/api/v1/user_uploads",
            auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY),
            files={"file": open(fname, "rb")}
        )
        upload_uri = zulip_upload.json().get("uri", "")
        dm_body = f"[Download Image]({upload_uri})"
        _log_line(chat["ticket"], f"Customer sent image: {caption} <{upload_uri}>")
        _send_zulip_dm(_recip_list(chat), dm_body)

    elif msg_type == "document":
        zulip_upload = requests.post(
            "https://chat-test.filmlight.ltd.uk/api/v1/user_uploads",
            auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY),
            files={"file": open(fname, "rb")}
        )
        upload_uri = zulip_upload.json().get("uri", "")
        dm_body = f"[{filename}]({upload_uri})"
        _log_line(chat["ticket"], f"Customer sent file: {caption} <{upload_uri}>")
        _send_zulip_dm(_recip_list(chat), dm_body)

    # _log_line(chat["ticket"], f"Customer to ENG: {text}")

    # _send_zulip_dm(_recip_list(chat), dm_body)

    # mark read
    phone_id = body["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
    requests.post(f"https://graph.facebook.com/v18.0/{phone_id}/messages",
                  headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
                  json={"messaging_product":"whatsapp",
                        "status":"read", "message_id": msg["id"]})
    return "", 200

# ─── 2. Zulip webhook ---------------------------------------------------------
@app.post("/webhook/zulip")
def receive_zulip():#
    payload = request.get_json(force=True)
    msg     = payload.get("message", {})

    print("Incoming Zulip message:", json.dumps(msg, indent=2)) 

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

    # Check if Zulip message includes an uploaded file
    ZULIP_UPLOAD_RE = re.compile(r"\[.*?\]\((/user_uploads/.*?)\)")

    match = ZULIP_UPLOAD_RE.search(msg.get("content", ""))
    if match:
        relative_url = match.group(1)
        zulip_file_url = f"https://chat-test.filmlight.ltd.uk{relative_url}"
        file_name = os.path.basename(relative_url).split('?')[0]

        # Download the image
        image_resp = requests.get(
            zulip_file_url,
            auth=(ZULIP_BOT_EMAIL, ZULIP_API_KEY),
            stream=True,
            timeout=10
        )

        if not image_resp.ok:
            return jsonify({"status": "zulip_download_failed"}), 500

        # Save to temp file
        fname = f"/tmp/{uuid.uuid4()}_{file_name}"
        with open(fname, "wb") as f:
            for chunk in image_resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Upload to WhatsApp
        mime_type = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        # mime_type = mimetypes.guess_type(fname)[0]
        # if mime_type not in ("image/jpeg", "image/png", "image/webp"):
        #     return jsonify({"status": "unsupported_mime", "mime": mime_type}), 400
        if mime_type == "application/octet-stream":
            mime_type = "text/plain"
            # Rename the file extension so WhatsApp treats it as .txt
            new_fname = fname + ".txt"
            os.rename(fname, new_fname)
            fname = new_fname
            file_name = os.path.basename(fname)

        with open(fname, "rb") as f:
            media_upload = requests.post(
                "https://graph.facebook.com/v18.0/599049466632787/media",
                headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
                files={"file": (os.path.basename(fname), f, mime_type)},
                data={"messaging_product": "whatsapp", "type": mime_type}
            )

        if not media_upload.ok and "Param file must be a file with one of the following types" in media_upload.text:
            print(f"Unsupported MIME type '{mime_type}', retrying as text/plain")
            mime_type = "text/plain"
            if not fname.endswith(".txt"):
                new_fname = fname + ".txt"
                os.rename(fname, new_fname)
                fname = new_fname
                file_name = os.path.basename(fname)

            with open(fname, "rb") as f:
                media_upload = requests.post(
                    "https://graph.facebook.com/v18.0/599049466632787/media",
                    headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"},
                    files={"file": (file_name, f, mime_type)},
                    data={"messaging_product": "whatsapp", "type": mime_type}
                )

        os.remove(fname)

        if not media_upload.ok:
            return jsonify({"status": "media_upload_failed", "details": media_upload.text}), 500
        


        media_id = media_upload.json().get("id")

        if mime_type.startswith("image/"):
            wa_payload = {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "image",
                "image": {
                    "id": media_id,
                    "caption": msg.get("content", "")
                }
            }
        else:
            wa_payload = {
                "messaging_product": "whatsapp",
                "to": phone,
                "type": "document",
                "document": {
                    "id": media_id,
                    "caption": msg.get("content", ""),
                    "filename": file_name
                }
            }

        resp = requests.post(
            "https://graph.facebook.com/v18.0/599049466632787/messages",
            json=wa_payload,
            headers={"Authorization": f"Bearer {GRAPH_API_TOKEN}"}
        )

        _log_line(chat["ticket"], f"ENG sent file: {file_name} (as {mime_type})")   

        return jsonify({"status":"sent image/document"}), 200   
    
    if content.lower() == "!end":
        _end_chat(phone, chat)
        return jsonify({"status":"ended"}), 200
    
    _log_line(chat["ticket"], f"ENG to Customer: {content}")

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

