import re


def clean_line(line: str) -> str:
    line = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", line)
    line = line.strip().rstrip(".:,;- ")
    return line


TICKET_PATTERNS = [
    (r"رقم الرحلة|رحلة رقم|رقم الرحله|الرحلة\s*[:\-]?\s*", "flight_number"),
    (r"رقم التذكرة|تذكرة رقم|رقم التذكره|ticket\s*(no|number|#)[:\-]?\s*", "ticket_number"),
    (r"E-ticket No[.:\s]*", "ticket_number"),
    (r"Booking Reference|Booking\s*(Ref|No|#)[.:\s]*", "booking"),
    (r"Booking No[.:\s]*", "booking"),
    (r"المقعد|مقعد|seat\s*(no|number|#)[:\-]?\s*", "seat"),
    (r"التاريخ|تاريخ الرحلة|تاريخ|date[:\-]?\s*", "date"),
    (r"البوابة|بوابة|gate[:\-]?\s*", "gate"),
    (r"شركة الطيران|الطيران|airline[:\-]?\s*", "airline"),
    (r"رقم الجواز|الجواز|جواز|passport\s*(no|number|#)[:\-]?\s*", "passport"),
    (r"رقم الحجز|حجز|booking\s*(no|number|#)[:\-]?\s*", "booking"),
    (r"درجة\s*(السفر|الحجز)?[:\-]?\s*|class[:\-]?\s*", "class"),
    (r"الوجهة|destination|إلى|to\b[:\-]?\s*", "destination"),
    (r"المغادرة|من|departure|from\b[:\-]?\s*", "origin"),
    (r"رقم الحاج|HID[:\-]?\s*", "hid"),
    (r"PPID[:\-]?\s*", "passport"),
]

NAME_PREFIXES = [
    r"الاسم\s*[:\-]?\s*", r"اسم الحاج\s*[:\-]?\s*", r"اسم الحاجه\s*[:\-]?\s*",
    r"اسم\s*[:\-]?\s*", r"الحاج\s*[:\-]?\s*", r"الحاجه\s*[:\-]?\s*",
    r"passenger\s*name\s*[:\-]?\s*", r"passenger\s*[:\-]?\s*",
    r"pax\s*name\s*[:\-]?\s*", r"pax\s*[:\-]?\s*",
    r"name\s*[:\-]?\s*", r"السيد\s*", r"السيده\s*", r"السيدة\s*",
]

FLIGHT_RE = re.compile(r"\b[A-Z]{2}\s*\d{2,6}\b")
TICKET_NUM_RE = re.compile(r"\b\d{10,15}\b")
BOOKING_REF_RE = re.compile(r"\b[A-Z0-9]{5,7}\b")
E_TICKET_RE = re.compile(r"\b\d{3}-\d{9,10}\b")
HID_RE = re.compile(r"\b\d{12,20}\b")
PPID_RE = re.compile(r"\b\d{5,10}\b")

# زمان الإقلاع: 10:30, 10:30 AM, 22:30, Departure: 10:30, STD: 10:30
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\s*(AM|PM)?\b", re.IGNORECASE)

# JED/Jeddah كلمات مفتاحية
JED_WORDS = re.compile(r"(JED|JEDDAH|جدة|جده)", re.IGNORECASE)


def extract_nusuk_data(text: str, tickets: dict):
    hid_label = re.search(r"HID[\s:]*(\d{12,20})", text)
    if hid_label:
        tickets["hid"] = hid_label.group(1)
    else:
        hid_match = HID_RE.search(text)
        if hid_match:
            tickets["hid"] = hid_match.group()

    ppid_label = re.search(r"PPID[\s:]*(\d{5,10})", text)
    if ppid_label:
        tickets["passport"] = ppid_label.group(1)
    else:
        ppid_match = PPID_RE.search(text)
        if ppid_match and "passport" not in tickets:
            num = ppid_match.group()
            if len(num) >= 5:
                tickets["passport"] = num


