DIV = "─" * 30

START_MSG = (
    "✈️🕋 *Travelers Ghana* 🕋✈️\n"
    f"{DIV}\n\n"
    "🇸🇦 أرسل لي PDF أو صورة لاستخراج أسماء الحجاج وتفاصيل التذاكر\n\n"
    "🇬🇧 Send me a PDF or image to extract pilgrim names & ticket details\n\n"
    f"{DIV}\n\n"
    "*/start* /export /exportall /history /stats /sheets"
)

BILINGUAL = {
    "processing": "🇸🇦 جاري المعالجة... ⏳\n🇬🇧 Processing... ⏳",
    "unsupported": "🇸🇦 نوع الملف غير مدعوم ❌\n🇬🇧 Unsupported file ❌",
    "error": "🇸🇦 خطأ: {}\n🇬🇧 Error: {}",
    "no_text": "🇸🇦 لم يتم استخراج نص\n🇬🇧 No text extracted",
    "pilgrims": "👥 الحجاج / Pilgrims",
    "tickets": "🎫 التذاكر / Tickets",
    "extracted": "📝 النص المستخرج / Extracted text",
    "export_prompt": "🇸🇦 /export لتصدير Excel\n🇬🇧 /export for Excel\n🇸🇦 /exportall لتصدير الكل\n🇬🇧 /exportall for all data",
    "no_data": "🇸🇦 لا توجد بيانات\n🇬🇧 No data",
    "export_ok": "✅ 🇸🇦 تم التصدير\n✅ 🇬🇧 Exported",
    "history": "📋 🇸🇦 آخر {} استخراج\n📋 🇬🇧 Last {} extractions",
    "stats": "📊 🇸🇦 الإحصائيات\n📊 🇬🇧 Statistics",
    "group_flight": "✈️ حسب الرحلة / By Flight",
    "group_airline": "🏢 حسب الشركة / By Airline",
    "search": "🔍 بحث / Search",
    "not_found": "🇸🇦 لم يتم العثور\n🇬🇧 Not found",
    "qr_found": "✅ 🇸🇦 QR مقروء\n✅ 🇬🇧 QR detected",
    "no_qr": "🇸🇦 لا يوجد QR\n🇬🇧 No QR found",
}

LABEL_MAP = {
    "flight_number": "✈️ 🇸🇦 رحلة  |  🇬🇧 Flight",
    "ticket_number": "🎫 🇸🇦 تذكرة  |  🇬🇧 Ticket",
    "seat": "💺 🇸🇦 مقعد  |  🇬🇧 Seat",
    "date": "📅 🇸🇦 تاريخ  |  🇬🇧 Date",
    "gate": "🚪 🇸🇦 بوابة  |  🇬🇧 Gate",
    "airline": "🏢 🇸🇦 طيران  |  🇬🇧 Airline",
    "passport": "🛂 🇸🇦 جواز  |  🇬🇧 Passport",
    "booking": "📋 🇸🇦 حجز  |  🇬🇧 Booking",
    "class": "💎 🇸🇦 درجة  |  🇬🇧 Class",
    "destination": "🏁 🇸🇦 إلى  |  🇬🇧 To",
    "origin": "📍 🇸🇦 من  |  🇬🇧 From",
    "route": "🛤️ 🇸🇦 مسار  |  🇬🇧 Route",
    "hid": "🆔 🇸🇦 رقم الحاج  |  🇬🇧 HID",
    "booking_ref": "🔖 🇸🇦 مرجع الحجز  |  🇬🇧 Ref",
    "passenger": "👤 🇸🇦 مسافر  |  🇬🇧 Passenger",
}


def t(key: str, *args) -> str:
    val = BILINGUAL.get(key, key)
    if args:
        val = val.format(*args, *args)
    return val


def label(key: str) -> str:
    return LABEL_MAP.get(key, key)
