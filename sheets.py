import os
import json
import time
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials
from logger import get_logger

log = get_logger("sheets")

# Indian Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_credentials():
    """Load Google credentials from environment variable or fallback to file."""
    google_creds_json = os.getenv("GOOGLE_CREDENTIALS")
    if google_creds_json:
        log.debug("Loading Google credentials from environment variable")
        creds_dict = json.loads(google_creds_json)
        return Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    else:
        log.debug("Loading Google credentials from credentials.json file")
        return Credentials.from_service_account_file("credentials.json", scopes=SCOPES)


def _open_spreadsheet():
    """Authenticate and open the spreadsheet. Returns the spreadsheet object."""
    creds = get_credentials()
    client = gspread.authorize(creds)
    return client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))


def get_sheet():
    log.debug("Authenticating with Google Sheets API")
    spreadsheet = _open_spreadsheet()
    log.debug("Google Sheets connection established")
    return spreadsheet.worksheet("Responses")


def get_guests():
    try:
        spreadsheet = _open_spreadsheet()
        sheet = spreadsheet.worksheet("Guests")
        records = sheet.get_all_records()
        log.info(f"Loaded {len(records)} guests from sheet")
        return records
    except Exception as e:
        log.error(f"Failed to get guests from sheet: {e}", exc_info=True)
        return []


def update_guests_sheet(name, phone, status):
    """Update the Status column for a guest in the Guests sheet."""
    try:
        spreadsheet = _open_spreadsheet()
        sheet = spreadsheet.worksheet("Guests")
        phones = sheet.col_values(2)  # Column B = Phone
        if str(phone) in phones:
            row = phones.index(str(phone)) + 1
            sheet.update_cell(row, 4, status)  # Col D = Status
            log.info(f"Guest status updated | name={name} | phone={phone} | status={status}")
        else:
            log.warning(f"Phone not found in Guests sheet | name={name} | phone={phone}")
    except Exception as e:
        log.error(f"Failed to update status | name={name} | phone={phone} | status={status}", exc_info=True)


# ── RSVP Save / Partial Save ─────────────────────────────────────────────────

def save_partial_rsvp(session):
    """
    Save a partial RSVP entry when a guest confirms attendance (Yes)
    but hasn't provided their guest count yet. Stores 'Pending' as the count.
    This ensures we have a record even if the guest never follows up.
    """
    name = session.get("name", "Unknown")
    phone = session.get("phone", "")
    whos_guest = session.get("whos_guest", "")

    try:
        sheet = get_sheet()

        # Don't create a duplicate partial entry if one already exists
        phones = sheet.col_values(3)  # Column C = Phone
        if str(phone) in phones:
            log.debug(f"Partial RSVP entry already exists — skipping | phone={phone}")
            return

        row = [
            datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
            name,
            phone,
            "Yes",
            "Pending",  # Guest count not yet provided
            whos_guest,
        ]
        sheet.append_row(row)
        log.info(f"Partial RSVP saved | name={name} | phone={phone} | whos_guest={whos_guest}")

    except Exception as e:
        log.error(f"Failed to save partial RSVP | name={name} | phone={phone} | error={e}", exc_info=True)


def save_rsvp(session):
    """
    Save or update the final RSVP entry in the Responses sheet.
    If a partial entry exists (from save_partial_rsvp), it is updated in place.
    If no partial entry exists, a new row is appended.
    """
    name = session.get("name", "Unknown")
    phone = session.get("phone", "")
    whos_guest = session.get("whos_guest", "")

    try:
        sheet = get_sheet()

        # Add header row if sheet is empty
        if sheet.row_count == 0 or not sheet.row_values(1):
            log.info("Responses sheet is empty — adding header row")
            sheet.append_row(["Timestamp", "Name", "Phone", "Attending", "Number of Guests", "Who's Guest"])

        row_data = [
            datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S"),
            name,
            phone,
            "Yes" if session.get("attending") else "No",
            session.get("guests", 0),
            whos_guest,
        ]

        # Check if a partial entry already exists for this phone (from save_partial_rsvp)
        phones = sheet.col_values(3)  # Column C = Phone
        if str(phone) in phones:
            row_index = phones.index(str(phone)) + 1
            sheet.update(f"A{row_index}:F{row_index}", [row_data])
            log.info(f"RSVP updated (was partial) | name={name} | phone={phone} | attending={session.get('attending')} | guests={session.get('guests', 0)}")
        else:
            sheet.append_row(row_data)
            log.info(f"RSVP saved | name={name} | phone={phone} | attending={session.get('attending')} | guests={session.get('guests', 0)} | whos_guest={whos_guest}")

        return True

    except Exception as e:
        log.error(f"Failed to save RSVP | name={name} | phone={phone} | error={e}", exc_info=True)
        return False


