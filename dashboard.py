import os
import io
import csv
import json
import hashlib
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
from db import get_db, init_db, save_extraction, passport_exists

ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
init_db()

LANG = {
    "ar": {
        "admin_title": "👑 Admin Panel - Travelers Ghana",
        "admin_login": "🔐 Admin Login",
        "admin_password": "Password",
        "login_btn": "Login",
        "logout_btn": "Logout",
        "search_placeholder": "Search name - passport - flight",
        "total_pilgrims": "Total Pilgrims",
        "total_flights": "Flights",
        "total_airlines": "Airlines",
        "download_csv": "Download CSV",
        "no_data": "No data",
        "all_submissions": "All Submissions",
        "source": "Source",
        "telegram": "Telegram",
        "web": "Web",
        "date": "Date",
        "actions": "Actions",
        "confirm_delete": "Are you sure?",
        "deleted": "✅ Deleted",
        "passport": "Passport",
        "name": "Name",
        "flight": "Flight",
        "ticket": "Ticket",
        "seat": "Seat",
        "airline": "Airline",
        "web_submissions": "Web Submissions",
        "public_link": "📌 Public Link",
    },
    "en": {
        "admin_title": "👑 Admin Panel - Travelers Ghana",
        "admin_login": "🔐 Admin Login",
        "admin_password": "Password",
        "login_btn": "Login",
        "logout_btn": "Logout",
        "search_placeholder": "Search name - passport - flight",
        "total_pilgrims": "Total Pilgrims",
        "total_flights": "Flights",
        "total_airlines": "Airlines",
        "download_csv": "Download CSV",
        "no_data": "No data",
        "all_submissions": "All Submissions",
        "source": "Source",
        "telegram": "Telegram",
        "web": "Web",
        "date": "Date",
        "actions": "Actions",
        "confirm_delete": "Are you sure?",
        "deleted": "✅ Deleted",
        "passport": "Passport",
        "name": "Name",
        "flight": "Flight",
        "ticket": "Ticket",
        "seat": "Seat",
        "airline": "Airline",
        "web_submissions": "Web Submissions",
        "public_link": "📌 Public Link",
    },
}


def notify_admin(name, passport, flight=""):
    if not BOT_TOKEN or not ADMIN_CHAT_ID:
        return
    msg = (
        f"🆕 *طلب جديد / New Submission*\n"
        f"👤 {name}\n"
        f"🛂 {passport}\n"
        f"✈️ {flight or '—'}"
    )
    try:
        http.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": ADMIN_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=5,
        )
    except:
        pass


def process_file_bytes(file_bytes, file_name):
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTS:
        return {"error": "Unsupported file type"}
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
        return {"error": str(e)}
    data = extract_data(text)
    data["qr"] = [str(q) for q in qr_data[:3]]
    return data


def handle_submission(ticket_bytes, ticket_name, passport_bytes, passport_name, name, passport):
    ticket_data = process_file_bytes(ticket_bytes, ticket_name) if ticket_bytes else {"pilgrims": [], "tickets": {}, "raw_text": ""}
    passport_data = process_file_bytes(passport_bytes, passport_name) if passport_bytes else {"pilgrims": [], "tickets": {}, "raw_text": ""}

    if "error" in ticket_data:
        return {"error": ticket_data["error"]}
    if "error" in passport_data:
        return {"error": passport_data["error"]}

    pilgrims = ticket_data.get("pilgrims", [])
    tickets = ticket_data.get("tickets", {})
    pp_pilgrims = passport_data.get("pilgrims", [])
    pp_tickets = passport_data.get("tickets", {})

    if not pilgrims and pp_pilgrims:
        pilgrims = pp_pilgrims
    if pp_tickets.get("passport") and not tickets.get("passport"):
        tickets["passport"] = pp_tickets.get("passport")

    if name:
        if not pilgrims:
            pilgrims = [{"name": name}]
        else:
            pilgrims[0]["name"] = name
    if passport:
        tickets["passport"] = passport

    is_jed = tickets.get("is_jed", False) or pp_tickets.get("is_jed", False)

    if is_jed:
        kept = ["flight_number", "departure_time", "flight_date", "date", "route", "airline", "origin", "passport", "is_jed"]
        tickets = {k: tickets[k] for k in kept if k in tickets}

    raw = ticket_data.get("raw_text", "") + "\n---\n" + passport_data.get("raw_text", "")
    fname = ticket_name or passport_name or "file"

    try:
        save_extraction(
            user_id=0, username="web", file_name=fname,
            file_type=Path(fname).suffix.lower(),
            pilgrims=pilgrims, tickets=tickets, raw_text=raw,
        )
    except Exception as e:
        return {"error": str(e)}

    notify_admin(name, tickets.get("passport", ""), tickets.get("flight_number", ""))
    return {"success": True, "pilgrims": pilgrims, "tickets": tickets, "is_jed": is_jed}


