import os
import logging
import tempfile
from pathlib import Path
from io import BytesIO

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram import InputFile

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DATA_DIR = Path("downloads")
DATA_DIR.mkdir(exist_ok=True)

from ocr import extract_text_from_pdf, extract_text_from_image
from extractor import extract_data
from qreader import read_qr_from_image, read_qr_from_pdf, extract_ticket_from_qr, HAS_QR
from db import init_db, save_extraction, get_history, get_stats, get_pilgrims_by_flight, get_pilgrims_by_airline
from lang import t, label, START_MSG, DIV
from sheets import export_to_sheets

init_db()

user_data_store = {}
ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_MSG)


async def process_file(
    update: Update, context: ContextTypes.DEFAULT_TYPE, msg,
    file_bytes: bytes, file_name: str = "file"
) -> None:
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        await msg.edit_text(t("unsupported"))
        return

    try:
        text = ""
        qr_data = []

        if ext == ".pdf":
            text = extract_text_from_pdf(file_bytes)
            if HAS_QR:
                qr_data = read_qr_from_pdf(file_bytes)
        else:
            text = extract_text_from_image(file_bytes)
            if HAS_QR:
                qr_data = read_qr_from_image(file_bytes)

    except Exception as e:
        logger.exception("Error processing file")
        await msg.edit_text(t("error", str(e)))
        return

    data = extract_data(text)

    if not data["pilgrims"] and not data["tickets"]:
        await msg.edit_text(t("no_text"))
        return

    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    user_data_store[user_id] = data

    save_extraction(
        user_id=user_id,
        username=username,
        file_name=file_name,
        file_type=ext,
        pilgrims=data["pilgrims"],
        tickets=data["tickets"],
        raw_text=data["raw_text"],
    )

    pilgrims = data.get("pilgrims", [])
    tickets = data.get("tickets", {})
    raw = data.get("raw_text", "")

    lines = []
    if pilgrims:
        lines.append("👥 *Pilgrims*")
        for i, p in enumerate(pilgrims, 1):
            lines.append(f"  {i}. {p['name']}")
        lines.append(DIV)

    if tickets:
        lines.append("🎫 *Ticket Details*")
        eng_labels = {
            "flight_number": "Flight", "ticket_number": "Ticket", "seat": "Seat",
            "date": "Date", "gate": "Gate", "airline": "Airline", "passport": "Passport",
            "booking": "Booking", "class": "Class", "destination": "To",
            "origin": "From", "route": "Route", "departure_time": "Departure Time",
            "flight_date": "Flight Date", "hid": "HID",
        }
        for k, v in tickets.items():
            lbl = eng_labels.get(k, k.replace("_", " ").title())
            lines.append(f"  • {lbl}: `{v}`")
        lines.append(DIV)

    if qr_data:
        lines.append("📱 *QR Data*")
        for q in qr_data[:3]:
            lines.append(f"  `{q[:100]}`")
        lines.append(DIV)

    lines.append("📝 *Raw Text*")
    lines.append(f"`{raw[:300]}`")
    if len(raw) > 300:
        lines.append("  ...")

    await msg.edit_text("\n".join(lines))

    if pilgrims or tickets:
        await update.message.reply_text(t("export_prompt"))


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(t("processing"))
    file = await update.message.document.get_file()
    file_bytes = await file.download_as_bytearray()
    file_name = update.message.document.file_name or "file.pdf"
    await process_file(update, context, msg, bytes(file_bytes), file_name)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = await update.message.reply_text(t("processing"))
    file = await update.message.photo[-1].get_file()
    file_bytes = await file.download_as_bytearray()
    await process_file(update, context, msg, bytes(file_bytes), "photo.jpg")


async def handle_media_group(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message.media_group_id:
        return
    msgs = context.user_data.get("media_group", [])
    msgs.append(update.message)
    context.user_data["media_group"] = msgs

    if update.message.document:
        msg = await update.message.reply_text(t("processing"))
        file = await update.message.document.get_file()
        fb = await file.download_as_bytearray()
        fn = update.message.document.file_name or "file.pdf"
        await process_file(update, context, msg, bytes(fb), fn)
    elif update.message.photo:
        msg = await update.message.reply_text(t("processing"))
        file = await update.message.photo[-1].get_file()
        fb = await file.download_as_bytearray()
        await process_file(update, context, msg, bytes(fb), "photo.jpg")


async def export_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = user_data_store.get(user_id)

    if not data:
        await update.message.reply_text(t("no_data"))
        return

    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        await update.message.reply_text("openpyxl not installed")
        return

    wb = openpyxl.Workbook()
    pilgrims = data.get("pilgrims", [])
    tickets = data.get("tickets", {})
    raw = data.get("raw_text", "")

    ws1 = wb.active
    ws1.title = "Pilgrims"
    ws1.append(["#", "Name", "Flight", "Ticket", "Seat", "Airline"])
    for c in "ABCDEF":
        ws1[f"{c}1"].font = Font(bold=True)
    ws1.column_dimensions["A"].width = 6
    ws1.column_dimensions["B"].width = 35
    ws1.column_dimensions["C"].width = 15
    ws1.column_dimensions["D"].width = 18
    ws1.column_dimensions["E"].width = 10
    ws1.column_dimensions["F"].width = 20

    for i, p in enumerate(pilgrims, 1):
        ws1.append([
            i, p["name"],
            tickets.get("flight_number", ""),
            tickets.get("ticket_number", ""),
            tickets.get("seat", ""),
            tickets.get("airline", ""),
        ])

    ws2 = wb.create_sheet("Raw Text")
    ws2.column_dimensions["A"].width = 120
    for line in raw.split("\n"):
        ws2.append([line])

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False, dir=str(DATA_DIR))
    wb.save(tmp.name)
    tmp.close()

    with open(tmp.name, "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename="pilgrims_data.xlsx"),
            caption=t("export_ok"),
        )
    os.unlink(tmp.name)