# ── Session Store ─────────────────────────────────────────────────────────────

def _get_sessions_sheet(spreadsheet):
    """Get or create the Sessions worksheet."""
    try:
        return spreadsheet.worksheet("Sessions")
    except gspread.exceptions.WorksheetNotFound:
        log.info("Sessions sheet not found — creating it")
        sheet = spreadsheet.add_worksheet(title="Sessions", rows=1000, cols=8)
        sheet.append_row(["Phone", "Step", "Name", "MaxGuests", "WhosGuest", "Attending"])
        return sheet


def get_session(phone):
    """Load a session from the Sessions sheet by phone number. Returns dict or None."""
    try:
        spreadsheet = _open_spreadsheet()
        sheet = _get_sessions_sheet(spreadsheet)

        phones = sheet.col_values(1)  # Column A = Phone
        phone_str = str(phone)

        if phone_str not in phones:
            log.debug(f"No session found | phone={phone}")
            return None

        row_index = phones.index(phone_str) + 1
        row = sheet.row_values(row_index)

        session = {
            "phone":      row[0] if len(row) > 0 else phone_str,
            "step":       row[1] if len(row) > 1 else "awaiting_rsvp",
            "name":       row[2] if len(row) > 2 else "Unknown_Guest",
            "max_guests": int(row[3]) if len(row) > 3 and row[3] else 1,
            "whos_guest": row[4] if len(row) > 4 else "",
            "attending":  row[5].lower() == "true" if len(row) > 5 and row[5] else None,
        }
        log.debug(f"Session loaded | phone={phone} | step={session['step']}")
        return session

    except Exception as e:
        log.error(f"Failed to get session | phone={phone} | error={e}", exc_info=True)
        return None


def save_session(phone, session_data, retries=3):
    """
    Save or update a session row in the Sessions sheet.
    Retries up to 3 times with backoff to handle transient Sheets API errors.
    """
    for attempt in range(retries):
        try:
            spreadsheet = _open_spreadsheet()
            sheet = _get_sessions_sheet(spreadsheet)

            phones = sheet.col_values(1)
            phone_str = str(phone)

            row = [
                phone_str,
                session_data.get("step", ""),
                session_data.get("name", ""),
                str(session_data.get("max_guests", 1)),
                session_data.get("whos_guest", ""),
                str(session_data.get("attending", "")),
            ]

            if phone_str in phones:
                row_index = phones.index(phone_str) + 1
                sheet.update(f"A{row_index}:F{row_index}", [row])
                log.debug(f"Session updated | phone={phone} | step={session_data.get('step')}")
            else:
                sheet.append_row(row)
                log.debug(f"Session created | phone={phone} | step={session_data.get('step')}")

            return

        except Exception as e:
            if attempt < retries - 1:
                wait = 0.5 * (attempt + 1)
                log.warning(f"Session save failed, retrying in {wait}s | attempt={attempt + 1} | phone={phone} | error={e}")
                time.sleep(wait)
            else:
                log.error(f"Failed to save session after {retries} attempts | phone={phone} | error={e}", exc_info=True)


def delete_session(phone):
    """Remove a session row from the Sessions sheet when RSVP is complete."""
    try:
        spreadsheet = _open_spreadsheet()
        sheet = _get_sessions_sheet(spreadsheet)

        phones = sheet.col_values(1)
        phone_str = str(phone)

        if phone_str in phones:
            row_index = phones.index(phone_str) + 1
            sheet.delete_rows(row_index)
            log.info(f"Session deleted | phone={phone}")
        else:
            log.warning(f"Session not found for deletion | phone={phone}")

    except Exception as e:
        log.error(f"Failed to delete session | phone={phone} | error={e}", exc_info=True)


def lookup_guest_by_phone(phone):
    """Look up a guest name and max_guests from the Guests sheet by phone number."""
    try:
        spreadsheet = _open_spreadsheet()
        sheet = spreadsheet.worksheet("Guests")
        phones = sheet.col_values(2)  # Column B = Phone
        if str(phone) in phones:
            row_index = phones.index(str(phone)) + 1
            row = sheet.row_values(row_index)
            name = row[0] if len(row) > 0 else None
            max_guests = int(row[2]) if len(row) > 2 and row[2] else 1
            whos_guest = row[4] if len(row) > 4 else ""
            log.info(f"Guest auto-matched by phone | phone={phone} | name={name} | max_guests={max_guests}")
            return name, max_guests, whos_guest
        return None, 1, ""
    except Exception as e:
        log.error(f"Failed to lookup guest by phone | phone={phone} | error={e}", exc_info=True)
        return None, 1, ""


