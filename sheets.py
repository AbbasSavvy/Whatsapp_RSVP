import os
import json
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
    """Update the Status Column for a guest in the Guests spreadsheet"""
    try:
        creds = get_credentials()
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        sheet = spreadsheet.worksheet("Guests")

        # Getting the correct row from this phone number:
        phones = sheet.col_values(2)  # Column B = Phone
        if str(phone) in phones:
            row = phones.index(str(phone)) + 1  # +1 since sheets are 1-indexed
            sheet.update_cell(row, 4, status)  # Col D = Status
            log.info(f"Guest status updated | name={name} | phone={phone} | status={status}")
        else:
            log.warning(f"Phone not found in Guests sheet | name={name} | phone={phone}")
    except Exception as e:
        log.error(f"Failed to update status | name={name} | phone={phone} | status={status}", exc_info=True)


def save_rsvp(session):
    name = session.get("name", "Unknown")
    phone = session.get("phone", "")
    whos_guest = session.get("whos_guest", "")

    try:
        sheet = get_sheet()
        # Add header row if the sheet is empty
        if sheet.row_count == 0 or not sheet.row_values(1):
            log.info("Sheet is empty — adding header row")
            sheet.append_row(["Timestamp", "Name", "Phone", "Attending", "Number of Guests", "Who's Guest"])

        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            name,
            phone,
            "Yes" if session.get("attending") else "No",
            session.get("guests", 0),
            whos_guest,
        ]

        sheet.append_row(row)
        log.info(f"RSVP saved | name={name} | phone={phone} | attending={session.get('attending')} | guests={session.get('guests', 0)} | whos_guest={whos_guest}")
        return True

    except Exception as e:
        log.error(f"Failed to save RSVP to Google Sheets | name={name} | phone={phone} | error={e}", exc_info=True)
        return False