async def history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    history = get_history(user_id)
    if not history:
        await update.message.reply_text(t("no_data"))
        return

    total = len(history)
    text_lines = [t("history", str(total)) + "\n"]
    for h in history:
        names = ", ".join(p["name"] for p in h["pilgrims"][:3])
        if len(h["pilgrims"]) > 3:
            names += " ..."
        when = h["created_at"][:19].replace("T", " ")
        text_lines.append(f"🆔 {h['id']} | 🕐 {when}")
        text_lines.append(f"  📄 {h['file_name'] or h['file_type']}: {names}")
        text_lines.append("")

    full_text = "\n".join(text_lines)

    if len(full_text) > 4000:
        tmp = tempfile.NamedTemporaryFile(
            suffix=".txt", delete=False, mode="w", dir=str(DATA_DIR)
        )
        tmp.write(full_text)
        tmp.close()
        with open(tmp.name, "rb") as f:
            await update.message.reply_document(
                document=InputFile(f, filename="history.txt"),
                caption=t("history", str(total)),
            )
        os.unlink(tmp.name)
    else:
        await update.message.reply_text(full_text)


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    stats = get_stats(user_id)

    if stats["total_pilgrims"] == 0:
        await update.message.reply_text(t("no_data"))
        return

    lines = [f"**{t('stats')}:**\n"]
    lines.append(f"👥 {t('pilgrims')}: {stats['total_pilgrims']}")
    lines.append(f"📄 Files: {stats['total_files']}")
    lines.append(f"✈️ Flights: {stats['total_flights']}")
    lines.append(f"🏢 Airlines: {stats['total_airlines']}")

    flights = get_pilgrims_by_flight(user_id)
    if flights:
        lines.append(f"\n**{t('group_flight')}:**")
        for f in flights[:5]:
            lines.append(f"  • {f['flight_number']}: {f['count']} pilgrims")

    airlines = get_pilgrims_by_airline(user_id)
    if airlines:
        lines.append(f"\n**{t('group_airline')}:**")
        for a in airlines[:5]:
            lines.append(f"  • {a['airline']}: {a['count']} pilgrims")

    await update.message.reply_text("\n".join(lines))


async def exportall_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    history = get_history(user_id)
    if not history:
        await update.message.reply_text(t("no_data"))
        return

    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError:
        await update.message.reply_text("openpyxl not installed")
        return

    wb = openpyxl.Workbook()

    ws1 = wb.active
    ws1.title = "All Extractions"
    ws1.append(["#", "Date/Time", "File", "Pilgrims", "Flight", "Ticket", "Seat", "Airline", "Passport"])
    for c in "ABCDEFGHI":
        ws1[f"{c}1"].font = Font(bold=True)
    ws1.column_dimensions["A"].width = 6
    ws1.column_dimensions["B"].width = 22
    ws1.column_dimensions["C"].width = 25
    ws1.column_dimensions["D"].width = 40
    ws1.column_dimensions["E"].width = 15
    ws1.column_dimensions["F"].width = 18
    ws1.column_dimensions["G"].width = 10
    ws1.column_dimensions["H"].width = 20
    ws1.column_dimensions["I"].width = 18

    row = 1
    for h in history:
        pilgrims = h.get("pilgrims", [])
        tickets = h.get("tickets", {})
        when = h["created_at"][:19].replace("T", " ")
        pilgrim_names = "; ".join(p["name"] for p in pilgrims)
        ws1.append([
            h["id"], when, h.get("file_name", h.get("file_type", "")),
            pilgrim_names,
            tickets.get("flight_number", ""),
            tickets.get("ticket_number", ""),
            tickets.get("seat", ""),
            tickets.get("airline", ""),
            tickets.get("passport", ""),
        ])
        row += 1

    ws1.auto_filter.ref = f"A1:I{row}"

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False, dir=str(DATA_DIR))
    wb.save(tmp.name)
    tmp.close()

    with open(tmp.name, "rb") as f:
        await update.message.reply_document(
            document=InputFile(f, filename="all_extractions.xlsx"),
            caption=f"{t('export_ok')} | {t('history', str(len(history)))}",
        )
    os.unlink(tmp.name)


async def sheets_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    data = user_data_store.get(user_id)
    if not data:
        await update.message.reply_text(t("no_data"))
        return

    result = export_to_sheets(data["pilgrims"], data["tickets"])
    await update.message.reply_text(result)


def main() -> None:
    if not TOKEN:
        logger.error("BOT_TOKEN not set")
        print("❌ BOT_TOKEN missing in .env")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_handler))
    app.add_handler(CommandHandler("exportall", exportall_handler))
    app.add_handler(CommandHandler("history", history_handler))
    app.add_handler(CommandHandler("stats", stats_handler))
    app.add_handler(CommandHandler("sheets", sheets_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("✅ Bot running / البوت يعمل")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
