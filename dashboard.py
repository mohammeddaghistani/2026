import os, io, csv, json, hashlib
from pathlib import Path
from datetime import datetime

import requests as http
from flask import Flask, render_template_string, request, jsonify, redirect, session, Response, make_response

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "transport-ghana-secret-2026")

API_SECRET = os.environ.get("API_SECRET", "tg2026pub")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
UPLOAD_FOLDER = Path("downloads/uploads")
UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
DB_PATH = Path("downloads") / "data.db"

from ocr import extract_text_from_pdf, extract_text_from_image
from extractor import extract_data
from qreader import read_qr_from_image, read_qr_from_pdf, HAS_QR
from db import get_db, init_db, save_extraction, passport_exists, create_user, verify_user, get_all_users, delete_user, count_users, update_status, get_pilgrim, STATUS_OPTIONS

ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
init_db()

# ── Design System ──
DS = {
    "primary": "#1a5632", "primary-dark": "#0d3d1e", "primary-deeper": "#0a2a15",
    "gold": "#c9a227", "gold-light": "#f5e6b8", "gold-dim": "#d4b44a",
    "cream": "#faf8f3", "cream-dark": "#f0ece1",
    "font-en": "'Inter','Segoe UI',sans-serif",
    "font-ar": "'Tajawal',sans-serif",
    "font-display": "'Playfair Display','Georgia',serif",
}
FONT_URL = "https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700;800&family=Inter:wght@300;400;500;600;700&family=Tajawal:wght@400;500;700&display=swap"
PWA_TAGS = """<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="TravGhana">
<meta name="theme-color" content="#1a5632">
<meta name="mobile-web-app-capable" content="yes">
<link rel="manifest" href="/manifest.json">"""

# ── Shared CSS (injected into all templates) ──
SHARED_CSS = f"""
:root{{--p:{DS['primary']};--pd:{DS['primary-dark']};--pd2:{DS['primary-deeper']};--g:{DS['gold']};--gl:{DS['gold-light']};--gd:{DS['gold-dim']};--c:{DS['cream']};--cd:{DS['cream-dark']};--fe:{DS['font-en']};--fa:{DS['font-ar']};--fd:{DS['font-display']}}
*{{font-family:var(--fe);-webkit-font-smoothing:antialiased}}
body{{background:var(--c);min-height:100vh}}
.navbar{{background:linear-gradient(135deg,var(--p),var(--pd))!important;box-shadow:0 2px 16px rgba(0,0,0,.1)}}
.navbar-brand{{font-family:var(--fd);font-weight:800;font-size:1.05rem;letter-spacing:.3px}}
.card{{border:none;border-radius:18px;box-shadow:0 2px 12px rgba(0,0,0,.04);background:#fff}}
.card-header{{background:0 0;border-bottom:1.5px solid rgba(201,162,39,.2);font-weight:700;padding:1rem 1.25rem;color:var(--p)}}
.table{{font-size:.82rem;margin:0}}
.table th{{font-weight:600;color:#555;border-top:none;background:#fafafa;font-size:.72rem;text-transform:uppercase;letter-spacing:.3px;padding:.6rem .5rem}}
.table td{{padding:.5rem;vertical-align:middle}}
.table-hover tbody tr:hover{{background:#f5fff5}}
.passport-text{{font-family:'SF Mono','Courier New',monospace;font-weight:700;letter-spacing:.8px;font-size:.78rem}}
.secret-badge{{font-size:.68rem;color:#c62828;font-weight:800;background:#fff5f5;padding:.15rem .5rem;border-radius:6px;font-family:'SF Mono',monospace}}
footer{{text-align:center;padding:2rem;color:#bbb;font-size:.75rem}}
footer::before{{content:'';display:block;width:32px;height:1.5px;background:var(--g);margin:0 auto .8rem;opacity:.3}}
"""


def notify_admin(name, passport, flight=""):
    if not BOT_TOKEN or not ADMIN_CHAT_ID: return
    try:
        http.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                  json={"chat_id": ADMIN_CHAT_ID,
                        "text": f"🆕 *طلب جديد / New Submission*\n👤 {name}\n🛂 {passport}\n✈️ {flight or '—'}",
                        "parse_mode": "Markdown"}, timeout=5)
    except: pass


def process_file_bytes(file_bytes, file_name):
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTS: return {"error": "Unsupported file type"}
    try:
        text = ""
        qr_data = []
        if ext == ".pdf":
            text = extract_text_from_pdf(file_bytes)
            if HAS_QR: qr_data = read_qr_from_pdf(file_bytes)
        else:
            text = extract_text_from_image(file_bytes)
            if HAS_QR: qr_data = read_qr_from_image(file_bytes)
    except Exception as e: return {"error": str(e)}
    data = extract_data(text)
    data["qr"] = [str(q) for q in qr_data[:3]]
    return data


def handle_submission(ticket_bytes, ticket_name, passport_bytes, passport_name, name, passport,
                      departure_date="", departure_time="", flight_number="",
                      departure_location="", declaration=""):
    td, pd = {"pilgrims": [], "tickets": {}, "raw_text": ""}, {"pilgrims": [], "tickets": {}, "raw_text": ""}
    if ticket_bytes:
        d = process_file_bytes(ticket_bytes, ticket_name)
        if "error" not in d: td = d
    if passport_bytes:
        d = process_file_bytes(passport_bytes, passport_name)
        if "error" not in d: pd = d
    pilgrims = td.get("pilgrims", []) or pd.get("pilgrims", [])
    tickets = {}
    if name: (pilgrims if pilgrims else ([{"name": name}]) if not pilgrims else pilgrims)[0]["name"] = name if name else (pilgrims[0].get("name","") if pilgrims else "")
    if passport: tickets["passport"] = passport
    for k in ("departure_date","departure_time","flight_number","departure_location","declaration"):
        tickets[k] = locals()[k]
    raw = td.get("raw_text","")+"\n---\n"+pd.get("raw_text","")
    fname = ticket_name or passport_name or "manual"
    try:
        eid = save_extraction(user_id=0, username="web", file_name=fname,
                              file_type=Path(fname).suffix.lower() if fname!="manual" else "manual",
                              pilgrims=pilgrims, tickets=tickets, raw_text=raw)
    except Exception as e: return {"error": str(e)}
    notify_admin(name, tickets.get("passport",""), flight_number)
    return {"success": True, "request_id": eid, "pilgrims": pilgrims, "tickets": tickets, "has_files": bool(ticket_bytes or passport_bytes)}


# ────────────────────── Form Page (PUBLIC_HTML) ──────────────────────

