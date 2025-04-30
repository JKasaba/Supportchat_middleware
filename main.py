from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/webhook/whatsapp", methods=["POST"])
def handle_webhook():
    data = request.get_json(force=True)
    print("📩 Received WhatsApp webhook:", data)
    return jsonify({"status": "received"}), 200

@app.route("/", methods=["GET"])
def index():
    return "Flask WhatsApp webhook is running!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
