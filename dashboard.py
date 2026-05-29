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


def handle_submission(file_bytes, file_name, name, passport):
    data = process_file_bytes(file_bytes, file_name)
    if "error" in data:
        return {"error": data["error"]}

    pilgrims_list = data.get("pilgrims", [])
    tickets = data.get("tickets", {})
    raw = data.get("raw_text", "")

    if not pilgrims_list:
        pilgrims_list = [{"name": name}]
    else:
        pilgrims_list[0]["name"] = name
    tickets["passport"] = passport

    try:
        save_extraction(
            user_id=0, username="web", file_name=file_name,
            file_type=Path(file_name).suffix.lower(),
            pilgrims=pilgrims_list, tickets=tickets, raw_text=raw,
        )
    except Exception as e:
        return {"error": str(e)}

    notify_admin(name, passport, tickets.get("flight_number", ""))
    return {"success": True, "pilgrims": pilgrims_list, "tickets": tickets}


# ────────────────────── Public HTML (static, no Jinja2) ──────────────────────

PUBLIC_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🌍 مسافري غانا - تقديم طلب</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
@import url('https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;900&display=swap');
:root { --primary: #1a5632; --primary-light: #e8f5e9; --accent: #c9a227; --accent-light: #fff8e1; }
* { font-family: 'Tajawal', 'Segoe UI', sans-serif; }
body { background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%); min-height: 100vh; }
.header { background: linear-gradient(135deg, var(--primary) 0%, #2e7d32 100%); color: #fff; padding: 2rem 0; }
.header h1 { font-weight: 900; font-size: 1.8rem; margin: 0; }
.header p { opacity: .85; margin: 0; font-size: .95rem; }
.header-icon { font-size: 2.5rem; margin-left: 1rem; }
.card { border: none; border-radius: 16px; box-shadow: 0 4px 24px rgba(0,0,0,.08); margin-top: -2rem; }
.card-header { background: transparent; border-bottom: 2px solid var(--primary-light); padding: 1.2rem 1.5rem; font-weight: 700; }
.form-control, .form-select { border-radius: 12px; padding: .75rem 1rem; border: 2px solid #e0e0e0; }
.form-control:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(26,86,50,.15); }
.btn-primary { background: var(--primary); border: none; border-radius: 12px; padding: .75rem 2rem; font-weight: 700; }
.btn-primary:hover { background: #0d3d1e; }
.upload-area { border: 2px dashed #ccc; border-radius: 16px; padding: 2rem; text-align: center; cursor: pointer; transition: .3s; }
.upload-area:hover { border-color: var(--primary); background: var(--primary-light); }
.upload-area i { font-size: 3rem; color: #999; }
.upload-area p { color: #999; margin: .5rem 0 0; }
.result-card { background: var(--accent-light); border-radius: 12px; padding: 1rem; margin-top: 1rem; }
.result-item { padding: .3rem 0; }
.result-label { font-weight: 700; color: #555; }
.result-value { color: #222; }
.badge-extracted { background: var(--primary-light); color: var(--primary); font-weight: 700; padding: .4rem .8rem; border-radius: 50px; }
.alert { border-radius: 12px; }
footer { text-align: center; padding: 2rem; color: #999; font-size: .85rem; }
.lang-toggle { position: fixed; top: 1rem; left: 1rem; z-index: 999; }
.en { direction: ltr; text-align: left; }
</style>
</head>
<body>
<a href="#" id="langBtn" class="btn btn-light btn-sm lang-toggle shadow" onclick="toggleLang()">🇬🇧 English</a>

<div class="header">
  <div class="container">
    <div class="d-flex align-items-center">
      <span class="header-icon">✈️🕋</span>
      <div>
        <h1 id="title">🌍 مسافري غانا - تقديم طلب</h1>
        <p id="subtitle">تقديم معلومات الحجاج والتذاكر</p>
      </div>
    </div>
  </div>
</div>

<div class="container py-4">
  <div class="card">
    <div class="card-header">
      <i class="bi bi-file-earmark-plus"></i> <span id="formTitle">تقديم طلب جديد</span>
    </div>
    <div class="card-body p-4">

      <div id="alertBox" class="alert d-none"></div>

      <form id="submitForm" enctype="multipart/form-data">
        <div class="mb-4">
          <label class="form-label fw-bold" id="uploadLabel">رفع ملف PDF أو صورة</label>
          <div class="upload-area" id="uploadArea" onclick="document.getElementById('fileInput').click()">
            <i class="bi bi-cloud-upload"></i>
            <p id="uploadText">اضغط هنا لرفع ملف</p>
            <small class="text-muted">PDF, JPG, PNG</small>
          </div>
          <input type="file" id="fileInput" name="file" accept=".pdf,.jpg,.jpeg,.png,.tiff,.tif,.bmp,.webp" class="d-none" onchange="onFileSelect(this)">
        </div>

        <div id="extractedPreview" class="result-card d-none">
          <div class="d-flex justify-content-between align-items-center mb-2">
            <span class="badge badge-extracted"><i class="bi bi-robot"></i> <span id="extractedLabel">البيانات المستخرجة</span></span>
          </div>
          <div id="extractedFields"></div>
        </div>

        <div class="row">
          <div class="col-md-6 mb-3">
            <label class="form-label fw-bold" id="nameLabel">اسم الحاج <span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="pilgrimName" name="name" required placeholder="الاسم الكامل">
          </div>
          <div class="col-md-6 mb-3">
            <label class="form-label fw-bold" id="passportLabel">رقم الجواز <span class="text-danger">*</span></label>
            <input type="text" class="form-control" id="passportInput" name="passport" required placeholder="رقم الجواز">
          </div>
        </div>

        <button type="submit" class="btn btn-primary btn-lg w-100" id="submitBtn">
          <i class="bi bi-send"></i> <span id="submitLabel">إرسال الطلب</span>
        </button>
      </form>

    </div>
  </div>
</div>

<footer>✈️🕋 Travelers Ghana &mdash; مسافري غانا</footer>

<script>
const API = 'https://travelersghana.com/api/submit';
let lang = 'ar';

const T = {
  ar: {
    title: '🌍 مسافري غانا - تقديم طلب',
    subtitle: 'تقديم معلومات الحجاج والتذاكر',
    formTitle: 'تقديم طلب جديد',
    uploadLabel: 'رفع ملف PDF أو صورة',
    uploadText: 'اضغط هنا لرفع ملف',
    extractedLabel: 'البيانات المستخرجة',
    nameLabel: 'اسم الحاج',
    passportLabel: 'رقم الجواز',
    namePlaceholder: 'الاسم الكامل',
    passportPlaceholder: 'رقم الجواز',
    submitLabel: 'إرسال الطلب',
    processing: 'جاري المعالجة...',
    success: '✅ تم إرسال الطلب بنجاح! سيتم التواصل معك قريباً',
    duplicate: '❌ رقم الجواز هذا موجود مسبقاً',
    fillFields: '⚠️ الرجاء تعبئة جميع الحقول',
    selectFile: '⚠️ الرجاء اختيار ملف',
    error: '❌ حدث خطأ',
    pilgrims: 'الحجاج',
    flight: 'الرحلة',
    ticket: 'التذكرة',
    airline: 'الطيران',
    date: 'التاريخ',
    seat: 'المقعد',
    passport: 'الجواز',
    gate: 'البوابة',
    noData: 'لم يتم استخراج بيانات',
    extracting: 'جاري الاستخراج...',
    failed: 'فشل الاستخراج',
    langBtn: '🇬🇧 English',
  },
  en: {
    title: '🌍 Travelers Ghana - Submit Request',
    subtitle: 'Submit pilgrim and ticket information',
    formTitle: 'New Request',
    uploadLabel: 'Upload PDF or Image',
    uploadText: 'Click here to upload file',
    extractedLabel: 'Extracted Data',
    nameLabel: 'Pilgrim Name',
    passportLabel: 'Passport Number',
    namePlaceholder: 'Full name',
    passportPlaceholder: 'Passport number',
    submitLabel: 'Submit Request',
    processing: 'Processing...',
    success: '✅ Request submitted! We will contact you soon.',
    duplicate: '❌ This passport number already exists',
    fillFields: '⚠️ Please fill all fields',
    selectFile: '⚠️ Please select a file',
    error: '❌ Error occurred',
    pilgrims: 'Pilgrims',
    flight: 'Flight',
    ticket: 'Ticket',
    airline: 'Airline',
    date: 'Date',
    seat: 'Seat',
    passport: 'Passport',
    gate: 'Gate',
    noData: 'No data extracted',
    extracting: 'Extracting...',
    failed: 'Extraction failed',
    langBtn: '🇸🇦 العربية',
  }
};

function toggleLang() {
  lang = lang === 'ar' ? 'en' : 'ar';
  applyLang();
}

function applyLang() {
  const t = T[lang];
  document.getElementById('title').textContent = t.title;
  document.getElementById('subtitle').textContent = t.subtitle;
  document.getElementById('formTitle').textContent = t.formTitle;
  document.getElementById('uploadLabel').textContent = t.uploadLabel;
  document.getElementById('uploadText').textContent = t.uploadText;
  document.getElementById('extractedLabel').textContent = t.extractedLabel;
  document.getElementById('nameLabel').innerHTML = t.nameLabel + ' <span class="text-danger">*</span>';
  document.getElementById('passportLabel').innerHTML = t.passportLabel + ' <span class="text-danger">*</span>';
  document.getElementById('pilgrimName').placeholder = t.namePlaceholder;
  document.getElementById('passportInput').placeholder = t.passportPlaceholder;
  document.getElementById('submitLabel').textContent = t.submitLabel;
  document.getElementById('langBtn').textContent = T[lang === 'ar' ? 'en' : 'ar'].langBtn;
  document.dir = lang === 'ar' ? 'rtl' : 'ltr';
  document.documentElement.lang = lang;
}

function showAlert(msg, type) {
  const box = document.getElementById('alertBox');
  box.className = 'alert alert-' + (type === 'error' ? 'danger' : 'success') + ' d-flex align-items-center';
  box.innerHTML = '<i class="bi ' + (type === 'error' ? 'bi-exclamation-triangle-fill' : 'bi-check-circle-fill') + ' ms-2"></i> ' + msg;
  box.classList.remove('d-none');
  setTimeout(() => { box.className = 'alert d-none'; }, 5000);
}

function onFileSelect(input) {
  if (!input.files.length) return;
  document.getElementById('uploadText').textContent = input.files[0].name;
  previewFile(input);
}

async function previewFile(input) {
  if (!input.files.length) return;
  const t = T[lang];
  const fd = new FormData();
  fd.append('file', input.files[0]);

  document.getElementById('extractedPreview').classList.remove('d-none');
  document.getElementById('extractedFields').innerHTML = '<div class="text-center py-3"><div class="spinner-border text-primary" role="status"></div><p class="mt-2 text-muted">' + t.extracting + '</p></div>';

  try {
    const res = await fetch('/extract_preview', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.error) {
      document.getElementById('extractedFields').innerHTML = '<div class="text-danger">' + data.error + '</div>';
      return;
    }
    let html = '';
    if (data.pilgrims && data.pilgrims.length) {
      html += '<div class="result-item"><span class="result-label">👥 ' + t.pilgrims + ':</span> ';
      html += data.pilgrims.map(p => '<span class="result-value">' + p.name + '</span>').join(' | ');
      html += '</div>';
      if (data.pilgrims[0] && data.pilgrims[0].name) {
        document.getElementById('pilgrimName').value = data.pilgrims[0].name;
      }
    }
    const labels = {
      flight_number: '✈️ ' + t.flight,
      ticket_number: '🎫 ' + t.ticket,
      airline: '🏢 ' + t.airline,
      date: '📅 ' + t.date,
      seat: '💺 ' + t.seat,
      passport: '🛂 ' + t.passport,
      gate: '🚪 ' + t.gate,
    };
    if (data.tickets) {
      for (const [k, v] of Object.entries(data.tickets)) {
        if (labels[k]) {
          html += '<div class="result-item"><span class="result-label">' + labels[k] + ':</span> <span class="result-value">' + v + '</span></div>';
        }
      }
    }
    document.getElementById('extractedFields').innerHTML = html || '<div class="text-muted">' + t.noData + '</div>';
  } catch(e) {
    document.getElementById('extractedFields').innerHTML = '<div class="text-danger">' + t.failed + '</div>';
  }
}

document.getElementById('submitForm').addEventListener('submit', async function(e) {
  e.preventDefault();
  const t = T[lang];
  const name = document.getElementById('pilgrimName').value.trim();
  const passport = document.getElementById('passportInput').value.trim();
  const fileInput = document.getElementById('fileInput');

  if (!name || !passport) { showAlert(t.fillFields, 'error'); return; }
  if (!fileInput.files.length) { showAlert(t.selectFile, 'error'); return; }

  const btn = document.getElementById('submitBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + t.processing;

  const fd = new FormData();
  fd.append('file', fileInput.files[0]);
  fd.append('name', name);
  fd.append('passport', passport);

  try {
    const res = await fetch('/api/submit', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success) {
      showAlert(t.success, 'success');
      document.getElementById('pilgrimName').value = '';
      document.getElementById('passportInput').value = '';
      document.getElementById('fileInput').value = '';
      document.getElementById('uploadText').textContent = t.uploadText;
      document.getElementById('extractedPreview').classList.add('d-none');
    } else if (data.duplicate) {
      showAlert(t.duplicate, 'error');
    } else {
      showAlert((t.error + ': ' + (data.error || '')), 'error');
    }
  } catch(e) {
    showAlert(t.error, 'error');
  }
  btn.disabled = false;
  btn.innerHTML = '<i class="bi bi-send"></i> ' + t.submitLabel;
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
<h2 class="fw-bold mt-3">مسافري غانا</h2>
<p class="text-muted">Travelers Ghana</p>
<hr>
<a href="/form" class="btn btn-primary btn-lg w-100 mb-2">📝 تقديم طلب جديد</a>
<a href="/admin" class="btn btn-outline-secondary w-100">🔐 لوحة التحكم</a>
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

    if "file" not in request.files or not request.files["file"].filename:
        return cors_ok(jsonify({"error": "no_file"})), 400

    f = request.files["file"]
    result = handle_submission(f.read(), f.filename, name, passport)
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
