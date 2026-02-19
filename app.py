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

sessions = {}

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

        response_text, session_data, response_type = handle_message(phone, message, sessions.get(phone))
        sessions[phone] = session_data

        step = sessions.get("step")
        log.info(f"Conversation state updated | phone={phone} | step={step}")

        # If RSVP is complete, save to Google Sheets and clear session
        if step == "done":
            log.info(f"RSVP complete for {session_data.get('name')} ({phone}) — saving to Sheets")
            save_rsvp(session_data)
            del sessions[phone]

        # Use button or plain text depending on what the step needs
        if response_type == "button":
            log.debug(f"Sending button message to {phone}")
            send_button_message(phone, response_text, RSVP_BUTTONS)
        else:
            log.debug(f"Sending text message to {phone}")
            send_message(phone, response_text)

    except (KeyError, IndexError) as e:
        log.error(f"Failed to process webhook payload: {e}", exc_info=True)

    return "ok", 200

@app.route("/send-invites", methods=["POST"])
def send_invites():
    data = request.get_json()
    guests = data.get("guests", [])
    log.info(f"Starting invite broadcast for {len(guests)} guest(s)")

    results = []

    for guest in guests:
        name = guest["name"]
        phone = guest["phone"]
        body = (
            f"Hi {name}! 🎉 You're invited to *Sarah & John's Wedding* on *June 14th, 2025*.\n\n"
            f"We'd love to know if you can make it!"
        )

        success = send_button_message(phone, body, RSVP_BUTTONS)
        sessions[phone] = {'step': "awaiting_rsvp", "name": name, "phone": phone}
        results.append({"phone": phone, "name": name, "sent": success})

        if success:
            log.info(f"Invite sent | name={name} | phone={phone}")
        else:
            log.error(f"Failed to send invite | name={name} | phone={phone}")

    log.info(f"Broadcast complete — {sum(r['sent'] for r in results)}/{len(guests)} sent successfully")
    return {"results": results}, 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting Wedding RSVP Bot on port {port}")
    app.run(debug=True, port=port)