def extract_itinerary_data(text: str, pilgrims: list, tickets: dict, seen_names: set):
    name_split = re.findall(
        r"([A-ZÀ-Ú]+(?:\s+[A-ZÀ-Ú]+)*)\s*\(First name\)\s*([A-ZÀ-Ú]+(?:\s+[A-ZÀ-Ú]+)*)\s*\(Last name\)",
        text
    )
    for first, last in name_split:
        full = (first.strip() + " " + last.strip()).strip()
        if full and full not in seen_names and len(full) > 5:
            seen_names.add(full)
            pilgrims.append({"name": full})

    adults = re.findall(r"([A-ZÀ-Ú]{2,}(?:\s+[A-ZÀ-Ú]{2,})+)\s*\(Adults\)", text)
    for a in adults:
        a = a.strip()
        if a and a not in seen_names and len(a) > 5:
            seen_names.add(a)
            pilgrims.append({"name": a})

    e_ticket = E_TICKET_RE.search(text)
    if e_ticket and "ticket_number" not in tickets:
        tickets["ticket_number"] = e_ticket.group()

    booking_no = re.search(r"Booking No[.:\s]*(\d{10,20})", text)
    if booking_no and "booking" not in tickets:
        tickets["booking"] = booking_no.group(1)

    booking_ref = re.search(r"Booking\s+Reference[.\s]*\n?([A-Z0-9]{5,7})", text)
    if booking_ref and "booking_ref" not in tickets:
        tickets["booking_ref"] = booking_ref.group(1)

    airline_matches = re.findall(r"Airline\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)\s*(MS\d{3})", text)
    if airline_matches:
        tickets["airline"] = airline_matches[0][0].strip()

    dates = re.findall(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if dates and "date" not in tickets:
        tickets["date"] = dates[0]

    # كشف مسار الرحلة (تحديث ليشمل JED وجدة)
    route_cities = r"(Taif|Cairo|London|Jeddah|Medina|Mecca|Riyadh|Dammam)"
    routes = re.findall(rf"({route_cities})\s*[-–]\s*({route_cities})", text)
    if routes:
        tickets["route"] = " → ".join(routes[0])
        tickets["origin"] = routes[0][0]
        tickets["destination"] = routes[0][1]

    # كشف وقت الإقلاع (Departure Time)
    dep_time = re.search(r"(?:Departure|Depart|STD|ETD|إقلاع)\s*[:\-]?\s*(\d{1,2}:\d{2})", text, re.IGNORECASE)
    if dep_time:
        tickets["departure_time"] = dep_time.group(1)
    else:
        # أي وقت في النص
        times = TIME_RE.findall(text)
        if times:
            tickets["departure_time"] = times[0][0]
            if times[0][1]:
                tickets["departure_time"] += " " + times[0][1]

    # تاريخ الرحلة (Flight Date) - تاريخ محدد بعد كلمة Date
    flight_date = re.search(r"(?:Flight|Departure|تارخ الرحلة)\s*(?:Date|تاريخ)?[:\-]?\s*(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})", text, re.IGNORECASE)
    if flight_date:
        tickets["flight_date"] = flight_date.group(1)
    else:
        flight_date2 = re.search(r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})", text, re.IGNORECASE)
        if flight_date2:
            tickets["flight_date"] = flight_date2.group(1)


def is_jed_departure(text: str, tickets: dict) -> bool:
    origin = tickets.get("origin", "")
    route = tickets.get("route", "")
    if JED_WORDS.search(origin):
        return True
    if JED_WORDS.search(route) and route.startswith(route[:5]):
        pass
    # البحث في النص الخام عن JED بالقرب من from/departure
    if re.search(r"(?:from|departure|من|مغادرة)\s*.*?(?:JED|Jeddah|جدة|جده)", text, re.IGNORECASE):
        return True
    # البحث عن رحلة برقمها ومصدرها JED
    if re.search(r"(?:(?:JED|Jeddah|جدة|جده)\s*[-–]\s*\w+|JED\d{2,})", text, re.IGNORECASE):
        return True
    return False


