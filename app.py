import os
import json
import time
import threading
from flask import Flask, request
from dotenv import load_dotenv
from logger import get_logger
from whatsapp import send_message, send_button_message, send_invite_template
from sheets import (
    save_rsvp, save_partial_rsvp, get_guests, update_guests_sheet,
    get_session, save_session, delete_session,
    lookup_guest_by_phone, has_existing_rsvp,
    broadcast_batch_write, get_sheet
)
from conversation import handle_message, RSVP_BUTTONS

load_dotenv()
log = get_logger("app")

app = Flask(__name__)

# Deduplication cache to prevent AiSensy webhook retries from being processed twice
processed_webhooks = set()

# Guard to prevent duplicate broadcast triggers
broadcast_running = False


# ── Wedding Configuration ────────────────────────────────────────────────────

EVENT_NAME = os.getenv("EVENT_NAME", "Sarah & John's Wedding")
EVENT_DATE = os.getenv("EVENT_DATE", "June 14th, 2025")
INVITE_IMAGE_URL = os.getenv("INVITE_IMAGE_URL")


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

        # Deduplicate — AiSensy retries webhooks if no timely response
        webhook_id = data.get("id", "")
        if webhook_id and webhook_id in processed_webhooks:
            log.debug(f"Duplicate webhook ignored | id={webhook_id}")
            return "ok", 200
        if webhook_id:
            processed_webhooks.add(webhook_id)
        # Prevent unbounded memory growth on long-running instances
        if len(processed_webhooks) > 10000:
            processed_webhooks.clear()

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
            session = get_session(phone)
            if session and session.get("step") == "awaiting_count":
                max_guests = session.get("max_guests", 1)
                send_message(phone, f"Please reply with a *number* between 1 and {max_guests}.")
            else:
                send_message(phone, "Sorry, I can only process text replies. Please tap the Yes or No buttons.")
            return "ok", 200

        # Load session from Sheets (survives redeploys)
        session = get_session(phone)

        # If no session, check if they already RSVPed first
        if session is None:
            if has_existing_rsvp(phone):
                log.info(f"Message received from already-RSVPed guest | phone={phone}")
                send_message(phone,
                             "Your RSVP is already recorded. 😊 If you need to make a change, please contact us directly.")
                return "ok", 200

            # Not RSVPed yet — try to auto-match from Guests sheet
            matched_name, max_guests, whos_guest = lookup_guest_by_phone(phone)
            if matched_name:
                log.warning(f"No session found but guest matched by phone | phone={phone} | name={matched_name}")
                session = {
                    "step": "awaiting_rsvp",
                    "phone": phone,
                    "name": f"[AUTO] {matched_name}",
                    "max_guests": max_guests,
                    "whos_guest": whos_guest
                }
            else:
                log.warning(f"No session and phone not in Guests sheet | phone={phone}")
                session = {
                    "step": "awaiting_rsvp",
                    "phone": phone,
                    "name": f"[UNKNOWN] {phone}",
                    "max_guests": 1,
                    "whos_guest": ""
                }

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

            # Save partial RSVP if guest just confirmed attendance but count is still pending
            # This ensures we have a record even if the guest never follows up with a count
            if step == "awaiting_count":
                log.info(f"Guest confirmed attendance, saving partial RSVP | phone={phone}")
                save_partial_rsvp(session_data)

        # Send response
        if response_type == "button":
            log.debug(f"Sending button message to {phone}")
            send_button_message(phone, response_text, RSVP_BUTTONS)
        else:
            log.debug(f"Sending text message to {phone}")
            send_message(phone, response_text)

    except Exception as e:
        log.error(f"Failed to process webhook payload: {e}", exc_info=True)

    return "ok", 200


@app.route("/test", methods=["GET"])
def test():
    success = send_message("917021839581", "Hello from the wedding bot!")  # test number
    return {"sent": success}


@app.route("/test-sheets", methods=["GET"])
def test_sheets():
    guests = get_guests()
    return {"guests_loaded": len(guests)}


@app.route("/pending-rsvps", methods=["GET"])
def pending_rsvps():
    """Return all guests who confirmed attendance but never provided a guest count."""
    sheet = get_sheet()
    records = sheet.get_all_records()
    pending = [r for r in records if str(r.get("Number of Guests", "")).strip() == "Pending"]
    log.info(f"Pending RSVPs queried — {len(pending)} found")
    return {"pending_count": len(pending), "pending": pending}, 200


@app.route("/send-all-invites", methods=["POST"])
def send_all_invites():
    """
    Send invites to all guests from Google Sheets.

    Runs the broadcast in a background thread so the HTTP response returns
    immediately — avoiding the Gunicorn 30s worker timeout that kills the
    request mid-broadcast.

    All Sheets writes (sessions + status) are batched into a single API
    connection at the end of the broadcast, instead of per-guest calls that
    blow the Google Sheets quota.
    """
    global broadcast_running

    if broadcast_running:
        log.warning("Broadcast already in progress — rejecting duplicate request")
        return {"error": "Broadcast already in progress. Check Railway logs for progress."}, 429

    guests = get_guests()
    if not guests:
        log.error("No guests loaded from sheet — aborting broadcast")
        return {"error": "No guests found in sheet"}, 400

    broadcast_running = True
    log.info(f"Broadcast triggered for {len(guests)} guest(s) — starting background thread")

    def run_broadcast(guests):
        global broadcast_running
        try:
            log.info(f"Broadcast thread started | total={len(guests)}")
            guest_updates = []  # collected for a single batch Sheets write at the end

            for i, guest in enumerate(guests, start=1):
                name = guest["Name"]
                phone = str(guest["Phone"])
                max_guests = int(guest.get("Max Guests", 1))
                whos_guest = guest.get("Who's Guest", "")

                log.info(f"Sending invite {i}/{len(guests)} | name={name} | phone={phone}")
                success = send_invite_template(phone, name, EVENT_NAME, EVENT_DATE, INVITE_IMAGE_URL)

                if success:
                    guest_updates.append({
                        "phone": phone,
                        "name": name,
                        "step": "awaiting_rsvp",
                        "max_guests": max_guests,
                        "whos_guest": whos_guest,
                        "status": "Invited",
                    })
                else:
                    guest_updates.append({
                        "phone": phone,
                        "name": name,
                        "status": "Could Not Connect",
                    })
                    log.error(f"Failed to send invite | name={name} | phone={phone}")

                # Breathing room between AiSensy API calls to avoid rate limiting
                time.sleep(0.5)

            # All invites sent — now do a single batch write to Sheets
            sent = sum(1 for u in guest_updates if u["status"] == "Invited")
            failed = len(guest_updates) - sent
            log.info(f"Invites complete — sent={sent} failed={failed} — writing batch to Sheets")
            broadcast_batch_write(guest_updates)
            log.info("Broadcast fully complete including Sheets update")

        finally:
            # Always reset the flag, even if something crashes mid-broadcast
            broadcast_running = False
            log.info("Broadcast lock released")

    thread = threading.Thread(target=run_broadcast, args=(guests,), daemon=True)
    thread.start()

    return {
        "status": "broadcast started",
        "total_guests": len(guests),
        "message": "Check Railway logs for progress. Sheets will update when all invites are sent."
    }, 200


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    log.info(f"Starting Wedding RSVP Bot on port {port}")
    app.run(debug=True, port=port)