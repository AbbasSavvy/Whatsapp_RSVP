import os
import json
import time
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from logger import get_logger

log = get_logger("sheets")

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


def get_sheet():
    log.debug("Authenticating with Google Sheets API")
    creds = get_credentials()
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
    log.debug("Google Sheets connection established")
    return spreadsheet.worksheet("Responses")


def get_guests():
    try:
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
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
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        sheet = spreadsheet.worksheet("Guests")

        phones = sheet.col_values(2)  # Column B = Phone
        if str(phone) in phones:
            row = phones.index(str(phone)) + 1  # +1 since sheets are 1-indexed
            sheet.update_cell(row, 4, status)   # Col D = Status
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
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name,
            phone,
            "Yes" if session.get("attending") else "No",
            session.get("guests", 0),
            whos_guest,
        ]

        # Check if a partial entry already exists for this phone (from save_partial_rsvp)
        phones = sheet.col_values(3)  # Column C = Phone
        if str(phone) in phones:
            # Update the existing partial row in place
            row_index = phones.index(str(phone)) + 1
            sheet.update(f"A{row_index}:F{row_index}", [row_data])
            log.info(f"RSVP updated (was partial) | name={name} | phone={phone} | attending={session.get('attending')} | guests={session.get('guests', 0)}")
        else:
            # No partial entry — append fresh
            sheet.append_row(row_data)
            log.info(f"RSVP saved | name={name} | phone={phone} | attending={session.get('attending')} | guests={session.get('guests', 0)} | whos_guest={whos_guest}")

        return True

    except Exception as e:
        log.error(f"Failed to save RSVP | name={name} | phone={phone} | error={e}", exc_info=True)
        return False


# ── Session Store (replaces in-memory sessions dict) ─────────────────────────

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
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
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
    Retries up to 3 times with backoff to handle transient Sheets API errors
    under concurrent load (e.g. multiple guests replying simultaneously).
    """
    for attempt in range(retries):
        try:
            creds = get_credentials()
            client = gspread.authorize(creds)
            spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
            sheet = _get_sessions_sheet(spreadsheet)

            phones = sheet.col_values(1)  # Column A = Phone
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

            return  # Success — exit retry loop

        except Exception as e:
            if attempt < retries - 1:
                wait = 0.5 * (attempt + 1)  # 0.5s, 1.0s, 1.5s backoff
                log.warning(f"Session save failed, retrying in {wait}s | attempt={attempt + 1} | phone={phone} | error={e}")
                time.sleep(wait)
            else:
                log.error(f"Failed to save session after {retries} attempts | phone={phone} | error={e}", exc_info=True)


def delete_session(phone):
    """Remove a session row from the Sessions sheet when RSVP is complete."""
    try:
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        sheet = _get_sessions_sheet(spreadsheet)

        phones = sheet.col_values(1)  # Column A = Phone
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
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        sheet = spreadsheet.worksheet("Guests")
        phones = sheet.col_values(2)  # Column B = Phone
        if str(phone) in phones:
            row_index = phones.index(str(phone)) + 1
            row = sheet.row_values(row_index)
            name = row[0] if len(row) > 0 else None         # Column A = Name
            max_guests = int(row[2]) if len(row) > 2 and row[2] else 1  # Column C = Max Guests
            whos_guest = row[4] if len(row) > 4 else ""     # Column E = Who's Guest
            log.info(f"Guest auto-matched by phone | phone={phone} | name={name} | max_guests={max_guests}")
            return name, max_guests, whos_guest
        return None, 1, ""
    except Exception as e:
        log.error(f"Failed to lookup guest by phone | phone={phone} | error={e}", exc_info=True)
        return None, 1, ""


def has_existing_rsvp(phone):
    """Check if a phone number already has an RSVP in the Responses sheet."""
    try:
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        sheet = spreadsheet.worksheet("Responses")
        phones = sheet.col_values(3)  # Column C = Phone
        return str(phone) in phones
    except Exception as e:
        log.error(f"Failed to check existing RSVP | phone={phone} | error={e}", exc_info=True)
        return False