def extract_data(text: str) -> dict:
    lines = [clean_line(l) for l in text.split("\n") if clean_line(l)]
    pilgrims = []
    tickets = {}
    seen_names = set()

    for line in lines:
        for pat, key in TICKET_PATTERNS:
            m = re.search(pat, line, re.IGNORECASE)
            if m and key not in tickets:
                val = re.sub(pat, "", line, flags=re.IGNORECASE).strip()
                val = re.sub(r"^[:.\s\-،,]+|[:.\s\-،,]+$", "", val)
                if val and len(val) > 1:
                    tickets[key] = val

    flight_match = FLIGHT_RE.search(text)
    if flight_match and "flight_number" not in tickets:
        tickets["flight_number"] = flight_match.group()

    extract_nusuk_data(text, tickets)
    extract_itinerary_data(text, pilgrims, tickets, seen_names)

    # JED filter - check departure from Jeddah
    tickets["is_jed"] = is_jed_departure(text, tickets)

    for line in lines:
        found = False
        for pat, _ in TICKET_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                found = True
                break
        if FLIGHT_RE.search(line):
            found = True
        if found:
            continue

        name = None
        for prefix in NAME_PREFIXES:
            m = re.search(prefix, line, re.IGNORECASE)
            if m:
                name = line[m.end():].strip().rstrip(".:,;- ")
                break

        if name is None and re.search(r"[\u0600-\u06FF]", line):
            cleaned = re.sub(r"^[\W\d]+|[\W\d]+$", "", line)
            if cleaned and len(cleaned) > 3:
                skip_words = ["رقم", "تذكرة", "مقعد", "بوابة", "شركة", "طيران",
                              "جواز", "حجز", "درجة", "رحلة", "وجهة", "مغادرة",
                              "صعود", "الحاج", "مقدم", "خدمة"]
                if not any(re.search(kw, line, re.IGNORECASE) for kw in skip_words):
                    name = cleaned

        if name is None:
            eng_name = re.search(r"\b([A-Z][a-zÀ-Ú]+(?:\s+[A-Z][a-zÀ-Ú]+){1,4})\b", line)
            if eng_name:
                candidate = eng_name.group(1)
                skip_eng = ["Flight", "Airline", "Departure", "Arrival", "Booking",
                            "Reference", "Economy", "Class", "Transfer", "Baggage",
                            "Personal", "Please", "Itinerary", "Cairo", "London",
                            "Taif", "Heathrow", "Airport", "International", "June",
                            "Checked", "Allowance", "Service", "Provider",
                            "Jeddah", "Medina", "Mecca", "Riyadh"]
                if not any(s in candidate for s in skip_eng) and len(candidate) > 5:
                    name = candidate

        if name and name not in seen_names and len(name) > 2:
            name_clean = re.sub(r"^[\s)\]]+|[\s)\]]+$", "", name).strip()
            skip_full = ["We advise", "Please note", "Baggage", "Carry-on", "Checked",
                         "Personal", "Flight", "Airline", "Booking", "Reference",
                         "Economy", "Class", "Transfer", "Important", "During",
                         "United Kingdom", "Cairo", "London", "Taif", "Heathrow",
                         "Jeddah", "Medina", "Mecca"]
            if name_clean and len(name_clean) > 2 and name_clean not in skip_full:
                if not any(skip in name_clean for skip in skip_full):
                    seen_names.add(name_clean)
                    pilgrims.append({"name": name_clean})

    seen_clean = set()
    pilgrims_clean = []
    for p in pilgrims:
        n = p["name"]
        if n in seen_clean:
            continue
        if len(n) < 3:
            continue
        if re.match(r"^[\s)\]]+$", n):
            continue
        seen_clean.add(n)
        pilgrims_clean.append(p)

    return {
        "pilgrims": pilgrims_clean,
        "tickets": tickets,
        "raw_text": text,
    }
