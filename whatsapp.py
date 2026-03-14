import os
import requests
from logger import get_logger

log = get_logger("whatsapp")

# ── AiSensy Campaign API (outbound invites) ───────────────────────────────────
AISENSY_CAMPAIGN_URL = "https://backend.aisensy.com/campaign/t1/api/v2"

# ── AiSensy Project API (outbound replies) ────────────────────────────────────
AISENSY_PROJECT_ID = "69b5284a41f33f0dae7190b1"
AISENSY_MESSAGE_URL = f"https://apis.aisensy.com/project-apis/v1/project/{AISENSY_PROJECT_ID}/messages"

def _get_aisensy_headers():
    return {
        "X-AiSensy-Project-API-Pwd": os.getenv("AISENSY_PROJECT_API_KEY"),
        "Content-Type": "application/json",
    }


def send_message(to, text):
    """Send a plain text message via AiSensy Project API."""
    payload = {
        "to": to,
        "type": "text",
        "recipient_type": "individual",
        "text": {"body": text},
    }

    try:
        response = requests.post(AISENSY_MESSAGE_URL, headers=_get_aisensy_headers(), json=payload, timeout=10)
        response.raise_for_status()
        log.info(f"Text message sent | to={to} | status={response.status_code}")
        return True
    except requests.RequestException as e:
        log.error(f"Failed to send text message | to={to} | error={e}", exc_info=True)
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"AiSensy response: {e.response.text}")
        return False


def send_button_message(to, body, buttons):
    """
    Send the rsvp_fallback_buttons template via AiSensy Project API.

    Note: The `body` and `buttons` parameters are kept for interface compatibility
    but AiSensy uses the pre-approved rsvp_fallback_buttons template directly.
    """
    payload = {
        "to": to,
        "type": "template",
        "template": {
            "language": {
                "policy": "deterministic",
                "code": "en"
            },
            "name": "rsvp_fallback_buttons",
            "components": []
        }
    }

    log.debug(f"Sending fallback button template via AiSensy | to={to}")

    try:
        response = requests.post(AISENSY_MESSAGE_URL, headers=_get_aisensy_headers(), json=payload, timeout=10)
        response.raise_for_status()
        log.info(f"Fallback button template sent | to={to} | status={response.status_code}")
        return True
    except requests.RequestException as e:
        log.error(f"Failed to send fallback button template | to={to} | error={e}")
        if hasattr(e, 'response') and e.response is not None:
            log.error(f"AiSensy response: {e.response.text}")
        return False


def send_invite_template(to, guest_name, event_name, event_date, image_url=None):
    """
    Send the approved template via AiSensy Campaign API.

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