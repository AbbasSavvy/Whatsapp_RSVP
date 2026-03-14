import os
import json
from flask import Flask, request
from dotenv import load_dotenv
from logger import get_logger
from whatsapp import send_message, send_button_message, send_invite_template
from sheets import save_rsvp, get_guests, update_guests_sheet
from conversation import handle_message, RSVP_BUTTONS

load_dotenv()
log = get_logger("app")

app = Flask(__name__)

sessions = {}


# ── Wedding Configuration ────────────────────────────────────────────────────
WEDDING_NAME = "Sarah & John's Wedding"
WEDDING_DATE = "June 14th, 2025"
INVITE_IMAGE_URL = "https://raw.githubusercontent.com/AbbasSavvy/Whatsapp_RSVP/main/assets/RSVP_Generated.png"
# INVITE_IMAGE_URL = None



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

    """
    AiSensy webhook payload format (message.sender.user topic):
    {
        "message": {
            "type": "message",
            "phone_number": "919004942031",
            "message_type": "TEXT",
            "message_content": {
                "text": "Yes"
                // OR for button replies:
                "button_reply": {"id": "yes", "title": "Yes, I'll be there!"}
            }
        }
    }
    """

    try:
        log.debug(f"Webhook payload received: {data}")

        if "message" not in data:
            log.debug("AiSensy webhook contained no message — skipping")
            return "ok", 200

        aisensy_message = data["message"]

        # Only process inbound user messages, skip delivery status updates
        if aisensy_message.get("sender") != "user" and aisensy_message.get("type") != "message":
            log.debug("AiSensy webhook is not a user message — skipping")
            return "ok", 200

        phone = aisensy_message.get("phone_number", "")
        msg_type = aisensy_message.get("message_type", "unknown")
        message_content = aisensy_message.get("message_content", {})

        log.info(f"Incoming message | phone={phone} | type={msg_type}")
        log.debug(f"Full message content: {message_content}")

        # Convert AiSensy payload to internal format expected by conversation.py
        if msg_type == "TEXT":
            message = {
                "type": "text",
                "text": {"body": message_content.get("text", "")}
            }
        elif msg_type == "BUTTON" or "button_reply" in message_content:
            button_reply = message_content.get("button_reply", {})
            message = {
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {
                        "id": button_reply.get("id", ""),
                        "title": button_reply.get("title", "")
                    }
                }
            }
        else:
            log.warning(f"Unhandled message type | phone={phone} | type={msg_type}")
            return "ok", 200

        response_text, session_data, response_type = handle_message(phone, message, sessions.get(phone))
        sessions[phone] = session_data

        step = session_data.get("step")
        log.info(f"Conversation state updated | phone={phone} | step={step}")

        # If RSVP is complete, save to Google Sheets and clear session
        if session_data.get("step") == "done":
            log.info(f"RSVP complete for {session_data.get('name')} ({phone}) — saving to Sheets")
            save_rsvp(session_data)
            update_guests_sheet(session_data.get("name"), phone, "Invited and Responded")
            if phone in sessions:
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
    """Send invites to a manually provided list of guests."""
    data = request.get_json()
    guests = data.get("guests", [])
    log.info(f"Starting invite broadcast for {len(guests)} guest(s)")

    results = []

    for guest in guests:
        name = guest["name"]
        phone = guest["phone"]
        max_guests = guest.get("max_guests", 1)

        success = send_invite_template(phone, name, WEDDING_NAME, WEDDING_DATE, INVITE_IMAGE_URL)
        sessions[phone] = {'step': "awaiting_rsvp", "name": name, "phone": phone, "max_guests": max_guests}
        results.append({"phone": phone, "name": name, "sent": success})

        if success:
            log.info(f"Invite sent | name={name} | phone={phone} | max_guests={max_guests}")
        else:
            log.error(f"Failed to send invite | name={name} | phone={phone}")

    log.info(f"Broadcast complete — {sum(r['sent'] for r in results)}/{len(guests)} sent successfully")
    return {"results": results}, 200


@app.route("/test", methods=["GET"])
def test():
    success = send_message("917021839581", "Hello from the wedding bot!")  # test number
    return {"sent": success}


@app.route("/test-sheets", methods=["GET"])
def test_sheets():
    from sheets import get_guests
    guests = get_guests()
    return {"guests_loaded": len(guests)}


@app.route("/send-all-invites", methods=["POST"])
def send_all_invites():
    """Send invites to all guests loaded from Google Sheets."""
    guests = get_guests()
    log.info(f"Sending invite to {len(guests)} guest(s) from Google Sheets.")
    results = []

    for guest in guests:
        name = guest["Name"]
        phone = str(guest["Phone"])
        max_guests = int(guest.get("Max Guests", 1))
        whos_guest = guest.get("Who's Guest", "")

        success = send_invite_template(phone, name, WEDDING_NAME, WEDDING_DATE, INVITE_IMAGE_URL)
        sessions[phone] = {'step': "awaiting_rsvp", "name": name, "phone": phone, "max_guests": max_guests, "whos_guest": whos_guest}

        if success:
            update_guests_sheet(name, phone, "Invited")
            log.info(f"Invite sent | name={name} | phone={phone} | max_guests={max_guests} | whos_guest={whos_guest}")
        else:
            update_guests_sheet(name, phone, "Could Not Connect")
            log.error(f"Failed to send invite | name={name} | phone={phone}")

        results.append({"phone": phone, "name": name, "sent": success})

    log.info(f"Broadcast complete - {sum(r['sent'] for r in results)}/{len(guests)} sent successfully")
    return {"results": results}, 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting Wedding RSVP Bot on port {port}")
    app.run(debug=True, port=port)
