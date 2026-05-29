import re
from io import BytesIO
from PIL import Image

try:
    from pyzbar.pyzbar import decode as qr_decode
    HAS_QR = True
except ImportError:
    HAS_QR = False

try:
    import fitz
except ModuleNotFoundError:
    import pymupdf as fitz


def read_qr_from_image(image_bytes: bytes) -> list:
    if not HAS_QR:
        return []
    try:
        img = Image.open(BytesIO(image_bytes))
        codes = qr_decode(img)
        return [c.data.decode("utf-8", errors="ignore") for c in codes]
    except Exception:
        return []


def read_qr_from_pdf(pdf_bytes: bytes) -> list:
    if not HAS_QR:
        return []
    import fitz
    results = []
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        codes = qr_decode(img)
        for c in codes:
            results.append(c.data.decode("utf-8", errors="ignore"))
    doc.close()
    return results


def extract_ticket_from_qr(qr_data: str) -> dict:
    info = {}
    patterns = {
        "flight": r"(flight|flight_number|flightno)[:\s]*([A-Z0-9]{3,10})",
        "ticket": r"(ticket|ticket_number|ticketno|tkt)[:\s]*(\d{6,15})",
        "name": r"(name|passenger|pax)[:\s]*([A-Za-z\s]{3,40})",
        "seat": r"(seat|seat_number)[:\s]*([A-Z0-9]{1,5})",
        "date": r"(date|flight_date)[:\s]*(\d{4}-\d{2}-\d{2})",
        "gate": r"(gate)[:\s]*([A-Z0-9]{1,5})",
    }
    for key, pat in patterns.items():
        m = re.search(pat, qr_data, re.IGNORECASE)
        if m:
            info[key] = m.group(2).strip()

    if not info:
        flight_match = re.search(r"\b[A-Z]{2}\s*\d{2,6}\b", qr_data)
        if flight_match:
            info["flight"] = flight_match.group()
        ticket_match = re.search(r"\b\d{6,15}\b", qr_data)
        if ticket_match:
            info["ticket"] = ticket_match.group()

    return info
