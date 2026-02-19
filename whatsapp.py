import os
import requests
from logger import get_logger

log = get_logger("whatsapp")

def _get_headers():
    return {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_ACCESS_TOKEN')}",
        "Content-Type": "application/json",
    }

def _get_url():
    phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    return f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"

def send_message(to, text):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        response = requests.post(_get_url(), headers=_get_headers(), json=payload, timeout=10)
        response.raise_for_status()
        log.info(f"Text message sent | to {to} | status: {response.status_code}")
        return True
    except requests.RequestException as e:
        log.error(f"Failed to send text message | to={to} | error={e}", exc_info=True)
        return False

def send_button_message(to, body, buttons):
    """
    Send an interactive button message via Meta Cloud API.

    `buttons` should be a list of dicts like:
        [{"id": "yes", "title": "✅ Yes, I'll be there!"},
         {"id": "no",  "title": "❌ Sorry, I can't make it"}]

    Meta allows a maximum of 3 buttons per message.
    Each button title must be 20 characters or fewer.

    """

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}}
                    for btn in buttons[:3]
                ]
            },
        },
    }

    log.debug(f"Sending button message | to={to} | buttons={[b['id'] for b in buttons]}")

    try:
        response = requests.post(_get_url(), headers=_get_headers(), json=payload, timeout=10)
        response.raise_for_status()
        log.info(f"Button message sent | to={to} | status={response.status_code}")
        return True

    except requests.RequestException as e:
        log.error(f"Failed to send button message | to={to} | error={e}")
        log.error(f"Meta response: {e.response.text}")
        return False
    