def has_existing_rsvp(phone):
    """
    Check if a phone number already has a completed RSVP in the Responses sheet.
    Note: this returns True for partial 'Pending' entries too, so it must only
    be called when session is None (i.e. the guest has no active conversation).
    Calling it unconditionally would block guests in awaiting_count from
    submitting their guest count.
    """
    try:
        spreadsheet = _open_spreadsheet()
        sheet = spreadsheet.worksheet("Responses")
        phones = sheet.col_values(3)  # Column C = Phone
        return str(phone) in phones
    except Exception as e:
        log.error(f"Failed to check existing RSVP | phone={phone} | error={e}", exc_info=True)
        return False


# ── Broadcast Batch Write ─────────────────────────────────────────────────────

def broadcast_batch_write(guest_updates):
    """
    Update Sessions sheet and Guests sheet status for all broadcast recipients
    in a single Sheets connection. Called once after all invites are sent.

    Uses cached phone lists read once upfront — avoids per-guest API calls
    that would blow Google's 60 reads/minute quota for 400 guests.

    Skips session writes for guests who already responded during the broadcast
    window (i.e. their phone is already in the Responses sheet). This prevents
    the batch write from overwriting or resurrecting sessions for guests who
    completed their RSVP before the batch ran.

    Also preserves "Invited and Responded" status in the Guests sheet —
    does not overwrite it back to "Invited" for guests who completed their
    RSVP during the broadcast window.

    guest_updates: list of dicts with keys:
        phone, name, status ("Invited" | "Could Not Connect")
        and for Invited: step, max_guests, whos_guest
    """
    if not guest_updates:
        return

    try:
        spreadsheet = _open_spreadsheet()
        sessions_sheet = _get_sessions_sheet(spreadsheet)
        guests_sheet = spreadsheet.worksheet("Guests")
        responses_sheet = spreadsheet.worksheet("Responses")

        # Read all phone/status columns once upfront — no per-guest reads
        existing_session_phones = sessions_sheet.col_values(1)  # Sessions col A
        guest_sheet_phones = guests_sheet.col_values(2)          # Guests col B
        guest_sheet_statuses = guests_sheet.col_values(4)        # Guests col D
        responded_phones = responses_sheet.col_values(3)         # Responses col C

        log.info(f"Batch write started | updates={len(guest_updates)}")

        for update in guest_updates:
            phone_str = str(update["phone"])
            status = update["status"]

            # ── Sessions sheet (only for successfully sent invites) ───────────
            if status == "Invited":
                if phone_str in responded_phones:
                    # Guest already responded during the broadcast window —
                    # their session was already handled by the webhook, skip
                    log.info(f"Guest already responded during broadcast — skipping session write | phone={phone_str}")
                else:
                    row = [
                        phone_str,
                        update.get("step", "awaiting_rsvp"),
                        update.get("name", ""),
                        str(update.get("max_guests", 1)),
                        update.get("whos_guest", ""),
                        "",  # attending — not yet known at invite time
                    ]
                    if phone_str in existing_session_phones:
                        row_index = existing_session_phones.index(phone_str) + 1
                        sessions_sheet.update(f"A{row_index}:F{row_index}", [row])
                        log.debug(f"Session updated (batch) | phone={phone_str}")
                    else:
                        sessions_sheet.append_row(row)
                        existing_session_phones.append(phone_str)  # keep local list in sync
                        log.debug(f"Session created (batch) | phone={phone_str}")

            # ── Guests sheet status ──────────────────────────────────────────
            if phone_str in guest_sheet_phones:
                row_index = guest_sheet_phones.index(phone_str) + 1
                # Don't overwrite if guest already responded during broadcast window
                current_status = guest_sheet_statuses[row_index - 1] if row_index - 1 < len(guest_sheet_statuses) else ""
                if current_status == "Invited and Responded":
                    log.info(f"Guest already responded — preserving status | phone={phone_str}")
                else:
                    guests_sheet.update_cell(row_index, 4, status)  # Col D = Status
                    log.info(f"Guest status updated (batch) | phone={phone_str} | status={status}")
            else:
                log.warning(f"Phone not found in Guests sheet (batch) | phone={phone_str}")

        log.info(f"Batch write complete | updates={len(guest_updates)}")

    except Exception as e:
        log.error(f"Batch write failed | error={e}", exc_info=True)