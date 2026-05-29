DIV = "─" * 30

START_MSG = (
    "✈️🕋 *Travelers Ghana* 🕋✈️\n"
    f"{DIV}\n\n"
    "🇬🇧 Send me a PDF or image to extract pilgrim names & ticket details\n"
    "🇸🇦 أرسل لي PDF أو صورة لاستخراج أسماء الحجاج وتفاصيل التذاكر\n\n"
    f"{DIV}\n\n"
    "*/start* /register /export /exportall /history /stats /sheets"
)

BILINGUAL = {
    "processing": "🇬🇧 Processing... ⏳\n🇸🇦 جاري المعالجة... ⏳",
    "unsupported": "🇬🇧 Unsupported file ❌\n🇸🇦 نوع الملف غير مدعوم ❌",
    "error": "🇬🇧 Error: {}\n🇸🇦 خطأ: {}",
    "no_text": "🇬🇧 No text extracted\n🇸🇦 لم يتم استخراج نص",
    "pilgrims": "👥 Pilgrims / الحجاج",
    "tickets": "🎫 Tickets / التذاكر",
    "extracted": "📝 Extracted text / النص المستخرج",
    "export_prompt": "🇬🇧 /export for Excel\n🇸🇦 /export لتصدير Excel\n🇬🇧 /exportall for all data\n🇸🇦 /exportall لتصدير الكل",
    "no_data": "🇬🇧 No data\n🇸🇦 لا توجد بيانات",
    "export_ok": "✅ 🇬🇧 Exported\n✅ 🇸🇦 تم التصدير",
    "history": "📋 🇬🇧 Last {} extractions\n📋 🇸🇦 آخر {} استخراج",
    "stats": "📊 🇬🇧 Statistics\n📊 🇸🇦 الإحصائيات",
    "group_flight": "✈️ By Flight / حسب الرحلة",
    "group_airline": "🏢 By Airline / حسب الشركة",
    "search": "🔍 Search / بحث",
    "not_found": "🇬🇧 Not found\n🇸🇦 لم يتم العثور",
    "qr_found": "✅ 🇬🇧 QR detected\n✅ 🇸🇦 QR مقروء",
    "no_qr": "🇬🇧 No QR found\n🇸🇦 لا يوجد QR",
}

LABEL_MAP = {
    "flight_number": "✈️ 🇬🇧 Flight  |  🇸🇦 رحلة",
    "ticket_number": "🎫 🇬🇧 Ticket  |  🇸🇦 تذكرة",
    "seat": "💺 🇬🇧 Seat  |  🇸🇦 مقعد",
    "date": "📅 🇬🇧 Date  |  🇸🇦 تاريخ",
    "gate": "🚪 🇬🇧 Gate  |  🇸🇦 بوابة",
    "airline": "🏢 🇬🇧 Airline  |  🇸🇦 طيران",
    "passport": "🛂 🇬🇧 Passport  |  🇸🇦 جواز",
    "booking": "📋 🇬🇧 Booking  |  🇸🇦 حجز",
    "class": "💎 🇬🇧 Class  |  🇸🇦 درجة",
    "destination": "🏁 🇬🇧 To  |  🇸🇦 إلى",
    "origin": "📍 🇬🇧 From  |  🇸🇦 من",
    "route": "🛤️ 🇬🇧 Route  |  🇸🇦 مسار",
    "hid": "🆔 🇬🇧 HID  |  🇸🇦 رقم الحاج",
    "booking_ref": "🔖 🇬🇧 Ref  |  🇸🇦 مرجع الحجز",
    "passenger": "👤 🇬🇧 Passenger  |  🇸🇦 مسافر",
}


def t(key: str, *args) -> str:
    val = BILINGUAL.get(key, key)
    if args:
        val = val.format(*args, *args)
    return val


def label(key: str) -> str:
    return LABEL_MAP.get(key, key)
