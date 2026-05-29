import os
import json
from pathlib import Path

try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    HAS_GSHEETS = True
except ImportError:
    HAS_GSHEETS = False

SHEET_NAME = "Pilgrims Data"
CRED_FILE = Path("downloads") / "google-credentials.json"


def is_available() -> bool:
    return HAS_GSHEETS and CRED_FILE.exists()


def export_to_sheets(pilgrims: list, tickets: dict) -> str:
    if not is_available():
        return "❌ Google Sheets requires:\n1. pip install gspread oauth2client\n2. google-credentials.json in downloads/"

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(
        str(CRED_FILE), scope
    )
    client = gspread.authorize(creds)

    try:
        sheet = client.open(SHEET_NAME).sheet1
    except gspread.SpreadsheetNotFound:
        sheet = client.create(SHEET_NAME).sheet1
        sheet.append_row(["Name", "Flight", "Ticket", "Seat", "Airline", "Passport", "Date", "Gate"])

    flight = tickets.get("flight_number", "")
    tkt = tickets.get("ticket_number", "")
    seat = tickets.get("seat", "")
    airline = tickets.get("airline", "")
    passport = tickets.get("passport", "")
    date = tickets.get("date", "")
    gate = tickets.get("gate", "")

    for p in pilgrims:
        sheet.append_row([
            p.get("name", ""), flight, tkt, seat, airline, passport, date, gate
        ])

    url = f"https://docs.google.com/spreadsheets/d/{sheet.spreadsheet.id}"
    return f"✅ Exported to Google Sheets\n{url}"