PUBLIC_HTML = rf"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Travelers Ghana — Pilgrim Registration</title>
{PWA_TAGS}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="{FONT_URL}" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
{SHARED_CSS}
.hero{{background:linear-gradient(160deg,var(--p),var(--pd) 40%,var(--pd2));padding:1.5rem 1rem 3.5rem;text-align:center;position:relative;overflow:hidden}}
.hero::before{{content:'';position:absolute;inset:0;background:radial-gradient(circle at 20% 50%,rgba(201,162,39,.08) 0%,transparent 50%),radial-gradient(circle at 80% 50%,rgba(255,255,255,.04) 0%,transparent 50%);pointer-events:none}}
.hero::after{{content:'';position:absolute;inset:0;background:url("data:image/svg+xml,%3Csvg width='120' height='120' viewBox='0 0 120 120' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.025'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");pointer-events:none;opacity:.5}}
.hero-icon{{display:inline-flex;align-items:center;justify-content:center;width:68px;height:68px;border-radius:50%;background:rgba(201,162,39,.12);backdrop-filter:blur(4px);border:1px solid rgba(201,162,39,.2);font-size:1.8rem;margin-bottom:.5rem}}
.hero h1{{font-family:var(--fd);font-weight:800;font-size:1.6rem;color:#fff;margin:0;letter-spacing:.3px}}
.hero h1 span{{background:linear-gradient(135deg,var(--g),var(--gl));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
.hero p{{color:rgba(255,255,255,.6);font-size:.82rem;margin:.3rem 0 0;font-weight:300}}
.hero .ar-sub{{font-family:var(--fa);font-size:.75rem;color:rgba(255,255,255,.35);margin-top:.1rem}}
.gold-line{{width:40px;height:2px;background:linear-gradient(90deg,var(--g),var(--gl));margin:.5rem auto 0;border-radius:2px}}
.container-form{{max-width:780px;margin:0 auto;padding:0 .75rem}}
.card-form{{border:none;border-radius:24px;box-shadow:0 12px 48px rgba(10,42,21,.1);margin-top:-1.8rem;background:#fff;overflow:hidden;position:relative;z-index:2}}
.card-form::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--p),var(--g),var(--p))}}
.card-form-body{{padding:1.5rem 1.25rem}}
.section{{border:1px solid rgba(0,0,0,.05);border-radius:14px;padding:1.2rem;margin-bottom:1rem;background:#fff;transition:all .3s;position:relative}}
.section:hover{{box-shadow:0 4px 20px rgba(10,42,21,.04);border-color:rgba(201,162,39,.12)}}
.section::after{{content:'';position:absolute;top:0;left:0;width:3px;height:100%;background:linear-gradient(180deg,var(--g),transparent);border-radius:3px 0 0 3px;opacity:0;transition:opacity .3s}}
.section:hover::after{{opacity:1}}
.section-title{{display:flex;align-items:center;gap:.5rem;font-weight:700;font-size:.8rem;color:var(--p);margin-bottom:.6rem;padding-bottom:.4rem;border-bottom:1.5px solid rgba(201,162,39,.15);text-transform:uppercase;letter-spacing:.3px}}
.section-title .ar{{font-family:var(--fa);font-weight:500;font-size:.72rem;color:#999;text-transform:none;letter-spacing:0;margin-left:auto}}
.section-number{{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:linear-gradient(135deg,var(--p),var(--pd));color:#fff;font-size:.65rem;font-weight:700;flex-shrink:0;box-shadow:0 2px 6px rgba(26,86,50,.15)}}
.form-label{{font-weight:600;font-size:.76rem;margin-bottom:.15rem;color:#222;display:flex;align-items:baseline;gap:.35rem;line-height:1.3}}
.form-label .ar{{font-family:var(--fa);font-weight:400;font-size:.7rem;color:#aaa}}
.form-control,.form-select{{border-radius:10px;padding:.55rem .8rem;border:1.5px solid #e2e2e2;font-size:.85rem;transition:all .25s;background:#fff}}
.form-control:focus,.form-select:focus{{border-color:var(--g);box-shadow:0 0 0 4px rgba(201,162,39,.1);background:#fff}}
.form-text-hint{{font-size:.65rem;color:#aaa;margin-bottom:.15rem}}
.btn-submit{{background:linear-gradient(135deg,var(--p),var(--pd));border:none;border-radius:50px;padding:.75rem 1.2rem;font-weight:600;font-size:.88rem;color:#fff;transition:all .35s;position:relative;overflow:hidden}}
.btn-submit:hover{{transform:translateY(-2px);box-shadow:0 10px 32px rgba(26,86,50,.3);color:#fff}}
.btn-submit::after{{content:'';position:absolute;top:-50%;left:-50%;width:200%;height:200%;background:linear-gradient(45deg,transparent,rgba(255,255,255,.08),transparent);transform:rotate(45deg);transition:.5s}}
.btn-submit:hover::after{{left:100%}}
.upload-area{{border:1.5px dashed #d0d0d0;border-radius:12px;padding:.7rem .5rem;text-align:center;cursor:pointer;transition:all .3s;background:#fafafa}}
.upload-area:hover{{border-color:var(--g);background:linear-gradient(135deg,var(--gl),#faf8f3);transform:translateY(-1px)}}
.upload-area i{{font-size:1.6rem;color:#bbb;display:block;margin-bottom:.25rem;transition:color .3s}}
.upload-area:hover i{{color:var(--g)}}
.upload-area p{{color:#999;margin:0;font-size:.75rem}}
.upload-area .filename{{color:var(--p);font-weight:600;font-size:.78rem}}
.alert{{border-radius:12px;font-size:.8rem;padding:.6rem .9rem;border:none;animation:slideDown .35s ease}}
@keyframes slideDown{{from{{opacity:0;transform:translateY(-8px)}}to{{opacity:1;transform:translateY(0)}}}}
.alert-success{{background:#e8f5e9;color:#1a5632;border-left:3px solid var(--p)}}
.alert-danger{{background:#fce4ec;color:#b71c1c;border-left:3px solid #e53935}}
.declaration-box{{background:linear-gradient(135deg,var(--c),#fff);border:1px solid rgba(201,162,39,.12);border-radius:10px;padding:.8rem 1rem}}
.form-check-input:checked{{background-color:var(--p);border-color:var(--p)}}
.passport-input{{direction:ltr;text-align:left;font-family:'SF Mono','Courier New',monospace;letter-spacing:1px;font-size:.82rem}}
.request-badge{{background:linear-gradient(135deg,var(--p),var(--pd));color:#fff;border-radius:50px;padding:.4rem 1.1rem;font-size:.9rem;font-weight:700;display:inline-block;font-family:var(--fd);box-shadow:0 4px 16px rgba(26,86,50,.15);animation:fadeInUp .45s ease}}
@keyframes fadeInUp{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:translateY(0)}}}}
@media(min-width:768px){{.hero{{padding:2rem 1rem 4rem}}.hero h1{{font-size:2.2rem}}.card-form-body{{padding:2rem}}.section{{padding:1.4rem}}}}
</style></head><body>

<div class="hero" style="padding-top:1.2rem">
  <div style="position:absolute;top:.4rem;left:.6rem;z-index:5">
    <a href="/" style="color:rgba(255,255,255,.5);text-decoration:none;font-size:.72rem;display:flex;align-items:center;gap:.25rem"><i class="bi bi-arrow-left"></i> <span style="font-family:var(--fa)">عودة</span></a>
  </div>
  <div class="hero-icon">🕋</div>
  <h1>Travelers <span>Ghana</span></h1>
  <p>Pilgrim Registration &amp; Ticket Information System</p>
  <div class="ar-sub">مسافري غانا — نظام تسجيل الحجاج وتذاكر السفر</div>
  <div class="gold-line"></div>
</div>

<div class="container-form">
  <div class="card-form">
    <div class="card-form-body">
      <div id="alertBox" class="alert d-none"></div>
      <div id="requestIdBox" class="text-center d-none mb-3"></div>

      <form id="submitForm" enctype="multipart/form-data">

        <!-- Section 1 -->
        <div class="section">
          <div class="section-title">
            <span class="section-number">1</span>
            Personal &amp; Travel Data
            <span class="ar">البيانات الشخصية وبيانات السفر</span>
          </div>
          <div class="mb-3">
            <label class="form-label">
              <span class="en">Traveler's Full Name</span>
              <span class="ar">الاسم الكامل للحاج</span>
            </label>
            <input type="text" class="form-control" id="pilgrimName" name="name" placeholder="Full name">
          </div>
          <div class="mb-0">
            <label class="form-label">
              <span class="en">Passport Number <span class="text-danger">*</span></span>
              <span class="ar">رقم جواز السفر</span>
            </label>
            <input type="text" class="form-control passport-input" id="passportInput" name="passport" required
                   placeholder="Passport number" pattern="\S+"
                   oninvalid="this.setCustomValidity('No spaces allowed')" oninput="this.setCustomValidity('')"
                   onblur="checkPassport(this.value)">
            <small class="text-muted" id="passportStatus"></small>
          </div>
        </div>

        <!-- Section 2 -->
        <div class="section">
          <div class="section-title">
            <span class="section-number">2</span>
            Departure Details
            <span class="ar">تفاصيل المغادرة</span>
          </div>
          <div class="row g-2 mb-3">
            <div class="col-6">
              <label class="form-label">
                <span class="en">Departure Date <span class="text-muted fw-normal" style="font-size:.62rem">(Gregorian — ميلادي)</span></span>
                <span class="ar">تاريخ المغادرة</span>
              </label>
              <input type="date" class="form-control" id="departureDate" name="departure_date" min="2025-01-01" max="2050-12-31">
              <div class="form-text-hint">Gregorian only — ميلادي فقط (YYYY-MM-DD)</div>
            </div>
            <div class="col-6">
              <label class="form-label">
                <span class="en">Departure Time <span class="text-muted fw-normal" style="font-size:.62rem">(24h)</span></span>
                <span class="ar">وقت المغادرة</span>
              </label>
              <input type="time" class="form-control" id="departureTime" name="departure_time" step="60">
              <div class="form-text-hint">24-hour format — نظام ٢٤ ساعة</div>
            </div>
          </div>
          <div class="mb-3">
            <label class="form-label">
              <span class="en">Flight / Bus Number</span>
              <span class="ar">رقم الرحلة / الحافلة</span>
            </label>
            <input type="text" class="form-control" id="flightNumber" name="flight_number" placeholder="e.g. XY123">
          </div>
          <div class="mb-0">
            <label class="form-label">
              <span class="en">Departure Location</span>
              <span class="ar">مكان المغادرة</span>
            </label>
            <select class="form-select" id="departureLocation" name="departure_location">
              <option value="">— Select —</option>
              <option value="Jeddah Airport (KAIA)">Jeddah Airport (KAIA) — مطار جدة</option>
              <option value="Medina Airport">Medina Airport — مطار المدينة</option>
              <option value="Land Border">Land Border — منفذ بري</option>
            </select>
          </div>
        </div>

        <!-- Section 3 -->
        <div class="section">
          <div class="section-title">
            <span class="section-number">3</span>
            Attachments
            <span class="ar">المرفقات والوثائق</span>
          </div>
          <div class="form-text-hint mb-2">Optional — you can skip</div>
          <div class="row g-2">
            <div class="col-md-6">
              <label class="form-label"><span class="en">Flight Ticket</span><span class="ar">التذكرة</span></label>
              <div class="upload-area" onclick="document.getElementById('ticketFile').click()">
                <i class="bi bi-file-earmark-text"></i>
                <p id="ticketUploadText">Tap to upload</p>
              </div>
              <input type="file" id="ticketFile" name="file_ticket" accept=".pdf,.jpg,.jpeg,.png" class="d-none" onchange="updateFileName(this,'ticketUploadText')">
            </div>
            <div class="col-md-6">
              <label class="form-label"><span class="en">Passport / Nusuk</span><span class="ar">الجواز أو نسك</span></label>
              <div class="upload-area" onclick="document.getElementById('passportFile').click()">
                <i class="bi bi-person-badge"></i>
                <p id="passportUploadText">Tap to upload</p>
              </div>
              <input type="file" id="passportFile" name="file_passport" accept=".pdf,.jpg,.jpeg,.png" class="d-none" onchange="updateFileName(this,'passportUploadText')">
            </div>
          </div>
        </div>

        <!-- Section 4 -->
        <div class="section">
          <div class="section-title">
            <span class="section-number">4</span>
            Declaration
            <span class="ar">الإقرار النهائي</span>
          </div>
          <div class="declaration-box">
            <div class="form-check mb-0">
              <input class="form-check-input" type="checkbox" id="declarationCheck" name="declaration" value="agreed" required>
              <label class="form-check-label" for="declarationCheck" style="font-size:.8rem;color:#444;line-height:1.5">
                <strong>I hereby certify</strong> that all the information provided is accurate and matches my official travel documents.
                <br><span style="font-family:var(--fa);font-size:.72rem;color:#888">أقر بأن جميع المعلومات المقدمة صحيحة ومطابقة لوثائق سفري الرسمية.</span>
              </label>
            </div>
          </div>
        </div>

        <button type="submit" class="btn btn-submit w-100" id="submitBtn">
          <i class="bi bi-send-fill me-2"></i> Submit Request — إرسال الطلب
        </button>
      </form>

      <div class="text-center mt-3">
        <span style="display:inline-flex;align-items:center;gap:.3rem;background:rgba(26,86,50,.04);border:1px solid rgba(26,86,50,.08);border-radius:50px;padding:.2rem .6rem;font-size:.65rem;color:#888">
          <i class="bi bi-shield-check"></i> Your data is protected
        </span>
      </div>
    </div>
  </div>
</div>

<footer>Travelers Ghana — مسافري غانا</footer>

<script>
function updateFileName(i,l){document.getElementById(l).textContent=i.files.length?i.files[0].name:"Tap to upload"}
function showAlert(m,t){
  const b=document.getElementById("alertBox"),i=t==="error"?"bi-exclamation-triangle-fill":"bi-check-circle-fill";
  b.className="alert alert-"+(t==="error"?"danger":"success")+" d-flex align-items-center";
  b.innerHTML='<i class="bi '+i+' me-2"></i> '+m;b.classList.remove("d-none");
  setTimeout(()=>{b.className="alert d-none"},8000)
}
async function checkPassport(v){
  const s=document.getElementById("passportStatus");
  if(!v||v.length<3){s.textContent="";return}
  s.textContent="Checking…";
  try{
    const r=await fetch("/api/check_passport?passport="+encodeURIComponent(v)),d=await r.json();
    s.textContent=d.exists?"❌ Already registered":"✅ Available";
    s.className=d.exists?"text-danger":"text-success"
  }catch(e){s.textContent=""}
}
document.getElementById("submitForm").addEventListener("submit",async function(e){
  e.preventDefault();
  const n=document.getElementById("pilgrimName").value.trim(),p=document.getElementById("passportInput").value.trim(),
    dd=document.getElementById("departureDate").value,dt=document.getElementById("departureTime").value,
    fn=document.getElementById("flightNumber").value.trim(),dl=document.getElementById("departureLocation").value,
    dc=document.getElementById("declarationCheck").checked?"agreed":"";
  if(!p){showAlert("Passport required — الرجاء تعبئة رقم الجواز","error");return}
  if(p.includes(" ")){showAlert("No spaces in passport — رقم الجواز لا يقبل مسافات","error");return}
  if(dd&&!/^\d{4}-\d{2}-\d{2}$/.test(dd)){showAlert("Invalid date — تاريخ غير صحيح (YYYY-MM-DD)","error");return}
  if(!dc){showAlert("Please agree to the declaration — وافق على الإقرار","error");return}
  const btn=document.getElementById("submitBtn");btn.disabled=!0;
  btn.innerHTML='<span class="spinner-border spinner-border-sm me-2"></span> Submitting…';
  const fd=new FormData();
  const tf=document.getElementById("ticketFile"),pf=document.getElementById("passportFile");
  if(tf.files.length)fd.append("file_ticket",tf.files[0]);
  if(pf.files.length)fd.append("file_passport",pf.files[0]);
  fd.append("name",n);fd.append("passport",p);fd.append("departure_date",dd);
  fd.append("departure_time",dt);fd.append("flight_number",fn);
  fd.append("departure_location",dl);fd.append("declaration",dc);
  try{
    const r=await fetch("/api/submit",{method:"POST",body:fd}),d=await r.json();
    if(d.success){
      const rid=d.request_id||"";
      showAlert("✅ Submitted! Request #"+rid,"success");
      if(rid){
        const box=document.getElementById("requestIdBox");
        box.classList.remove("d-none");
        box.innerHTML='<span class="request-badge">📋 Request #'+rid+'</span><br>'+
          '<a href="/edit/'+rid+'" class="btn btn-sm mt-2" style="border-radius:50px;border:1.5px solid var(--g);color:var(--g);background:transparent;font-size:.72rem;font-weight:600;text-decoration:none;padding:.2rem .7rem"><i class="bi bi-pencil"></i> Edit — تعديل</a>'
      }
      this.reset();document.getElementById("ticketUploadText").textContent="Tap to upload";
      document.getElementById("passportUploadText").textContent="Tap to upload";
      document.getElementById("passportStatus").textContent=""
    }else if(d.duplicate){showAlert("❌ Passport already registered — مسجل مسبقاً","error")}
    else{showAlert("Error: "+(d.error||"Unknown"),"error")}
  }catch(e){showAlert("Submission failed","error")}
  btn.disabled=!1;btn.innerHTML='<i class="bi bi-send-fill me-2"></i> Submit Request — إرسال الطلب'
});
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""

# ────────────────────── Admin Panel ──────────────────────

ADMIN_HTML = """<!DOCTYPE html>
<html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ L.admin_title }}</title>
""" + PWA_TAGS + """<link rel="preconnect" href="https://fonts.googleapis.com">
<link href=\"""" + FONT_URL + """\" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
""" + SHARED_CSS + """
.stat-card{border:none;border-radius:18px;box-shadow:0 2px 12px rgba(0,0,0,.04);padding:1.2rem;transition:all .25s;background:#fff;height:100%}
.stat-card:hover{box-shadow:0 6px 20px rgba(0,0,0,.06);transform:translateY(-2px)}
.stat-number{font-size:1.6rem;font-weight:800;color:var(--p);line-height:1.2}
.stat-label{color:#888;font-size:.78rem;font-weight:500}
.search-box{border-radius:50px;padding:.5rem 1.2rem;border:1.5px solid #e5e7eb;background:#fafafa;font-size:.85rem}
.search-box:focus{border-color:var(--g);box-shadow:0 0 0 4px rgba(201,162,39,.1);background:#fff}
.btn-soft{background:#fff;border:1.5px solid #e5e7eb;border-radius:50px;padding:.3rem .7rem;font-size:.72rem;font-weight:600;color:#555;transition:all .2s;text-decoration:none}
.btn-soft:hover{background:var(--p);color:#fff;border-color:var(--p)}
</style></head><body>

<nav class="navbar navbar-expand-lg navbar-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="/admin"><i class="bi bi-shield-lock me-2"></i>{{ L.admin_title }}</a>
    <div class="d-flex gap-2 align-items-center">
      <a href="/" class="btn btn-sm btn-outline-light py-1 px-2"><i class="bi bi-house"></i></a>
      <a href="/admin/users" class="btn btn-sm btn-outline-light py-1"><i class="bi bi-people me-1"></i>{{ 'المستخدمين' if lang == 'ar' else 'Users' }}</a>
      <a href="?lang={{ 'en' if lang == 'ar' else 'ar' }}" class="btn btn-sm btn-outline-light py-1">{{ '🇸🇦' if lang == 'ar' else '🇬🇧' }}</a>
      <a href="/admin/logout" class="btn btn-sm btn-outline-light py-1"><i class="bi bi-box-arrow-right"></i></a>
    </div>
  </div>
</nav>

<div class="container-fluid py-4 px-lg-4">
  <div class="row g-3 mb-4">
    <div class="col-6 col-md-3">
      <div class="stat-card"><div class="d-flex justify-content-between align-items-start">
        <div><div class="stat-number">{{ stats.total }}</div><div class="stat-label">{{ L.total_pilgrims }}</div></div>
        <div class="stat-icon fs-3 text-success opacity-50"><i class="bi bi-people"></i></div>
      </div></div>
    </div>
    <div class="col-6 col-md-3">
      <div class="stat-card"><div class="d-flex justify-content-between align-items-start">
        <div><div class="stat-number">{{ stats.flights }}</div><div class="stat-label">{{ L.total_flights }}</div></div>
        <div class="stat-icon fs-3 text-primary opacity-50"><i class="bi bi-airplane"></i></div>
      </div></div>
    </div>
    <div class="col-6 col-md-3">
      <div class="stat-card"><div class="d-flex justify-content-between align-items-start">
        <div><div class="stat-number">{{ stats.airlines }}</div><div class="stat-label">{{ L.total_airlines }}</div></div>
        <div class="stat-icon fs-3 text-warning opacity-50"><i class="bi bi-building"></i></div>
      </div></div>
    </div>
    <div class="col-6 col-md-3">
      <div class="stat-card"><div class="d-flex justify-content-between align-items-start">
        <div><div class="stat-number">{{ stats.web }}</div><div class="stat-label">{{ L.web_submissions }}</div></div>
        <div class="stat-icon fs-3 text-info opacity-50"><i class="bi bi-globe"></i></div>
      </div></div>
    </div>
  </div>

  <div class="card">
    <div class="card-header"><div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
      <span><i class="bi bi-table me-2"></i>{{ L.all_submissions }} <span class="text-muted fw-normal">({{ pilgrims|length }})</span></span>
      <div class="d-flex gap-2">
        <a href="/admin/export_csv" class="btn-soft"><i class="bi bi-filetype-csv me-1"></i> CSV</a>
        <a href="/admin/export_xlsx" class="btn-soft"><i class="bi bi-file-earmark-excel me-1"></i> Excel</a>
      </div>
    </div></div>
    <div class="card-body p-3">
      <form class="mb-3" method="get">
        <div class="input-group">
          <input type="text" name="q" class="form-control search-box border-end-0" placeholder="{{ L.search_placeholder }}" value="{{ query }}">
          <button class="btn btn-primary rounded-end-pill px-3" type="submit" style="background:var(--p);border-color:var(--p)"><i class="bi bi-search"></i></button>
        </div>
      </form>
      <div class="table-responsive" style="border-radius:12px;border:1px solid #f0f0f0">
        <table class="table table-hover align-middle mb-0">
          <thead><tr>
            <th style="width:48px">{{ L.source }}</th>
            <th>🔐</th><th>{{ L.name }}</th><th>{{ L.passport }}</th>
            <th>{{ L.flight }}</th><th>{{ L.departure_time }}</th><th>{{ L.departure_location }}</th>
            <th>Status</th><th>{{ L.date }}</th><th style="width:40px"></th>
          </tr></thead>
          <tbody>
            {% set styles={'processing':'bg-warning-subtle text-warning-emphasis','under_action':'bg-info-subtle text-info-emphasis','completed':'bg-success-subtle text-success-emphasis','departed':'bg-secondary-subtle text-secondary-emphasis'} %}
            {% for p in pilgrims %}
            {% set sv = p.status or '' %}
            <tr>
              <td><span class="badge rounded-pill fs-7 {{ 'bg-primary-subtle text-primary-emphasis' if p.user_id != 0 else 'bg-success-subtle text-success-emphasis' }}">{{ '📱' if p.user_id != 0 else '🌐' }}</span></td>
              <td><span class="secret-badge">TG{{ '%04d'|format(p.id) }}</span></td>
              <td><strong>{{ p.name }}</strong></td>
              <td><span class="passport-text">{{ p.passport }}</span></td>
              <td>{% if p.flight_number %}<span class="badge bg-secondary-subtle text-secondary-emphasis fw-medium">{{ p.flight_number }}</span>{% endif %}</td>
              <td class="small text-muted">{{ p.departure_time }}</td>
              <td class="small text-muted">{{ p.departure_location }}</td>
              <td>
                {% if sv and sv in styles %}
                  <span class="badge {{ styles[sv] }} rounded-pill" style="font-size:.62rem">{{ sv.replace('_',' ')|title }}</span>
                {% else %}
                  <form method="post" action="/api/update_status/{{ p.id }}" class="d-inline status-form">
                    <select name="status" class="form-select form-select-sm" style="font-size:.62rem;padding:.1rem .25rem;width:85px;border-radius:50px;border:1px solid #ddd" onchange="this.form.submit()">
                      <option value="">Set…</option>
                      {% for sk, sl in [('processing','Processing'),('under_action','Under Action'),('completed','Completed'),('departed','Departed')] %}
                      <option value="{{ sk }}">{{ sl }}</option>
                      {% endfor %}
                    </select>
                  </form>
                {% endif %}
              </td>
              <td class="small text-muted">{{ p.created_at[:10] }}</td>
              <td>
                <form method="post" action="/admin/delete/{{ p.id }}" onsubmit="return confirm('{{ L.confirm_delete }}')" class="d-inline">
                  <button class="btn btn-outline-danger btn-sm border-0 px-1 py-0"><i class="bi bi-trash3"></i></button>
                </form>
              </td>
            </tr>
            {% else %}
            <tr><td colspan="10" class="text-center text-muted py-5">{{ L.no_data }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
<footer>Travelers Ghana — مسافري غانا</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{{ L.admin_login }}</title>
""" + PWA_TAGS + """<link rel="preconnect" href="https://fonts.googleapis.com">
<link href=\"""" + FONT_URL + """\" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{min-height:100vh;background:linear-gradient(135deg,#1a5632 0%,#0d3d1e 50%,#0a2a15 100%);display:flex;align-items:center;font-family:'Inter',sans-serif;position:relative}
body::before{content:'';position:fixed;inset:0;background-image:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23c9a227' fill-opacity='0.04'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");pointer-events:none;z-index:0}
.card{border:none;border-radius:20px;box-shadow:0 25px 80px rgba(0,0,0,.4);overflow:hidden;position:relative;z-index:1;border-top:4px solid #c9a227}
.card-body{padding:2.75rem 2.25rem}
h2{font-family:'Playfair Display',Georgia,serif;font-weight:800;color:#1a5632;font-size:1.7rem}
.form-label{font-size:.78rem;text-transform:uppercase;letter-spacing:.5px;color:#6b7280;margin-bottom:.3rem}
.form-control{border-radius:10px;padding:.75rem 1rem;border:2px solid #e5e7eb;font-size:.9rem;transition:border-color .25s,box-shadow .25s}
.form-control:focus{border-color:#c9a227;box-shadow:0 0 0 4px rgba(201,162,39,.12)}
.btn-primary{background:linear-gradient(135deg,#1a5632,#0d3d1e);border:none;border-radius:50px;padding:.8rem;font-weight:600;letter-spacing:.3px;transition:all .3s}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(26,86,50,.35)}
.decorative-line{display:flex;align-items:center;justify-content:center;gap:8px;margin:.8rem auto 1.25rem}
.decorative-line span{display:block;height:1px;background:linear-gradient(90deg,transparent,#c9a227,transparent);flex:1;max-width:60px}
.decorative-line .diamond{width:7px;height:7px;background:#c9a227;transform:rotate(45deg);flex-shrink:0}
.alert-custom{background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #dc2626;border-radius:8px;padding:.6rem .9rem;font-size:.8rem;color:#991b1b;margin-bottom:1.25rem;font-weight:500}
.footer-text{margin-top:1.75rem;padding-top:1rem;border-top:1px solid #f3f4f6;font-size:.7rem;color:#9ca3af}
.footer-text span{color:#c9a227;font-weight:600}
</style></head><body>
<div class="container"><div class="row justify-content-center"><div class="col-md-5">
<div class="card"><div class="card-body text-center">
  <div style="font-size:2.25rem;margin-bottom:.15rem;line-height:1">🔐</div>
  <h2>{{ L.admin_login }}</h2>
  <p class="text-muted" style="font-family:'Tajawal',sans-serif;font-size:.85rem">دخول المشرف</p>
  <div class="decorative-line"><span></span><div class="diamond"></div><span></span></div>
  {% if error %}<div class="alert-custom">{{ error }}</div>{% endif %}
  <form method="post" action="/admin">
    <div class="mb-4 text-start">
      <label class="form-label fw-semibold">{{ L.admin_password }}</label>
      <input type="password" name="password" class="form-control" required autofocus placeholder="Enter admin password">
    </div>
    <button type="submit" class="btn btn-primary w-100">{{ L.login_btn }}</button>
  </form>
  <div class="footer-text">Travelers Ghana <span>—</span> مسافري غانا</div>
</div></div></div></div></div>
</body></html>"""

EDIT_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Edit Request — Travelers Ghana</title>
""" + PWA_TAGS + """<link rel="preconnect" href="https://fonts.googleapis.com">
<link href=\"""" + FONT_URL + """\" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{min-height:100vh;background:linear-gradient(135deg,#1a5632 0%,#0d3d1e 50%,#0a2a15 100%)}
.card{border:none;border-radius:20px;box-shadow:0 20px 60px rgba(0,0,0,.3);margin:2rem auto;max-width:540px;background:#fff}
.card-body{padding:2rem}
h2{font-family:'Playfair Display',Georgia,serif;font-weight:800;color:#1a5632;font-size:1.4rem;margin:0}
.form-label{font-weight:600;font-size:.78rem;color:#333;margin-bottom:.15rem}
.form-control,.form-select{border-radius:10px;padding:.6rem .85rem;border:1.5px solid #e2e2e2;font-size:.85rem;transition:all .25s}
.form-control:focus,.form-select:focus{border-color:#c9a227;box-shadow:0 0 0 4px rgba(201,162,39,.1)}
.btn-primary{background:linear-gradient(135deg,#1a5632,#0d3d1e);border:none;border-radius:50px;padding:.7rem;font-weight:600}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 6px 20px rgba(26,86,50,.25)}
.alert{border-radius:12px;font-size:.82rem;padding:.6rem .9rem;border:none}
.alert-success{background:#e8f5e9;color:#1a5632}
.alert-danger{background:#fce4ec;color:#b71c1c}
.request-id{display:inline-block;background:rgba(201,162,39,.1);color:#c9a227;border-radius:50px;padding:.2rem .7rem;font-size:.72rem;font-weight:700;font-family:'SF Mono',monospace}
footer{text-align:center;padding:1.5rem;color:rgba(255,255,255,.4);font-size:.7rem}
</style></head><body>
<div style="padding:1.5rem 1rem 0;text-align:center">
  <a href="/" style="color:rgba(255,255,255,.5);text-decoration:none;font-size:.75rem"><i class="bi bi-house"></i> Home</a>
</div>
<div class="card"><div class="card-body">
  <div class="text-center mb-3">
    <div style="font-size:2rem;margin-bottom:.25rem">✏️</div>
    <h2>Edit Request</h2>
    <p class="text-muted small" style="font-family:'Tajawal',sans-serif">تعديل الطلب</p>
    <span class="request-id">📋 #{{ pilgrim.id }}</span>
  </div>
  {% if success %}<div class="alert alert-success">{{ success }}</div>{% endif %}
  {% if error %}<div class="alert alert-danger">{{ error }}</div>{% endif %}
  <form method="post">
    <div class="mb-3">
      <label class="form-label">Passport — جواز السفر <span class="text-danger">*</span></label>
      <input type="text" class="form-control" name="passport" value="{{ pilgrim.passport }}" required placeholder="Enter passport to verify">
    </div>
    <div class="mb-3">
      <label class="form-label">Full Name — الاسم الكامل</label>
      <input type="text" class="form-control" name="name" value="{{ pilgrim.name }}" placeholder="Full name">
    </div>
    <div class="row g-2 mb-3">
      <div class="col-6">
        <label class="form-label">Date — التاريخ <span class="text-muted fw-normal" style="font-size:.6rem">(Gregorian)</span></label>
        <input type="date" class="form-control" name="departure_date" value="{{ pilgrim.departure_date or '' }}" min="2025-01-01" max="2050-12-31">
      </div>
      <div class="col-6">
        <label class="form-label">Time — الوقت <span class="text-muted fw-normal" style="font-size:.6rem">(24h)</span></label>
        <input type="time" class="form-control" name="departure_time" value="{{ pilgrim.departure_time or '' }}" step="60">
      </div>
    </div>
    <div class="mb-3">
      <label class="form-label">Flight — رقم الرحلة</label>
      <input type="text" class="form-control" name="flight_number" value="{{ pilgrim.flight_number or '' }}" placeholder="e.g. XY123">
    </div>
    <div class="mb-4">
      <label class="form-label">Location — مكان المغادرة</label>
      <select class="form-select" name="departure_location">
        <option value="">— Select —</option>
        {% for val,label in [('Jeddah Airport (KAIA)','Jeddah Airport (KAIA)'),('Medina Airport','Medina Airport'),('Land Border','Land Border')] %}
        <option value="{{ val }}" {{ 'selected' if pilgrim.departure_location == val }}>{{ label }}</option>
        {% endfor %}
      </select>
    </div>
    <button type="submit" class="btn btn-primary w-100"><i class="bi bi-check-lg me-2"></i>Save — حفظ</button>
  </form>
</div></div>
<footer>Travelers Ghana — مسافري غانا</footer>
</body></html>"""


def cors_ok(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    return resp


# ── PWA ──

@app.route("/manifest.json")
def manifest():
    return {
        "name": "Travelers Ghana",
        "short_name": "TravGhana",
        "description": "Pilgrim Registration & Ticket Information System",
        "start_url": "/login",
        "display": "standalone",
        "background_color": "#1a5632",
        "theme_color": "#1a5632",
        "orientation": "portrait",
        "icons": [
            {"src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 192 192'%3E%3Crect width='192' height='192' rx='32' fill='%231a5632'/%3E%3Ctext x='96' y='140' text-anchor='middle' font-size='120' fill='%23c9a227'%3E✈%3C/text%3E%3C/svg%3E", "sizes": "192x192", "type": "image/svg+xml"},
            {"src": "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 512 512'%3E%3Crect width='512' height='512' rx='64' fill='%231a5632'/%3E%3Ctext x='256' y='370' text-anchor='middle' font-size='300' fill='%23c9a227'%3E✈%3C/text%3E%3C/svg%3E", "sizes": "512x512", "type": "image/svg+xml", "purpose": "any maskable"}
        ]
    }


@app.route("/service-worker.js")
def service_worker():
    return Response("self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',()=>self.clients.claim());self.addEventListener('fetch',()=>{});", mimetype="application/javascript")


# ── Routes ──

@app.route("/", methods=["GET"])
def public_page():
    return redirect("/login")


@app.route("/form")
def form_page():
    if not session.get("user_id") and not session.get("admin"):
        return redirect("/login?next=/form")
    return PUBLIC_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/extract_preview", methods=["POST", "OPTIONS"])
def extract_preview():
    if request.method == "OPTIONS": return cors_ok(make_response())
    if "file" not in request.files: return cors_ok(jsonify({"error": "No file"})), 400
    f = request.files["file"]
    data = process_file_bytes(f.read(), f.filename or "file.pdf")
    return cors_ok(jsonify(data))


@app.route("/api/submit", methods=["POST", "OPTIONS"])
def api_submit():
    if request.method == "OPTIONS": return cors_ok(make_response())
    name = request.form.get("name", "").strip()
    passport = request.form.get("passport", "").strip()
    if not passport: return cors_ok(jsonify({"error": "fill_fields"})), 400
    if passport_exists(passport): return cors_ok(jsonify({"duplicate": True, "error": "passport_exists"})), 409

    ticket_bytes = ticket_name = passport_bytes = passport_name = None
    if "file_ticket" in request.files and request.files["file_ticket"].filename:
        f = request.files["file_ticket"]; ticket_bytes = f.read(); ticket_name = f.filename
    if "file_passport" in request.files and request.files["file_passport"].filename:
        f = request.files["file_passport"]; passport_bytes = f.read(); passport_name = f.filename

    result = handle_submission(ticket_bytes, ticket_name, passport_bytes, passport_name, name, passport,
        departure_date=request.form.get("departure_date", "").strip(),
        departure_time=request.form.get("departure_time", "").strip(),
        flight_number=request.form.get("flight_number", "").strip(),
        departure_location=request.form.get("departure_location", "").strip(),
        declaration=request.form.get("declaration", "").strip())
    if "error" in result: return cors_ok(jsonify(result)), 500
    return cors_ok(jsonify(result))


@app.route("/admin", methods=["GET", "POST"])
def admin():
    lang = request.args.get("lang", "ar")
    L = {"ar": {"admin_title":"👑 Admin Panel","admin_login":"🔐 Admin Login","admin_password":"Password","login_btn":"Login","search_placeholder":"بحث بالاسم أو الجواز أو الرحلة","total_pilgrims":"Total Pilgrims","total_flights":"Flights","total_airlines":"Airlines","web_submissions":"Web","all_submissions":"All Submissions","source":"Src","telegram":"Telegram","web":"Web","name":"Name","passport":"Passport","flight":"Flight","departure_time":"Time","departure_location":"Location","date":"Date","actions":"","confirm_delete":"Are you sure?","no_data":"No data"},"en": {"admin_title":"👑 Admin Panel","admin_login":"🔐 Admin Login","admin_password":"Password","login_btn":"Login","search_placeholder":"Search name - passport - flight","total_pilgrims":"Total Pilgrims","total_flights":"Flights","total_airlines":"Airlines","web_submissions":"Web","all_submissions":"All Submissions","source":"Src","telegram":"Telegram","web":"Web","name":"Name","passport":"Passport","flight":"Flight","departure_time":"Time","departure_location":"Location","date":"Date","actions":"","confirm_delete":"Are you sure?","no_data":"No data"}}[lang]
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD: session["admin"] = True
        else: return render_template_string(LOGIN_HTML, lang=lang, L=L, error="❌ " + ("Wrong password" if lang == "en" else "كلمة المرور خطأ"))
    if not session.get("admin"): return render_template_string(LOGIN_HTML, lang=lang, L=L, error="")

    query = request.args.get("q", "")
    conn = get_db()
    stats = {"total": conn.execute("SELECT COUNT(*) as c FROM pilgrims").fetchone()["c"],
             "flights": conn.execute("SELECT COUNT(DISTINCT flight_number) as c FROM pilgrims WHERE flight_number != ''").fetchone()["c"],
             "airlines": conn.execute("SELECT COUNT(DISTINCT airline) as c FROM pilgrims WHERE airline != ''").fetchone()["c"],
             "web": conn.execute("SELECT COUNT(*) as c FROM pilgrims WHERE user_id = 0").fetchone()["c"]}
    if query:
        rows = conn.execute("SELECT * FROM pilgrims WHERE name LIKE ? OR passport LIKE ? OR flight_number LIKE ? ORDER BY created_at DESC LIMIT 500", (f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pilgrims ORDER BY created_at DESC LIMIT 500").fetchall()
    conn.close()
    return render_template_string(ADMIN_HTML, lang=lang, L=L, stats=stats, pilgrims=[dict(r) for r in rows], query=query)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/admin")


@app.route("/admin/delete/<int:pid>", methods=["POST"])
def admin_delete(pid):
    if not session.get("admin"): return redirect("/admin")
    conn = get_db(); conn.execute("DELETE FROM pilgrims WHERE id = ?", (pid,)); conn.commit(); conn.close()
    return redirect("/admin")


@app.route("/admin/export_csv")
def admin_export_csv():
    if not session.get("admin"): return redirect("/admin")
    conn = get_db()
    rows = conn.execute("SELECT name, passport, flight_number, departure_time, departure_location, created_at, CASE WHEN user_id=0 THEN 'web' ELSE 'telegram' END as source FROM pilgrims ORDER BY created_at DESC").fetchall()
    conn.close()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["Name","Passport","Flight","Departure Time","Departure Location","Created","Source"])
    for r in rows: w.writerow([r["name"],r["passport"],r["flight_number"],r["departure_time"],r["departure_location"],r["created_at"],r["source"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition":"attachment;filename=pilgrims.csv"})


@app.route("/api/check_passport", methods=["GET", "OPTIONS"])
def api_check_passport():
    if request.method == "OPTIONS": return cors_ok(make_response())
    return cors_ok(jsonify({"exists": passport_exists(request.args.get("passport",""))}))


@app.route("/admin/export_xlsx")
def admin_export_xlsx():
    if not session.get("admin"): return redirect("/admin")
    conn = get_db()
    rows = conn.execute("SELECT name, passport, flight_number, departure_time, departure_location, created_at FROM pilgrims ORDER BY created_at DESC").fetchall()
    conn.close()
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Pilgrims"
    ws.append(["Name","Passport","Flight","Departure Time","Departure Location","Created"])
    for r in rows: ws.append([r["name"],r["passport"],r["flight_number"],r["departure_time"],r["departure_location"],r["created_at"]])
    out = io.BytesIO(); wb.save(out); out.seek(0)
    return Response(out.getvalue(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition":"attachment;filename=pilgrims.xlsx"})


@app.route("/api/update_status/<int:pid>", methods=["POST"])
def api_update_status(pid):
    if not session.get("admin"): return cors_ok(jsonify({"error":"unauthorized"})), 401
    status = request.form.get("status","").strip()
    if status not in [s[0] for s in STATUS_OPTIONS]: return cors_ok(jsonify({"error":"invalid_status"})), 400
    ok = update_status(pid, status, session.get("username","admin"))
    return cors_ok(jsonify({"success": ok}))


@app.route("/edit/<int:pid>", methods=["GET", "POST"])
def edit_request(pid):
    p = get_pilgrim(pid)
    if not p: return "⚠️ Request not found", 404
    if p.get("status") and p["status"] not in ("", "pending"):
        return "⚠️ This request has been processed and can no longer be edited", 403
    if request.method == "POST":
        passport = request.form.get("passport","").strip()
        if p["passport"] != passport: return render_template_string(EDIT_HTML, pilgrim=p, error="❌ Passport doesn't match this request", success="")
        name = request.form.get("name","").strip()
        dd = request.form.get("departure_date","").strip()
        dt = request.form.get("departure_time","").strip()
        fn = request.form.get("flight_number","").strip()
        dl = request.form.get("departure_location","").strip()
        conn = get_db()
        conn.execute("UPDATE pilgrims SET name=?, departure_date=?, departure_time=?, flight_number=?, departure_location=? WHERE id=?", (name,dd,dt,fn,dl,pid))
        conn.commit(); conn.close()
        return render_template_string(EDIT_HTML, pilgrim=p, success="✅ Updated — تم التحديث بنجاح", error="")
    return render_template_string(EDIT_HTML, pilgrim=p, error="", success="")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    next_url = request.args.get("next", "")
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","").strip()
        next_url = request.form.get("next", next_url)
        user = verify_user(username, password)
        if user:
            session["user_id"] = user["id"]; session["username"] = user["username"]; session["role"] = user["role"]
            return redirect(next_url or "/organizer")
        elif username == "admin" and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect(next_url or "/admin")
        else:
            error = "❌ Invalid username or password — اسم المستخدم أو كلمة المرور خطأ"
    return render_template_string("""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Login — Travelers Ghana</title>
"""+PWA_TAGS+"""<link rel="preconnect" href="https://fonts.googleapis.com">
<link href=\""""+FONT_URL+"""\" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{min-height:100vh;background:linear-gradient(135deg,#1a5632 0%,#0d3d1e 50%,#0a2a15 100%);display:flex;align-items:center;font-family:'Inter',sans-serif;position:relative}
body::before{content:'';position:fixed;inset:0;background-image:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23c9a227' fill-opacity='0.04'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");pointer-events:none;z-index:0}
.card{border:none;border-radius:20px;box-shadow:0 25px 80px rgba(0,0,0,.4);overflow:hidden;position:relative;z-index:1;border-top:4px solid #c9a227}
.card-body{padding:2.75rem 2.25rem}
h2{font-family:'Playfair Display',Georgia,serif;font-weight:800;color:#1a5632;font-size:1.7rem}
.form-label{font-size:.78rem;text-transform:uppercase;letter-spacing:.5px;color:#6b7280;margin-bottom:.3rem}
.form-control{border-radius:10px;padding:.75rem 1rem;border:2px solid #e5e7eb;font-size:.9rem;transition:border-color .25s,box-shadow .25s}
.form-control:focus{border-color:#c9a227;box-shadow:0 0 0 4px rgba(201,162,39,.12)}
.btn-primary{background:linear-gradient(135deg,#1a5632,#0d3d1e);border:none;border-radius:50px;padding:.8rem;font-weight:600;transition:all .3s}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(26,86,50,.35)}
.gold-line{width:36px;height:2px;background:linear-gradient(90deg,transparent,#c9a227,transparent);margin:.6rem auto 1rem;border-radius:2px}
.alert-custom{background:#fef2f2;border:1px solid #fecaca;border-left:4px solid #dc2626;border-radius:8px;padding:.6rem .9rem;font-size:.8rem;color:#991b1b;margin-bottom:1.25rem;font-weight:500}
.footer-text{margin-top:1.75rem;padding-top:1rem;border-top:1px solid #f3f4f6;font-size:.7rem;color:rgba(255,255,255,.4)}
</style></head><body>
<div class="container"><div class="row justify-content-center"><div class="col-md-5">
<div class="card"><div class="card-body text-center">
<div style="font-size:2.25rem;margin-bottom:.15rem">✈️🕋</div>
<h2>Welcome</h2>
<p class="text-muted" style="font-family:'Tajawal',sans-serif;font-size:.85rem;margin-bottom:.15rem">مرحباً</p>
<div class="gold-line"></div>
{% if error %}<div class="alert-custom">{{ error }}</div>{% endif %}
<form method="post">
<input type="hidden" name="next" value="{{ next_url }}">
<div class="mb-4 text-start">
<label class="form-label fw-semibold">Username — اسم المستخدم</label>
<input type="text" name="username" class="form-control" required autofocus placeholder="Enter your username">
</div>
<div class="mb-4 text-start">
<label class="form-label fw-semibold">Password — كلمة المرور</label>
<input type="password" name="password" class="form-control" required placeholder="Enter your password">
</div>
<button type="submit" class="btn btn-primary w-100">Login — دخول</button>
</form>
<div class="footer-text">Travelers Ghana — مسافري غانا</div>
</div></div></div></div></div></body></html>""", error=error, next_url=next_url)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


@app.route("/organizer")
def organizer():
    if not session.get("user_id"): return redirect("/login")
    username = session.get("username", ""); role = session.get("role", "")
    conn = get_db(); query = request.args.get("q", "")
    if query:
        rows = conn.execute("SELECT * FROM pilgrims WHERE name LIKE ? OR passport LIKE ? OR flight_number LIKE ? ORDER BY created_at DESC LIMIT 500", (f"%{query}%", f"%{query}%", f"%{query}%")).fetchall()
    else:
        rows = conn.execute("SELECT * FROM pilgrims ORDER BY created_at DESC LIMIT 500").fetchall()
    total = conn.execute("SELECT COUNT(*) as c FROM pilgrims").fetchone()["c"]; conn.close()
    return render_template_string("""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Organizer — Travelers Ghana</title>
"""+PWA_TAGS+"""<link rel="preconnect" href="https://fonts.googleapis.com">
<link href=\""""+FONT_URL+"""\" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
"""+SHARED_CSS+"""
.stats-number{font-size:1.8rem;font-weight:800;color:var(--p);line-height:1}
.stats-label{color:#888;font-size:.78rem;font-weight:500}
.search-box{border-radius:50px;padding:.5rem 1.2rem;border:1.5px solid #e5e7eb;background:#fafafa;font-size:.85rem}
.search-box:focus{border-color:var(--g);box-shadow:0 0 0 4px rgba(201,162,39,.1);background:#fff}
</style></head><body>

<nav class="navbar navbar-expand-lg navbar-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="/organizer"><i class="bi bi-person-badge me-2"></i>{{ username }}</a>
    <div class="d-flex gap-2 align-items-center">
      <a href="/" class="btn btn-sm btn-outline-light py-1 px-2"><i class="bi bi-house"></i></a>
      <a href="/form" class="btn btn-sm btn-light fw-semibold py-1"><i class="bi bi-plus-circle me-1"></i>New</a>
      <span class="badge bg-white bg-opacity-25 px-2 py-1 fw-medium" style="font-size:.7rem">{{ role }}</span>
      <a href="/logout" class="btn btn-sm btn-outline-light py-1"><i class="bi bi-box-arrow-right"></i></a>
    </div>
  </div>
</nav>

<div class="container-fluid py-4 px-lg-4">
  <div class="row g-3 mb-4">
    <div class="col-4"><div class="card p-3 text-center">
      <div class="stats-number">{{ total }}</div>
      <div class="stats-label">Total</div>
    </div></div>
    <div class="col-4"><div class="card p-3 text-center">
      <div class="stats-number">{{ pilgrims|length }}</div>
      <div class="stats-label">Displayed</div>
    </div></div>
    <div class="col-4"><div class="card p-3 text-center">
      <div class="stats-number" style="font-size:1rem;text-transform:capitalize">{{ role }}</div>
      <div class="stats-label">Role</div>
    </div></div>
  </div>

  <div class="card">
    <div class="card-header"><i class="bi bi-table me-2"></i>All Submissions</div>
    <div class="card-body p-3">
      <form class="mb-3" method="get">
        <div class="input-group">
          <input type="text" name="q" class="form-control search-box border-end-0" placeholder="Search name, passport, flight" value="{{ query }}">
          <button class="btn btn-primary rounded-end-pill px-3" type="submit" style="background:var(--p);border-color:var(--p)"><i class="bi bi-search"></i></button>
        </div>
      </form>
      <div class="table-responsive" style="border-radius:12px;border:1px solid #f0f0f0">
        <table class="table table-hover align-middle mb-0">
          <thead><tr>
            <th>🔐</th><th>Name</th><th>Passport</th><th>Flight</th><th>Time</th><th>Location</th><th>Status</th><th>Date</th>
          </tr></thead>
          <tbody>
            {% set sm={'processing':'Processing','under_action':'Under Action','completed':'Completed','departed':'Departed'} %}
            {% set sc={'processing':'bg-warning-subtle text-warning-emphasis','under_action':'bg-info-subtle text-info-emphasis','completed':'bg-success-subtle text-success-emphasis','departed':'bg-secondary-subtle text-secondary-emphasis'} %}
            {% for p in pilgrims %}
            <tr>
              <td><span class="secret-badge">TG{{ '%04d'|format(p.id) }}</span></td>
              <td><strong>{{ p.name }}</strong></td>
              <td><span class="passport-text">{{ p.passport }}</span></td>
              <td>{% if p.flight_number %}<span class="badge bg-secondary-subtle text-secondary-emphasis fw-medium">{{ p.flight_number }}</span>{% endif %}</td>
              <td class="small text-muted">{{ p.departure_time }}</td>
              <td class="small text-muted">{{ p.departure_location }}</td>
              <td>{% if p.status and p.status in sm %}<span class="badge {{ sc[p.status] }} rounded-pill" style="font-size:.62rem">{{ sm[p.status] }}</span>{% else %}<span class="text-muted small">—</span>{% endif %}</td>
              <td class="small text-muted">{{ p.created_at[:10] }}</td>
            </tr>
            {% else %}
            <tr><td colspan="8" class="text-center text-muted py-5">No submissions</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
<footer>Travelers Ghana — مسافري غانا</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body></html>""", username=username, role=role, pilgrims=[dict(r) for r in rows], total=total, query=query)


@app.route("/admin/users")
def admin_users():
    if not session.get("admin"): return redirect("/admin")
    users = get_all_users(); total_count = count_users()
    return render_template_string("""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>User Management — Travelers Ghana</title>
"""+PWA_TAGS+"""<link rel="preconnect" href="https://fonts.googleapis.com">
<link href=\""""+FONT_URL+"""\" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
"""+SHARED_CSS+"""
.form-control{border-radius:10px;padding:.6rem .85rem;border:1.5px solid #e2e2e2;font-size:.85rem;transition:all .25s}
.form-control:focus{border-color:var(--g);box-shadow:0 0 0 4px rgba(201,162,39,.1)}
.btn-primary{background:linear-gradient(135deg,var(--p),var(--pd));border:none;border-radius:50px;font-weight:600;padding:.55rem;font-size:.82rem}
.btn-primary:hover{box-shadow:0 4px 16px rgba(26,86,50,.2)}
</style></head><body>

<nav class="navbar navbar-expand-lg navbar-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="/admin"><i class="bi bi-shield-lock me-2"></i>Users</a>
    <div class="d-flex gap-2">
      <a href="/" class="btn btn-sm btn-outline-light py-1 px-2"><i class="bi bi-house"></i></a>
      <a href="/admin" class="btn btn-sm btn-outline-light py-1"><i class="bi bi-arrow-left me-1"></i>Back</a>
    </div>
  </div>
</nav>

<div class="container-fluid py-4 px-lg-4">
  <div class="row g-4">
    <div class="col-lg-4">
      <div class="card"><div class="card-header"><i class="bi bi-person-plus me-2"></i>Add User</div>
      <div class="card-body p-4">
        <form method="post" action="/admin/users/create">
          <div class="mb-3"><label class="form-label fw-semibold">Username</label>
          <input type="text" name="username" class="form-control" required placeholder="Username"></div>
          <div class="mb-3"><label class="form-label fw-semibold">Password</label>
          <input type="text" name="password" class="form-control" required placeholder="Password"></div>
          <div class="mb-4"><label class="form-label fw-semibold">Role</label>
          <select name="role" class="form-control">
            <option value="organizer">Organizer</option>
            <option value="viewer">Viewer</option>
          </select></div>
          <button type="submit" class="btn btn-primary w-100"><i class="bi bi-plus-circle me-2"></i>Create</button>
        </form>
      </div></div>
    </div>
    <div class="col-lg-8">
      <div class="card"><div class="card-header"><i class="bi bi-people me-2"></i>Users <span class="fw-normal text-muted">({{ total_count }})</span></div>
      <div class="card-body p-3">
        <div class="table-responsive" style="border-radius:12px;border:1px solid #f0f0f0">
          <table class="table table-hover mb-0">
            <thead><tr><th>ID</th><th>Username</th><th>Role</th><th>Created</th><th></th></tr></thead>
            <tbody>
              {% for u in users %}
              <tr>
                <td class="text-muted small">{{ u.id }}</td>
                <td><strong>{{ u.username }}</strong></td>
                <td><span class="badge bg-{{ 'success' if u.role == 'organizer' else 'info' }} rounded-pill">{{ u.role }}</span></td>
                <td class="small text-muted">{{ u.created_at[:10] }}</td>
                <td>
                  <form method="post" action="/admin/users/delete/{{ u.id }}" onsubmit="return confirm('Delete user?')">
                    <button class="btn btn-outline-danger btn-sm border-0 px-1"><i class="bi bi-trash3"></i></button>
                  </form>
                </td>
              </tr>
              {% else %}
              <tr><td colspan="5" class="text-center text-muted py-5">No users</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div></div>
    </div>
  </div>
</div>
</body></html>""", users=users, total_count=total_count)


@app.route("/admin/users/create", methods=["POST"])
def admin_users_create():
    if not session.get("admin"): return redirect("/admin")
    username = request.form.get("username","").strip()
    password = request.form.get("password","").strip()
    role = request.form.get("role","organizer")
    if username and password: uid = create_user(username, password, role)
    return redirect("/admin/users")


@app.route("/admin/users/delete/<int:uid>", methods=["POST"])
def admin_users_delete(uid):
    if not session.get("admin"): return redirect("/admin")
    delete_user(uid)
    return redirect("/admin/users")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🌍 Server running on http://0.0.0.0:{port}")
    print(f"👑 Admin panel: http://localhost:{port}/admin")
    print(f"📋 Organizer login: http://localhost:{port}/login")
    app.run(host="0.0.0.0", port=port, debug=True)
