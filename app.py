import os
import io
import shutil
import tempfile
from datetime import datetime, timedelta

from flask import Flask, render_template, send_file, request, abort, Response, jsonify
from werkzeug.utils import secure_filename

from PyPDF2 import PdfReader, PdfWriter
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from PIL import Image
from pdfminer.high_level import extract_text

# -----------------------------------------------------------------------------
# Flask app configuration
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)

MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB per file
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_outputs")
CLEANUP_AGE_MINUTES = 30

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
ALLOWED_PDF_EXT = {'.pdf'}
ALLOWED_WORD_EXT = {'.docx'}  # DOCX only for Word→PDF
ALLOWED_TEXT_EXT = {'.txt'}

# -----------------------------------------------------------------------------
# Utility helpers
# -----------------------------------------------------------------------------
def ext_of(filename):
    return os.path.splitext(filename.lower())[1]

def validate_file(stream):
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size < 1024:
        abort(Response("File too small (min 1 KB).", status=400))
    if size > MAX_CONTENT_LENGTH:
        abort(Response("File too large (max 50 MB).", status=400))

def save_uploads(files):
    saved = []
    for storage in files:
        validate_file(storage.stream)
        filename = secure_filename(storage.filename)
        if not filename:
            abort(Response("Invalid filename.", status=400))
        path = os.path.join(UPLOAD_DIR, f"{datetime.utcnow().timestamp()}_{filename}")
        storage.save(path)
        saved.append(path)
    return saved

def cleanup_temp():
    cutoff = datetime.utcnow() - timedelta(minutes=CLEANUP_AGE_MINUTES)
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        for name in os.listdir(base):
            path = os.path.join(base, name)
            try:
                mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
                if mtime < cutoff:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
            except Exception:
                pass

def wrap_text(text, max_chars=95):
    words = text.split(' ')
    lines, current = [], []
    length = 0
    for w in words:
        add_len = len(w) + (1 if current else 0)
        if length + add_len <= max_chars:
            current.append(w)
            length += add_len
        else:
            lines.append(' '.join(current))
            current = [w]
            length = len(w)
    if current:
        lines.append(' '.join(current))
    return lines

def parse_pages(pages_str):
    pages = set()
    parts = [p.strip() for p in pages_str.split(',') if p.strip()]
    for part in parts:
        if '-' in part:
            a, b = part.split('-', 1)
            try:
                start = int(a); end = int(b)
                for i in range(min(start, end), max(start, end)+1):
                    pages.add(i)
            except ValueError:
                abort(Response("Invalid page range.", status=400))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                abort(Response("Invalid page number.", status=400))
    return pages

def safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# -----------------------------------------------------------------------------
# SPA routes
# -----------------------------------------------------------------------------
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/about', methods=['GET'])
def about():
    return render_template('index.html')

@app.route('/privacy', methods=['GET'])
def privacy():
    return render_template('index.html')

@app.route('/terms', methods=['GET'])
def terms():
    return render_template('index.html')

@app.route('/tool', methods=['GET'])
def tool():
    return render_template('index.html')

@app.route('/blog', methods=['GET'])
def blog():
    return render_template('index.html')

@app.route('/blog/<slug>', methods=['GET'])
def blog_article(slug):
    return render_template('index.html')

@app.route('/contact', methods=['GET'])
def contact():
    return render_template('index.html')

# -----------------------------------------------------------------------------
# Contact API
# -----------------------------------------------------------------------------
@app.route('/api/contact', methods=['POST'])
def api_contact():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    message = (data.get('message') or '').strip()
    if not name or not email or not message:
        return Response("Please provide name, email, and message.", status=400)
    return jsonify({"status": "ok", "received": {"name": name, "email": email}}), 200

# -----------------------------------------------------------------------------
# Tool APIs
# -----------------------------------------------------------------------------
@app.route('/api/word-to-pdf', methods=['POST'])
def api_word_to_pdf():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one Word file.", status=400))
    paths = save_uploads(files)
    doc_path = paths[0]
    if ext_of(doc_path) != '.docx':
        abort(Response("Only DOCX files are supported.", status=400))
    try:
        doc = Document(doc_path)
        out_path = os.path.join(OUTPUT_DIR, f"word_{int(datetime.utcnow().timestamp())}.pdf")
        c = canvas.Canvas(out_path, pagesize=A4)
        width, height = A4
        x = 50
        y = height - 50
        line_height = 14
        for para in doc.paragraphs:
            lines = wrap_text(para.text, max_chars=95)
            for line in lines:
                c.drawString(x, y, line)
                y -= line_height
                if y < 50:
                    c.showPage()
                    y = height - 50
            y -= line_height // 2
        c.save()
        return send_file(out_path, mimetype="application/pdf", download_name="converted.pdf")
    finally:
        safe_remove(doc_path)

# Merge, rotate, delete, lock, unlock PDF routes unchanged...

# -----------------------------------------------------------------------------
# Word-to-PDF ReportLab helper
# -----------------------------------------------------------------------------
def word_to_pdf_reportlab_converter(doc_path):
    out_path = os.path.join(OUTPUT_DIR, f"word_{int(datetime.utcnow().timestamp())}_reportlab.pdf")
    doc = Document(doc_path)
    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4
    x = 50
    y = height - 50
    line_height = 14
    for para in doc.paragraphs:
        lines = wrap_text(para.text, max_chars=95)
        for line in lines:
            c.drawString(x, y, line)
            y -= line_height
            if y < 50:
                c.showPage()
                y = height - 50
        y -= line_height // 2
    c.save()
    return out_path

@app.route('/api/word-to-pdf-reportlab', methods=['POST'])
def api_word_to_pdf_reportlab():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one Word file.", status=400))
    paths = save_uploads(files)
    doc_path = paths[0]
    if ext_of(doc_path) != '.docx':
        abort(Response("Only DOCX files are supported.", status=400))
    try:
        out_path = word_to_pdf_reportlab_converter(doc_path)
        return send_file(out_path, mimetype="application/pdf", download_name="converted_reportlab.pdf")
    finally:
        safe_remove(doc_path)

# Remaining routes: merge-word, word-to-text, text-to-pdf, text-to-word, images-to-pdf unchanged...

# -----------------------------------------------------------------------------
# Gunicorn entrypoint
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)