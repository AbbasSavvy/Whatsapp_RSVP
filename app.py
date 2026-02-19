import os
import json
from flask import Flask, request
from dotenv import load_dotenv
from logger import get_logger
from whatsapp import send_message, send_button_message
from sheets import save_rsvp
from conversation import handle_message, RSVP_BUTTONS

load_dotenv()
log = get_logger("app")

app = Flask(__name__)

session = {}

@app.route('/webhook', methods=['GET'])
def verify_webhook():
    mode = request.args.get('hub.mode')
    token = request.args.get('hub.verify_token')
    challenge = request.args.get('hub.challenge')

    if mode == "subscribe" and token == os.getenv("VERIFY_TOKEN"):
        log.info("Webhook verified successfully")
        return challenge, 200

    log.warning("Webhook verification failed - token mismatch, or wrong mode.")
    return "Forbidden", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()

    """ Data from Meta JSON will be of the following format:
        {
      "entry": [{
        "changes": [{
          "value": {
            "messages": [{
              "from": "911234567890",
              "type": "text",
              "text": { "body": "Yes" }
            }]
          }
        }]
      }]
    }
    """

    try:
        entry = data['entry'][0]
        changes = entry['changes'][0]
        value = changes['value']

        if "messages" not in value:
            log.debug("Webhook payload contained no messages — skipping")
            return "ok", 200

        message = value["messages"][0]
        phone = message["from"]
        msg_type = message.get("type", "unknown")

        log.info(f"Incoming message | phone={phone} | type={msg_type}")
        log.debug(f"Full message payload: {message}")

