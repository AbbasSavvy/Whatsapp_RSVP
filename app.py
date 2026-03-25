import os
import json
import time
from flask import Flask, request
from dotenv import load_dotenv
from logger import get_logger
from whatsapp import send_message, send_button_message, send_invite_template
from sheets import save_rsvp, get_guests, update_guests_sheet, get_session, save_session, delete_session
from conversation import handle_message, RSVP_BUTTONS

load_dotenv()
log = get_logger("app")

app = Flask(__name__)


# ── Wedding Configuration ────────────────────────────────────────────────────
WEDDING_NAME = "Sarah & John's Wedding"
WEDDING_DATE = "June 14th, 2025"
# INVITE_IMAGE_URL = "https://raw.githubusercontent.com/AbbasSavvy/Whatsapp_RSVP/main/assets/RSVP_Generated.png"
INVITE_IMAGE_URL = None


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
    """
    AiSensy webhook payload format:
    {
        "topic": "message.sender.user",
        "data": {
            "message": {
                "type": "message",
                "phone_number": "919004942031",
                "sender": "USER",
                "message_type": "TEXT" | "QUICK_REPLY",
                "message_content": {
                    // For TEXT:
                    "text": "Yes"
                    // For QUICK_REPLY (button tap):
                    "text": "Yes, I'll be there!",
                    "callbackPayload": "{\"id\":\"...\"}"
                }
            }
        }
    }
    """
    data = request.get_json()

    try:
        log.debug(f"Webhook payload received: {data}")

        # Only process inbound user messages — filter by topic
        topic = data.get("topic", "")
        if topic != "message.sender.user":
            log.debug(f"Skipping non-user-message topic: {topic}")
            return "ok", 200

        # Navigate to the message object inside data.data.message
        aisensy_message = data.get("data", {}).get("message", {})
        if not aisensy_message:
            log.warning("message.sender.user event had no message object — skipping")
            return "ok", 200

        phone = str(aisensy_message.get("phone_number", ""))
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

        elif msg_type == "QUICK_REPLY":
            # Button taps arrive as QUICK_REPLY with the button label in text
            # Map button label to yes/no id for conversation.py
            text = message_content.get("text", "")
            text_lower = text.lower()
            if "yes" in text_lower:
                button_id = "yes"
            elif "no" in text_lower:
                button_id = "no"
            else:
                button_id = text_lower  # pass through for unknown buttons
            log.debug(f"QUICK_REPLY mapped | text='{text}' | button_id='{button_id}'")
            message = {
                "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {
                        "id": button_id,
                        "title": text
                    }
                }
            }

        elif msg_type == "BUTTON" or "button_reply" in message_content:
            # Fallback handler for any other button format
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
            send_message(phone, "Sorry, I can only process text replies. Please type Yes or No.")
            return "ok", 200

        # Load session from Sheets (survives redeploys)
        session = get_session(phone)
        response_text, session_data, response_type = handle_message(phone, message, session)

        step = session_data.get("step")
        log.info(f"Conversation state updated | phone={phone} | step={step}")

        # If RSVP is complete, save response and clean up session
        if step == "done":
            log.info(f"RSVP complete for {session_data.get('name')} ({phone}) — saving to Sheets")
            save_rsvp(session_data)
            update_guests_sheet(session_data.get("name"), phone, "Invited and Responded")
            delete_session(phone)
        else:
            # Persist session state to Sheets
            save_session(phone, session_data)

        # Send response
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
        phone = str(guest["phone"])
        max_guests = int(guest.get("max_guests", 1))
        whos_guest = guest.get("whos_guest", "")  # fixed: now read from request body

        success = send_invite_template(phone, name, WEDDING_NAME, WEDDING_DATE, INVITE_IMAGE_URL)

        if success:
            session_data = {
                "step": "awaiting_rsvp",
                "name": name,
                "phone": phone,
                "max_guests": max_guests,
                "whos_guest": whos_guest
            }
            save_session(phone, session_data)
            log.info(f"Invite sent | name={name} | phone={phone} | max_guests={max_guests}")
        else:
            log.error(f"Failed to send invite | name={name} | phone={phone}")

        results.append({"phone": phone, "name": name, "sent": success})

    log.info(f"Broadcast complete — {sum(r['sent'] for r in results)}/{len(guests)} sent successfully")
    return {"results": results}, 200


@app.route("/test", methods=["GET"])
def test():
    success = send_message("917021839581", "Hello from the wedding bot!")  # test number
    return {"sent": success}


@app.route("/test-sheets", methods=["GET"])
def test_sheets():
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

        if success:
            session_data = {
                "step": "awaiting_rsvp",
                "name": name,
                "phone": phone,
                "max_guests": max_guests,
                "whos_guest": whos_guest
            }
            save_session(phone, session_data)
            update_guests_sheet(name, phone, "Invited")
            log.info(f"Invite sent | name={name} | phone={phone} | max_guests={max_guests} | whos_guest={whos_guest}")
        else:
            update_guests_sheet(name, phone, "Could Not Connect")
            log.error(f"Failed to send invite | name={name} | phone={phone}")

        results.append({"phone": phone, "name": name, "sent": success})

        # Small delay to avoid hitting AiSensy rate limits on large broadcasts
        time.sleep(0.1)

    log.info(f"Broadcast complete - {sum(r['sent'] for r in results)}/{len(guests)} sent successfully")
    return {"results": results}, 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting Wedding RSVP Bot on port {port}")
    app.run(debug=True, port=port)
