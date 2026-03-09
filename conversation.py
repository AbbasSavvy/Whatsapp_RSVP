"""
Conversation flow handler.

Steps:
  awaiting_rsvp  → Guest taps Yes/No button (or types)
  awaiting_count → Guest replies with number of guests (if Yes)
  done           → RSVP complete

Button reply IDs:
  "yes" → attending
  "no"  → not attending
"""

from logger import get_logger

log = get_logger("conversation")

# Buttons:
RSVP_BUTTONS = [
    {"id": "yes", "title": "Yes, I'll be there!"},
    {"id": "no", "title": "No, Can't make it."},
]


def extract_input(message):
    """
    Extract the user's input from a Meta webhook message object.
    Returns (input_type, value) where input_type is "button" or "text".
    """

    if message.get("type") == "interactive":
        button_id = message["interactive"]["button_reply"]["id"]
        log.debug(f"Button tap detected | button_id: {button_id}")
        return "button", button_id

    text = message.get("text", {}).get("body", "").strip()
    log.debug(f"Text input detected | value='{text}'")
    return "text", text

def handle_message(phone, message, session):
    """

    Process an incoming message based on the current conversation step.
    Returns (response_text, updated_session, response_type)
    where response_type is "button" or "text" so app.py knows which sender to use.

    """

    input_type, value = extract_input(message)
    value_lower = value.lower()

    # ── New conversation ─────────────────────────────────────────────────────

    if session is None:
        log.info(f"New conversation started | phone: {phone}")
        session = {"step": "awaiting_rsvp", "phone": {phone}, "name": "Unknown_Guest"}
        body = (
            "Hi! 👋 You've reached the RSVP bot for *Sarah & John's Wedding* on *June 14th, 2025*.\n\n"
            "Will you be able to join us?"
        )
        return body, session, "button"

    step = session.get("step")
    log.debug(f"Handling message | phone={phone} | step={step} | input_type={input_type} | value='{value}'")

    # ── Step 1: Awaiting RSVP ───────────────────────────────────────────────

    if step == "awaiting_rsvp":
        is_yes = value_lower in ("yes", "y") or (input_type == "button" and value_lower == "yes")
        is_no = value_lower in ("no", "n") or (input_type == "button" and value_lower == "no")

        if is_yes:
            log.info(f"Guest confirmed attendance | phone={phone} | name={session.get('name')}")
            session["attending"] = True
            session["step"] = "awaiting_count"
            max_guests = session.get("max_guests", 1)

            if max_guests == 1:
                session["guests"] = 1
                session["step"] = "done"
                name = session.get("name", "Guest")
                log.info(f"Single guest auto-confirmed | phone={phone} | name={name}")

                return (
                    f"Wonderful! We're so excited to celebrate with you, {name}! 🥂\n\n"
                    "Your RSVP is confirmed! We can't wait to see you on June 14th. 💍\n\n"
                    "_If anything changes, please contact Sarah or John directly._",
                    session,
                    "text",
                )

            return (
                f"Wonderful! We're so excited to celebrate with you! 🥂\n\n"
                f"How many guests will be joining you? Please reply with a number between *1* and *{max_guests}*.",
                session,
                "text",
            )


        elif is_no:
            log.info(f"Guest declined attendance | phone={phone} | name={session.get('name')}")
            session["attending"] = False
            session["guests"] = 0
            session["step"] = "done"
            name = session.get("name", "Guest")
            return (
                f"Thank you for letting us know, {name}. You'll be missed! 💐\n\n"
                "We hope to celebrate with you another time.",
                session,
                "text",
            )

        else:
            log.warning(f"Unrecognised RSVP reply | phone={phone} | value='{value}'")
            return (
                "Please use the buttons below to let us know if you'll be attending! 👇",
                session,
                "button",
            )

 # ── Step 2: Awaiting guest count ────────────────────────────────────────
    elif step == "awaiting_count":

        max_guests = session.get("max_guests", 1)

        try:
            guest_count = int(value.strip())
            if guest_count < 1 or guest_count > max_guests:
                log.warning(f"Guest count out of range | phone={phone} | value={value} | max={max_guests}")
                return (
                    f"Please enter a number between *1* and *{max_guests}*.",
                    session,
                    "text",
                )

        except ValueError:
            log.warning(f"Invalid guest count input | phone={phone} | value='{value}'")
            return (
                f"Please reply with a *number* between 1 and {max_guests} (e.g. *2*).",
                session,
                "text",
            )

        session["guests"] = guest_count
        session["step"] = "done"
        name = session.get("name", "Guest")
        log.info(f"Guest count recorded | phone={phone} | name={name} | count={guest_count}")

        return (
            f"Perfect! We've noted *{guest_count} guest(s)* for {name}. 🎊\n\n"
            "Your RSVP is confirmed! We can't wait to see you on June 14th. 💍\n\n"
            "_If anything changes, please contact Sarah or John directly._",
            session,
            "text",
        )

        
 # ── Already done ─────────────────────────────────────────────────────────
    elif step == "done":
        log.info(f"Message received after RSVP completion | phone={phone}")
        return (
            "Your RSVP is already recorded. 😊 If you need to make a change, please contact Sarah or John directly.",
            session,
            "text",
        )

    log.error(f"Unknown conversation step | phone={phone} | step={step}")
    return "Something went wrong. Please try again.", session, "text"