# ────────────────────── Public HTML (static, no Jinja2) ──────────────────────

PUBLIC_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Travelers Ghana - Submit Request</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
*{font-family:'Inter','Segoe UI',sans-serif}
body{background:linear-gradient(135deg,#f5f7fa 0%,#c3cfe2 100%);min-height:100vh}
.header{background:linear-gradient(135deg,#1a5632 0%,#2e7d32 100%);color:#fff;padding:1.5rem 0}
.header h1{font-weight:800;font-size:1.5rem;margin:0}
.header p{opacity:.85;margin:0;font-size:.9rem}
.header-icon{font-size:2rem;margin-right:.8rem}
.card{border:none;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);margin-top:-1.5rem}
.card-header{background:transparent;border-bottom:2px solid #e8f5e9;padding:1rem 1.25rem;font-weight:700}
.card-body{padding:1.25rem}
.form-control{border-radius:10px;padding:.6rem .9rem;border:2px solid #e0e0e0}
.form-control:focus{border-color:#1a5632;box-shadow:0 0 0 3px rgba(26,86,50,.15)}
.btn-primary{background:#1a5632;border:none;border-radius:10px;padding:.65rem 1.5rem;font-weight:700}
.btn-primary:hover{background:#0d3d1e}
.upload-area{border:2px dashed #ccc;border-radius:12px;padding:1.2rem;text-align:center;cursor:pointer;transition:.2s;margin-bottom:0}
.upload-area:hover{border-color:#1a5632;background:#e8f5e9}
.upload-area i{font-size:2rem;color:#999}
.upload-area p{color:#999;margin:.3rem 0 0;font-size:.9rem}
.upload-card{background:#f8f9fa;border-radius:12px;padding:1rem;height:100%}
.upload-card .badge{font-size:.75rem}
.result-card{background:#fff8e1;border-radius:10px;padding:.8rem;margin-bottom:.8rem}
.result-item{padding:.15rem 0;font-size:.9rem}
.result-label{font-weight:600;color:#555;display:inline-block;min-width:130px}
.result-value{color:#222;font-weight:500}
.alert{border-radius:10px;font-size:.9rem}
.admin-link{position:fixed;top:.8rem;right:.8rem;z-index:999;font-size:.8rem}
footer{text-align:center;padding:1.5rem;color:#999;font-size:.8rem}
.upload-label{font-weight:600;font-size:.9rem;margin-bottom:.4rem;display:block}
.upload-label small{font-weight:400;color:#888}
</style>
</head>
<body>

<a href="/admin" class="btn btn-light btn-sm admin-link shadow-sm"><i class="bi bi-shield-lock"></i> Admin</a>

<div class="header">
  <div class="container">
    <div class="d-flex align-items-center">
      <span class="header-icon">✈️🕋</span>
      <div>
        <h1>Travelers Ghana</h1>
        <p>Upload your ticket and passport to auto-extract your information</p>
      </div>
    </div>
  </div>
</div>

<div class="container py-4">
  <div class="card">
    <div class="card-header">
      <i class="bi bi-file-earmark-plus"></i> New Request
    </div>
    <div class="card-body">

      <div id="alertBox" class="alert d-none"></div>

      <form id="submitForm" enctype="multipart/form-data">

        <div class="row mb-3">
          <div class="col-md-6 mb-3 mb-md-0">
            <div class="upload-card">
              <span class="upload-label">📎 Ticket <small>(PDF or image)</small></span>
              <div class="upload-area" id="ticketUploadArea" onclick="document.getElementById('ticketFile').click()">
                <i class="bi bi-file-earmark-text"></i>
                <p id="ticketUploadText">Upload ticket file</p>
                <small class="text-muted">PDF, JPG, PNG</small>
              </div>
              <input type="file" id="ticketFile" name="file_ticket" accept=".pdf,.jpg,.jpeg,.png" class="d-none" onchange="onTicketSelect(this)">
              <div id="ticketPreview" class="result-card mt-2 d-none">
                <div class="fw-bold small mb-1"><i class="bi bi-robot"></i> Extracted Ticket Info</div>
                <div id="ticketFields"></div>
              </div>
            </div>
          </div>
          <div class="col-md-6">
            <div class="upload-card">
              <span class="upload-label">🛂 Passport / Nusuk Card <small>(image preferred)</small></span>
              <div class="upload-area" id="passportUploadArea" onclick="document.getElementById('passportFile').click()">
                <i class="bi bi-person-badge"></i>
                <p id="passportUploadText">Upload passport or Nusuk card</p>
                <small class="text-muted">JPG, PNG, PDF</small>
              </div>
              <input type="file" id="passportFile" name="file_passport" accept=".pdf,.jpg,.jpeg,.png" class="d-none" onchange="onPassportSelect(this)">
              <div id="passportPreview" class="result-card mt-2 d-none">
                <div class="fw-bold small mb-1"><i class="bi bi-robot"></i> Extracted Info</div>
                <div id="passportFields"></div>
              </div>
            </div>
          </div>
        </div>

        <div class="row g-2 mb-3">
          <div class="col-md-6">
            <label class="form-label fw-bold small mb-1">Pilgrim Name <span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="pilgrimName" name="name" required placeholder="Full name">
          </div>
          <div class="col-md-6">
            <label class="form-label fw-bold small mb-1">Passport Number <span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="passportInput" name="passport" required placeholder="Passport number" onblur="checkPassport(this.value)">
            <small class="text-muted" id="passportStatus"></small>
          </div>
        </div>

        <button type="submit" class="btn btn-primary w-100" id="submitBtn">
          <i class="bi bi-send"></i> Submit Request
        </button>
      </form>

      <div class="text-center mt-2">
        <small class="text-muted"><i class="bi bi-shield-check"></i> Your data is protected</small>
      </div>

    </div>
  </div>
</div>

<footer>✈️🕋 Travelers Ghana</footer>

<script>
let ticketData = {};
let passportData = {};

function showAlert(msg, type) {
  const box = document.getElementById('alertBox');
  const icon = type === 'error' ? 'bi-exclamation-triangle-fill' : 'bi-check-circle-fill';
  box.className = 'alert alert-' + (type === 'error' ? 'danger' : 'success') + ' d-flex align-items-center';
  box.innerHTML = '<i class="bi ' + icon + ' me-2"></i> ' + msg;
  box.classList.remove('d-none');
  setTimeout(() => { box.className = 'alert d-none'; }, 6000);
}

async function previewFile(fileInput, previewId, fieldsId, uploadTextId, isTicket) {
  if (!fileInput.files.length) return;
  document.getElementById(uploadTextId).textContent = fileInput.files[0].name;

  const fd = new FormData();
  fd.append('file', fileInput.files[0]);

  document.getElementById(previewId).classList.remove('d-none');
  document.getElementById(fieldsId).innerHTML = '<div class="text-center py-2"><div class="spinner-border spinner-border-sm text-primary" role="status"></div><small class="text-muted ms-1">Extracting...</small></div>';

  try {
    const res = await fetch('/extract_preview', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.error) {
      document.getElementById(fieldsId).innerHTML = '<small class="text-danger">' + data.error + '</small>';
      return;
    }

    if (isTicket) ticketData = data;
    else passportData = data;

    let html = '';
    if (isTicket) {
      const t = data.tickets || {};
      if (t.flight_number) html += '<div class="result-item"><span class="result-label">✈️ Flight:</span><span class="result-value">' + t.flight_number + '</span></div>';
      if (t.departure_time) html += '<div class="result-item"><span class="result-label">⏰ Departure:</span><span class="result-value">' + t.departure_time + '</span></div>';
      if (t.flight_date || t.date) html += '<div class="result-item"><span class="result-label">📅 Date:</span><span class="result-value">' + (t.flight_date || t.date) + '</span></div>';
      if (t.route) html += '<div class="result-item"><span class="result-label">🛤️ Route:</span><span class="result-value">' + t.route + '</span></div>';
      if (t.airline) html += '<div class="result-item"><span class="result-label">🏢 Airline:</span><span class="result-value">' + t.airline + '</span></div>';
      if (t.origin) html += '<div class="result-item"><span class="result-label">📍 From:</span><span class="result-value">' + t.origin + '</span></div>';
      if (t.is_jed) html += '<div class="result-item"><span class="badge bg-success">✈️ JED Flight</span></div>';
      if (data.pilgrims && data.pilgrims.length) {
        html += '<div class="result-item"><span class="result-label">👤 Name:</span><span class="result-value">' + data.pilgrims[0].name + '</span></div>';
        if (!document.getElementById('pilgrimName').value)
          document.getElementById('pilgrimName').value = data.pilgrims[0].name;
      }
      if (!html) html = '<small class="text-muted">No ticket data found</small>';
    } else {
      const t = data.tickets || {};
      if (data.pilgrims && data.pilgrims.length) {
        html += '<div class="result-item"><span class="result-label">👤 Name:</span><span class="result-value">' + data.pilgrims[0].name + '</span></div>';
        if (!document.getElementById('pilgrimName').value)
          document.getElementById('pilgrimName').value = data.pilgrims[0].name;
      }
      if (t.passport || t.hid) {
        const pp = t.passport || t.hid;
        html += '<div class="result-item"><span class="result-label">🛂 Passport:</span><span class="result-value">' + pp + '</span></div>';
        if (!document.getElementById('passportInput').value)
          document.getElementById('passportInput').value = pp;
        checkPassport(pp);
      }
      if (t.hid && t.hid !== t.passport) {
        html += '<div class="result-item"><span class="result-label">🆔 HID:</span><span class="result-value">' + t.hid + '</span></div>';
      }
      if (!html) html = '<small class="text-muted">No data extracted</small>';
    }
    document.getElementById(fieldsId).innerHTML = html;
  } catch(e) {
    document.getElementById(fieldsId).innerHTML = '<small class="text-danger">Extraction failed</small>';
  }
}

function onTicketSelect(input) { previewFile(input, 'ticketPreview', 'ticketFields', 'ticketUploadText', true); }
function onPassportSelect(input) { previewFile(input, 'passportPreview', 'passportFields', 'passportUploadText', false); }

async function checkPassport(val) {
  const status = document.getElementById('passportStatus');
  if (!val || val.length < 3) { status.textContent = ''; return; }
  status.textContent = 'Checking...';
  try {
    const res = await fetch('/api/check_passport?passport=' + encodeURIComponent(val));
    const data = await res.json();
    status.textContent = data.exists ? '❌ Already registered' : '✅ Available';
    status.className = data.exists ? 'text-danger' : 'text-success';
  } catch(e) { status.textContent = ''; }
}

document.getElementById('submitForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const name = document.getElementById('pilgrimName').value.trim();
  const passport = document.getElementById('passportInput').value.trim();
  const ticketFile = document.getElementById('ticketFile');
  const passportFile = document.getElementById('passportFile');

  if (!name || !passport) { showAlert('Please fill all fields', 'error'); return; }
  if (!ticketFile.files.length && !passportFile.files.length) { showAlert('Please upload at least one file', 'error'); return; }

  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processing...';

  const fd = new FormData();
  if (ticketFile.files.length) fd.append('file_ticket', ticketFile.files[0]);
  if (passportFile.files.length) fd.append('file_passport', passportFile.files[0]);
  fd.append('name', name);
  fd.append('passport', passport);

  try {
    const res = await fetch('/api/submit', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success) {
      let msg = '✅ Request submitted! We will contact you soon.';
      if (!data.is_jed) msg += ' ⚠️ Note: Flight does not depart from JED, saved as reference.';
      showAlert(msg, 'success');
      document.getElementById('pilgrimName').value = '';
      document.getElementById('passportInput').value = '';
      document.getElementById('passportStatus').textContent = '';
      ticketFile.value = ''; document.getElementById('ticketUploadText').textContent = 'Upload ticket file';
      document.getElementById('ticketPreview').classList.add('d-none');
      passportFile.value = ''; document.getElementById('passportUploadText').textContent = 'Upload passport or Nusuk card';
      document.getElementById('passportPreview').classList.add('d-none');
      ticketData = {}; passportData = {};
    } else if (data.duplicate) {
      showAlert('❌ This passport number is already registered', 'error');
    } else {
      showAlert('Error: ' + (data.error || 'Unknown'), 'error');
    }
  } catch(e) {
    showAlert('Error submitting request', 'error');
  }
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-send"></i> Submit Request';
});
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""

ADMIN_HTML = """<!DOCTYPE html>
<html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ L.admin_title }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap');
:root { --primary: #1a5632; --accent: #c9a227; }
* { font-family: 'Tajawal', 'Segoe UI', sans-serif; }
body { background: #f0f2f5; }
.navbar { background: linear-gradient(135deg, var(--primary) 0%, #2e7d32 100%) !important; padding: .8rem 1rem; }
.navbar-brand { font-weight: 900; font-size: 1.3rem; }
.stat-card { border: none; border-radius: 16px; box-shadow: 0 2px 8px rgba(0,0,0,.08); padding: 1.2rem; transition: .2s; }
.stat-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,.12); }
.stat-number { font-size: 1.8rem; font-weight: 900; }
.stat-label { color: #666; font-size: .85rem; }
.stat-icon { font-size: 2rem; }
.card { border: none; border-radius: 16px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.card-header { background: transparent; border-bottom: 2px solid #e8f5e9; font-weight: 700; }
.search-box { border-radius: 50px; padding: .5rem 1.2rem; border: 2px solid #e0e0e0; }
.search-box:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(26,86,50,.15); }
.table th { font-weight: 600; color: #444; border-top: none; background: #fafafa; }
.table-hover tbody tr:hover { background: #f5fff5; }
.badge-source { font-size: .75rem; padding: .3rem .6rem; border-radius: 50px; }
.badge-tg { background: #e3f2fd; color: #1565c0; }
.badge-web { background: #e8f5e9; color: #2e7d32; }
footer { text-align: center; padding: 2rem; color: #999; font-size: .85rem; }
.passport-text { font-family: 'Courier New', monospace; font-weight: 700; letter-spacing: 1px; }
</style>
</head>
<body>

<nav class="navbar navbar-expand-lg navbar-dark">
  <div class="container-fluid">
    <a class="navbar-brand" href="/admin"><i class="bi bi-shield-lock"></i> {{ L.admin_title }}</a>
    <div class="d-flex gap-2">
      <a href="?lang={{ 'en' if lang == 'ar' else 'ar' }}" class="btn btn-sm btn-outline-light">{{ '🇸🇦 العربية' if lang == 'ar' else '🇬🇧 English' }}</a>
      <a href="/admin/logout" class="btn btn-sm btn-outline-light"><i class="bi bi-box-arrow-right"></i></a>
    </div>
  </div>
</nav>

<div class="container-fluid py-4">

  <div class="row mb-4">
    <div class="col-md-3 mb-3">
      <div class="stat-card">
        <div class="d-flex justify-content-between">
          <div><div class="stat-number">{{ stats.total }}</div><div class="stat-label">{{ L.total_pilgrims }}</div></div>
          <div class="stat-icon"><i class="bi bi-people text-success"></i></div>
        </div>
      </div>
    </div>
    <div class="col-md-3 mb-3">
      <div class="stat-card">
        <div class="d-flex justify-content-between">
          <div><div class="stat-number">{{ stats.flights }}</div><div class="stat-label">{{ L.total_flights }}</div></div>
          <div class="stat-icon"><i class="bi bi-airplane text-primary"></i></div>
        </div>
      </div>
    </div>
    <div class="col-md-3 mb-3">
      <div class="stat-card">
        <div class="d-flex justify-content-between">
          <div><div class="stat-number">{{ stats.airlines }}</div><div class="stat-label">{{ L.total_airlines }}</div></div>
          <div class="stat-icon"><i class="bi bi-building text-warning"></i></div>
        </div>
      </div>
    </div>
    <div class="col-md-3 mb-3">
      <div class="stat-card">
        <div class="d-flex justify-content-between">
          <div><div class="stat-number">{{ stats.web }}</div><div class="stat-label">{{ L.web_submissions }}</div></div>
          <div class="stat-icon"><i class="bi bi-globe text-info"></i></div>
        </div>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
        <span><i class="bi bi-table"></i> {{ L.all_submissions }} ({{ pilgrims|length }})</span>
        <div class="d-flex gap-2">
          <a href="/admin/export_csv" class="btn btn-outline-success btn-sm"><i class="bi bi-download"></i> CSV</a>
        </div>
      </div>
    </div>
    <div class="card-body p-3">
      <form class="mb-3" method="get">
        <div class="input-group">
          <input type="text" name="q" class="form-control search-box" placeholder="{{ L.search_placeholder }}" value="{{ query }}">
          <button class="btn btn-primary" type="submit"><i class="bi bi-search"></i></button>
        </div>
      </form>

      <div class="table-responsive">
        <table class="table table-hover align-middle">
          <thead>
            <tr>
              <th>#</th>
              <th>{{ L.source }}</th>
              <th>{{ L.name }}</th>
              <th>{{ L.passport }}</th>
              <th>{{ L.flight }}</th>
              <th>{{ L.ticket }}</th>
              <th>{{ L.seat }}</th>
              <th>{{ L.airline }}</th>
              <th>{{ L.date }}</th>
              <th>{{ L.actions }}</th>
            </tr>
          </thead>
          <tbody>
            {% for p in pilgrims %}
            <tr>
              <td>{{ p.id }}</td>
              <td><span class="badge badge-source {{ 'badge-tg' if p.user_id != 0 else 'badge-web' }}">{{ '📱 ' + L.telegram if p.user_id != 0 else '🌐 ' + L.web }}</span></td>
              <td><strong>{{ p.name }}</strong></td>
              <td><span class="passport-text">{{ p.passport }}</span></td>
              <td>{% if p.flight_number %}<span class="badge bg-light text-dark">{{ p.flight_number }}</span>{% endif %}</td>
              <td class="small">{{ p.ticket_number }}</td>
              <td>{{ p.seat }}</td>
              <td>{{ p.airline }}</td>
              <td class="small text-muted">{{ p.created_at[:10] }}</td>
              <td>
                <form method="post" action="/admin/delete/{{ p.id }}" onsubmit="return confirm('{{ L.confirm_delete }}')" class="d-inline">
                  <button class="btn btn-outline-danger btn-sm"><i class="bi bi-trash"></i></button>
                </form>
              </td>
            </tr>
            {% else %}
            <tr><td colspan="10" class="text-center text-muted py-4">{{ L.no_data }}</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>

</div>

<footer>✈️🕋 Travelers Ghana &mdash; مسافري غانا</footer>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>"""

LOGIN_HTML = """<!DOCTYPE html>
<html lang="{{ lang }}" dir="{{ 'rtl' if lang == 'ar' else 'ltr' }}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ L.admin_login }}</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap');
* { font-family: 'Tajawal', sans-serif; }
body { background: linear-gradient(135deg, #1a5632 0%, #2e7d32 100%); min-height: 100vh; display: flex; align-items: center; }
.card { border: none; border-radius: 20px; box-shadow: 0 10px 40px rgba(0,0,0,.2); }
.card-header { background: transparent; border-bottom: 2px solid #e8f5e9; text-align: center; padding: 2rem 1rem 1rem; }
.card-header h2 { font-weight: 900; color: var(--primary); }
.form-control { border-radius: 12px; padding: .75rem 1rem; border: 2px solid #e0e0e0; }
.form-control:focus { border-color: #1a5632; box-shadow: 0 0 0 3px rgba(26,86,50,.15); }
.btn-primary { background: #1a5632; border: none; border-radius: 12px; padding: .75rem; font-weight: 700; }
.btn-primary:hover { background: #0d3d1e; }
</style>
</head>
<body>
<div class="container">
  <div class="row justify-content-center">
    <div class="col-md-5">
      <div class="card">
        <div class="card-header">
          <div style="font-size: 3rem;">🔐</div>
          <h2>{{ L.admin_login }}</h2>
        </div>
        <div class="card-body p-4">
          {% if error %}
          <div class="alert alert-danger">{{ error }}</div>
          {% endif %}
          <form method="post" action="/admin">
            <div class="mb-3">
              <label class="form-label fw-bold">{{ L.admin_password }}</label>
              <input type="password" name="password" class="form-control" required autofocus>
            </div>
            <button type="submit" class="btn btn-primary w-100">{{ L.login_btn }}</button>
          </form>
        </div>
      </div>
    </div>
  </div>
</div>
</body>
</html>"""


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


# ──────────────────────────── Flask Routes ────────────────────────────

@app.route("/", methods=["GET"])
def public_page():
    return """
<!DOCTYPE html><html lang="ar" dir="rtl"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🌍 مسافري غانا</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap');
*{font-family:'Tajawal',sans-serif}
body{background:linear-gradient(135deg,#f5f7fa,#c3cfe2);min-height:100vh;display:flex;align-items:center}
.card{border:none;border-radius:20px;box-shadow:0 10px 40px rgba(0,0,0,.1)}
.btn-primary{background:#1a5632;border:none;border-radius:12px;padding:.75rem 2rem;font-weight:700}
.btn-primary:hover{background:#0d3d1e}
</style></head><body>
<div class="container"><div class="row justify-content-center"><div class="col-md-6">
<div class="card p-5 text-center">
<div style="font-size:4rem">✈️🕋</div>
<h2 class="fw-bold mt-3">Travelers Ghana ✈️🕋</h2>
<p class="text-muted">Pilgrim &amp; Ticket Information System</p>
<hr>
<a href="/form" class="btn btn-primary btn-lg w-100 mb-2"><i class="bi bi-send"></i> Submit Request</a>
<a href="/admin" class="btn btn-outline-secondary w-100"><i class="bi bi-shield-lock"></i> Admin Panel</a>
</div></div></div></div></body></html>"""


@app.route("/form")
def form_page():
    return PUBLIC_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/extract_preview", methods=["POST", "OPTIONS"])
def extract_preview():
    if request.method == "OPTIONS":
        return cors_ok(make_response())
    if "file" not in request.files:
        return cors_ok(jsonify({"error": "No file"})), 400
    f = request.files["file"]
    data = process_file_bytes(f.read(), f.filename or "file.pdf")
    return cors_ok(jsonify(data))


@app.route("/api/submit", methods=["POST", "OPTIONS"])
def api_submit():
    if request.method == "OPTIONS":
        return cors_ok(make_response())
    name = request.form.get("name", "").strip()
    passport = request.form.get("passport", "").strip()

    if not name or not passport:
        return cors_ok(jsonify({"error": "fill_fields"})), 400
    if passport_exists(passport):
        return cors_ok(jsonify({"duplicate": True, "error": "passport_exists"})), 409

    ticket_bytes = None
    ticket_name = None
    passport_bytes = None
    passport_name = None

    if "file_ticket" in request.files and request.files["file_ticket"].filename:
        f = request.files["file_ticket"]
        ticket_bytes = f.read()
        ticket_name = f.filename
    if "file_passport" in request.files and request.files["file_passport"].filename:
        f = request.files["file_passport"]
        passport_bytes = f.read()
        passport_name = f.filename

    if not ticket_bytes and not passport_bytes:
        return cors_ok(jsonify({"error": "no_file"})), 400

    result = handle_submission(ticket_bytes, ticket_name, passport_bytes, passport_name, name, passport)
    if "error" in result:
        return cors_ok(jsonify(result)), 500
    return cors_ok(jsonify(result))


@app.route("/admin", methods=["GET", "POST"])
def admin():
    lang = request.args.get("lang", "ar")
    L = LANG[lang]
    if request.method == "POST":
        pw = request.form.get("password", "")
        if pw == ADMIN_PASSWORD:
            session["admin"] = True
        else:
            return render_template_string(LOGIN_HTML, lang=lang, L=L, error="❌ " + ("كلمة المرور خطأ" if lang == "ar" else "Wrong password"))
    if not session.get("admin"):
        return render_template_string(LOGIN_HTML, lang=lang, L=L, error="")

    query = request.args.get("q", "")
    conn = get_db()
    stats = {
        "total": conn.execute("SELECT COUNT(*) as c FROM pilgrims").fetchone()["c"],
        "flights": conn.execute("SELECT COUNT(DISTINCT flight_number) as c FROM pilgrims WHERE flight_number != ''").fetchone()["c"],
        "airlines": conn.execute("SELECT COUNT(DISTINCT airline) as c FROM pilgrims WHERE airline != ''").fetchone()["c"],
        "web": conn.execute("SELECT COUNT(*) as c FROM pilgrims WHERE user_id = 0").fetchone()["c"],
    }
    if query:
        rows = conn.execute(
            "SELECT * FROM pilgrims WHERE name LIKE ? OR passport LIKE ? OR flight_number LIKE ? ORDER BY created_at DESC LIMIT 500",
            (f"%{query}%", f"%{query}%", f"%{query}%")
        ).fetchall()
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
    if not session.get("admin"):
        return redirect("/admin")
    conn = get_db()
    conn.execute("DELETE FROM pilgrims WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    return redirect("/admin")


@app.route("/admin/export_csv")
def admin_export_csv():
    if not session.get("admin"):
        return redirect("/admin")
    conn = get_db()
    rows = conn.execute(
        "SELECT p.name, p.passport, p.flight_number, p.ticket_number, p.seat, p.airline, p.date, p.created_at, "
        "CASE WHEN p.user_id = 0 THEN 'web' ELSE 'telegram' END as source "
        "FROM pilgrims p ORDER BY p.created_at DESC"
    ).fetchall()
    conn.close()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Passport", "Flight", "Ticket", "Seat", "Airline", "Date", "Created", "Source"])
    for r in rows:
        w.writerow([r["name"], r["passport"], r["flight_number"], r["ticket_number"], r["seat"], r["airline"], r["date"], r["created_at"], r["source"]])
    return Response(out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=pilgrims.csv"})


@app.route("/api/check_passport", methods=["GET", "OPTIONS"])
def api_check_passport():
    if request.method == "OPTIONS":
        return cors_ok(make_response())
    passport = request.args.get("passport", "")
    return cors_ok(jsonify({"exists": passport_exists(passport)}))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"🌍 Server running on http://0.0.0.0:{port}")
    print(f"👑 Admin panel: http://localhost:{port}/admin")
    app.run(host="0.0.0.0", port=port, debug=True)
