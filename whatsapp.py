import os
import requests
from logger import get_logger

log = get_logger("whatsapp")

# ── AiSensy Campaign API (outbound invites) ───────────────────────────────────
AISENSY_CAMPAIGN_URL = "https://backend.aisensy.com/campaign/t1/api/v2"

# ── Meta Cloud API ────────────────────────────────────────────────────────────
def _get_meta_headers():
    return {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_ACCESS_TOKEN')}",
        "Content-Type": "application/json",
    }

def _get_meta_url():
    phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    return f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"


def send_message(to, text):
    """Send a plain text message via Meta Cloud API."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    }

    try:
        response = requests.post(_get_meta_url(), headers=_get_meta_headers(), json=payload, timeout=10)
        response.raise_for_status()
        log.info(f"Text message sent | to={to} | status={response.status_code}")
        return True
    except requests.RequestException as e:
        log.error(f"Failed to send text message | to={to} | error={e}", exc_info=True)
        return False


def send_button_message(to, body, buttons):
    """
    Send an interactive button message via Meta Cloud API.

    `buttons` should be a list of dicts like:
        [{"id": "yes", "title": "Yes, I'll be there!"},
         {"id": "no",  "title": "No, Can't make it."}]

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
        response = requests.post(_get_meta_url(), headers=_get_meta_headers(), json=payload, timeout=10)
        response.raise_for_status()
        log.info(f"Button message sent | to={to} | status={response.status_code}")
        return True

    except requests.RequestException as e:
        log.error(f"Failed to send button message | to={to} | error={e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"Meta response: {e.response.text}")
        return False


def send_invite_template(to, guest_name, event_name, event_date, image_url=None):
    """
    Send the approved template via AiSensy Campaign API.
    Used when USE_AISENSY=true in environment.

    Parameters:
        to         : recipient phone number (e.g. "919004942031")
        guest_name : fills {{1}} in the template body
        event_name : fills {{2}} in the template body
        event_date : fills {{3}} in the template body
        image_url  : optional public URL for the image header
    """
    payload = {
        "apiKey": os.getenv("AISENSY_API_KEY"),
        "campaignName": os.getenv("AISENSY_CAMPAIGN_NAME", "rsvp_invite_campaign"),  # TODO: update with actual campaign name once created
        "destination": to,
        "userName": guest_name,
        "source": "rsvp_bot",
        "templateParams": [guest_name, event_name, event_date],
    }

    if image_url:
        payload["media"] = {
            "url": image_url,
            "filename": "invite.jpg"
        }

    log.debug(f"Sending AiSensy invite | to={to} | guest={guest_name} | event={event_name}")

    try:
        response = requests.post(
            AISENSY_CAMPAIGN_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        log.info(f"AiSensy invite sent | to={to} | status={response.status_code}")
        log.info(f"AiSensy response: {response.json()}")
        return True

    except requests.RequestException as e:
        log.error(f"Failed to send AiSensy invite | to={to} | error={e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"AiSensy response: {e.response.text}")
        return False


def send_invite_template_meta(to, guest_name, event_name, event_date, image_url=None):
    """
    Send the approved 'rsvp_template_new' template via Meta Cloud API.
    Used when USE_AISENSY=false in environment.

    Parameters:
        to         : recipient phone number (e.g. "919004942031")
        guest_name : fills {{guest_name}} in the template body
        event_name : fills {{event_name}} in the template body
        event_date : fills {{event_date}} in the template body
        image_url  : optional public URL for the image header
    """
    if image_url:
        header_component = {
            "type": "header",
            "parameters": [{"type": "image", "image": {"link": image_url}}]
        }
    else:
        header_component = {
            "type": "header",
            "parameters": [{"type": "text", "text": event_name}]
        }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": "rsvp_template_new",
            "language": {"code": "en"},
            "components": [
                header_component,
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "parameter_name": "guest_name", "text": guest_name},
                        {"type": "text", "parameter_name": "event_name", "text": event_name},
                        {"type": "text", "parameter_name": "event_date", "text": event_date},
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [{"type": "payload", "payload": "yes"}]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [{"type": "payload", "payload": "no"}]
                }
            ],
        }
    }

    log.debug(f"Sending Meta invite template | to={to} | guest={guest_name} | event={event_name}")

    try:
        response = requests.post(_get_meta_url(), headers=_get_meta_headers(), json=payload, timeout=10)
        response.raise_for_status()
        log.info(f"Meta invite template sent | to={to} | status={response.status_code}")
        log.info(f"Meta response: {response.json()}")
        return True

    except requests.RequestException as e:
        log.error(f"Failed to send Meta invite template | to={to} | error={e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"Meta response: {e.response.text}")
        return False