# WhatsApp RSVP Bot

A conversational WhatsApp bot for managing wedding RSVPs at scale. Guests receive a personalised invite via WhatsApp, tap a button to respond, and their RSVP is recorded automatically in Google Sheets — no manual follow-up required.

Built with Python/Flask, hosted on Railway, and powered by AiSensy as the WhatsApp Business API provider.

---

## Features

- **Broadcast invites** to your entire guest list from Google Sheets with a single API call
- **Conversational RSVP flow** — Yes/No buttons, dynamic guest count prompt, auto-confirmation for solo guests
- **Persistent sessions** stored in Google Sheets (survives server restarts and redeploys)
- **Partial RSVP saving** — captures attendance even if a guest never submits a guest count
- **Duplicate-safe** — deduplicates AiSensy webhook retries and skips already-RSVPed guests
- **Fallback handling** — sends button template for unrecognised replies
- **Rate-limit safe** — batches all Sheets writes after broadcast to avoid Google's 60 reads/min quota
- **IST timestamps** on all Responses sheet entries

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11 / Flask |
| Hosting | Railway (auto-deploy from GitHub) |
| WhatsApp API | AiSensy (BSP) |
| Data store | Google Sheets via gspread |
| Image hosting | Cloudinary |
| WSGI server | Gunicorn |

---

## Project Structure

```
.
├── app.py            # Flask routes, webhook handler, broadcast logic
├── conversation.py   # RSVP conversation state machine
├── whatsapp.py       # AiSensy API wrappers (send_message, send_button_message, send_invite_template)
├── sheets.py         # Google Sheets read/write — guests, responses, sessions
├── logger.py         # Logging setup (stdout, DEBUG level)
├── requirements.txt  # Python dependencies
└── .python-version   # Pins Python 3.11.9 for Railway
```

---

## Google Sheets Structure

### Guests sheet
| Column | Field | Notes |
|---|---|---|
| A | Name | Guest display name |
| B | Phone | Full international format, e.g. `919876543210` |
| C | Max Guests | Maximum guests this person can bring |
| D | Status | Updated to `Invited` or `Could Not Connect` after broadcast; `Invited and Responded` on completion |
| E | Who's Guest | Which family/side this guest belongs to |

### Responses sheet
| Column | Field |
|---|---|
| A | Timestamp (IST) |
| B | Name |
| C | Phone |
| D | Attending (Yes / No) |
| E | Number of Guests |
| F | Who's Guest |

### Sessions sheet
Auto-created on first run. Stores in-progress conversation state per guest. Rows are deleted when an RSVP is completed.

---

## Conversation Flow

```
Guest receives invite template
        │
        ▼
  [Yes, I'll be there!] ──────────────────────────────────────┐
        │                                                      │
        │  max_guests > 1                                      │  max_guests == 1
        ▼                                                      ▼
  "How many guests?"                               Auto-confirm, RSVP done ✓
        │
        ▼
  Guest replies with number
        │
        ▼
  Validate (1 ≤ n ≤ max_guests)
        │
        ▼
  Confirm + save to Sheets ✓

  [No, Can't make it.] ──▶ Record decline + save to Sheets ✓

  [Unrecognised reply] ──▶ Send rsvp_fallback_buttons template
```

---

## Environment Variables

Env Variables set in Railway dashboard (or a local `.env` file for development):

| Variable | Description |
|---|---|
| `VERIFY_TOKEN` | Webhook verification token (any secret string) |
| `GOOGLE_SHEET_ID` | Google Sheets spreadsheet ID |
| `GOOGLE_CREDENTIALS` | Service account credentials JSON (as a string) |
| `AISENSY_API_KEY` | AiSensy Campaign API key |
| `AISENSY_CAMPAIGN_NAME` | Name of the AiSensy API campaign |
| `AISENSY_PROJECT_API_KEY` | AiSensy Project API key (PRO plan) |
| `EVENT_NAME` | Displayed in invite and conversation messages |
| `EVENT_DATE` | Displayed in invite and conversation messages |
| `INVITE_IMAGE_URL` | Cloudinary URL for the invite image (header media) |

> **Note:** Wrap values containing single quotes in double quotes in `.env` files, e.g. `EVENT_NAME="Sarah & John's Wedding"`.

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| `GET` | `/webhook` | AiSensy webhook verification |
| `POST` | `/webhook` | Inbound message handler |
| `POST` | `/send-all-invites` | Trigger broadcast to all guests in Sheets |
| `GET` | `/pending-rsvps` | List guests who said Yes but never gave a count |
| `GET` | `/test` | Send a test message to a hardcoded number |
| `GET` | `/test-sheets` | Verify Sheets connection and guest count |

---

## Running Locally

```bash
# Install dependencies
pip install -r requirements.txt

# Add your credentials
cp .env.example .env
# Fill in GOOGLE_CREDENTIALS, AISENSY keys, etc.

# Place credentials.json in the project root (fallback if GOOGLE_CREDENTIALS not set)

# Start the server
python app.py

# Expose locally with ngrok (dev only)
ngrok http 5000
# Set the ngrok URL as your AiSensy webhook
```

---

## Key Design Decisions

**Why Google Sheets as a session store?**
Railway redeploys wipe in-memory state. Sheets gives us persistence without adding a database dependency, and doubles as the primary data view for non-technical event organisers.

**Why batch-write sessions after broadcast?**
With 400+ guests, reading and writing per guest would exhaust Google's 60 reads/minute quota. Sessions are written in one pass after all invites are sent, using cached phone lists read once upfront.

**Why AiSensy over Meta Cloud API directly?**
Meta's direct API had silent message delivery failures and a permission gate (`whatsapp_business_messaging` stuck at "Ready for Testing") that requires becoming an official Tech Provider. AiSensy handles the BSP layer and approval process.

**Why Utility category templates?**
Meta frequency-caps Marketing templates per user per day. Utility templates bypass this, making them the correct category for transactional RSVP flows.

**Why Cloudinary for images?**
GitHub raw URLs and images over 5MB are rejected as WhatsApp template header media. Cloudinary with `q_auto,f_jpg` transformations reliably passes Meta's media validation.

---

## License

Private project — not licensed for redistribution.