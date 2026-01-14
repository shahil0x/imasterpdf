import os
import shutil
import tempfile
import uuid
from io import BytesIO
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, send_file,
    request, abort, Response, jsonify
)
from werkzeug.utils import secure_filename

from PyPDF2 import PdfReader, PdfWriter
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from PIL import Image

# -----------------------------------------------------------------------------
# Flask app configuration
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)

MAX_CONTENT_LENGTH = 50 * 1024 * 1024
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_outputs")
CLEANUP_AGE_MINUTES = 30

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def unique_output(ext):
    return os.path.join(OUTPUT_DIR, f"{uuid.uuid4().hex}.{ext}")

def cleanup_temp():
    cutoff = datetime.utcnow() - timedelta(minutes=CLEANUP_AGE_MINUTES)
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        for f in os.listdir(base):
            p = os.path.join(base, f)
            try:
                if datetime.utcfromtimestamp(os.path.getmtime(p)) < cutoff:
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        os.remove(p)
            except:
                pass

def save_uploads(files):
    paths = []
    for f in files:
        name = secure_filename(f.filename)
        if not name:
            abort(Response("Invalid filename", 400))
        path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4().hex}_{name}")
        f.save(path)
        paths.append(path)
    return paths

def wrap_text(text, width=95):
    words = text.split()
    lines, cur, count = [], [], 0
    for w in words:
        if count + len(w) <= width:
            cur.append(w)
            count += len(w) + 1
        else:
            lines.append(" ".join(cur))
            cur = [w]
            count = len(w)
    if cur:
        lines.append(" ".join(cur))
    return lines

# ✅ MEMORY SAFE SEND (CRITICAL FIX)
def safe_send(path, filename, mimetype):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        abort(Response("Failed to generate file", 500))

    with open(path, "rb") as f:
        data = f.read()

    buffer = BytesIO(data)
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=filename,
        mimetype=mimetype
    )

# -----------------------------------------------------------------------------
# SPA Routes
# -----------------------------------------------------------------------------
@app.route("/")
@app.route("/about")
@app.route("/privacy")
@app.route("/terms")
@app.route("/tool")
@app.route("/blog")
@app.route("/blog/<slug>")
@app.route("/contact")
def spa(slug=None):
    return render_template("index.html")

# -----------------------------------------------------------------------------
# Contact
# -----------------------------------------------------------------------------
@app.route("/api/contact", methods=["POST"])
def api_contact():
    return jsonify({"status": "ok"}), 200

# -----------------------------------------------------------------------------
# WORD → PDF
# -----------------------------------------------------------------------------
@app.route("/api/word-to-pdf", methods=["POST"])
def word_to_pdf():
    cleanup_temp()
    doc_path = save_uploads(request.files.getlist("files"))[0]
    doc = Document(doc_path)

    out = unique_output("pdf")
    c = canvas.Canvas(out, pagesize=A4)
    y = A4[1] - 50

    for p in doc.paragraphs:
        for line in wrap_text(p.text):
            c.drawString(50, y, line)
            y -= 14
            if y < 50:
                c.showPage()
                y = A4[1] - 50

    c.save()
    return safe_send(out, "converted.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# MERGE PDF
# -----------------------------------------------------------------------------
@app.route("/api/merge-pdf", methods=["POST"])
def merge_pdf():
    cleanup_temp()
    paths = save_uploads(request.files.getlist("files"))
    writer = PdfWriter()

    for p in paths:
        reader = PdfReader(p)
        for page in reader.pages:
            writer.add_page(page)

    out = unique_output("pdf")
    with open(out, "wb") as f:
        writer.write(f)

    return safe_send(out, "merged.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# ROTATE PDF
# -----------------------------------------------------------------------------
@app.route("/api/rotate-pdf", methods=["POST"])
def rotate_pdf():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    deg = int(request.form.get("rotation", 90))

    reader = PdfReader(pdf)
    writer = PdfWriter()

    for p in reader.pages:
        p.rotate_clockwise(deg)
        writer.add_page(p)

    out = unique_output("pdf")
    with open(out, "wb") as f:
        writer.write(f)

    return safe_send(out, "rotated.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# DELETE PDF PAGES
# -----------------------------------------------------------------------------
@app.route("/api/delete-pages-pdf", methods=["POST"])
def delete_pages():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    pages = {int(x) - 1 for x in request.form.get("pages", "").split(",") if x}

    reader = PdfReader(pdf)
    writer = PdfWriter()

    for i, p in enumerate(reader.pages):
        if i not in pages:
            writer.add_page(p)

    out = unique_output("pdf")
    with open(out, "wb") as f:
        writer.write(f)

    return safe_send(out, "pages_removed.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# LOCK PDF
# -----------------------------------------------------------------------------
@app.route("/api/lock-pdf", methods=["POST"])
def lock_pdf():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    pin = request.form.get("pin")

    reader = PdfReader(pdf)
    writer = PdfWriter()

    for p in reader.pages:
        writer.add_page(p)

    writer.encrypt(pin)

    out = unique_output("pdf")
    with open(out, "wb") as f:
        writer.write(f)

    return safe_send(out, "locked.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# UNLOCK PDF
# -----------------------------------------------------------------------------
@app.route("/api/unlock-pdf", methods=["POST"])
def unlock_pdf():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    pwd = request.form.get("password")

    reader = PdfReader(pdf)
    reader.decrypt(pwd)

    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)

    out = unique_output("pdf")
    with open(out, "wb") as f:
        writer.write(f)

    return safe_send(out, "unlocked.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# IMAGES → PDF
# -----------------------------------------------------------------------------
@app.route("/api/images-to-pdf", methods=["POST"])
def images_to_pdf():
    cleanup_temp()
    paths = save_uploads(request.files.getlist("files"))
    images = [Image.open(p).convert("RGB") for p in paths]

    out = unique_output("pdf")
    images[0].save(out, save_all=True, append_images=images[1:])

    return safe_send(out, "images.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# TEXT → PDF
# -----------------------------------------------------------------------------
@app.route("/api/text-to-pdf", methods=["POST"])
def text_to_pdf():
    cleanup_temp()
    text = request.form.get("text", "")

    out = unique_output("pdf")
    c = canvas.Canvas(out, pagesize=A4)
    y = A4[1] - 50

    for line in text.splitlines():
        c.drawString(50, y, line)
        y -= 14
        if y < 50:
            c.showPage()
            y = A4[1] - 50

    c.save()
    return safe_send(out, "text.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# WORD → TEXT
# -----------------------------------------------------------------------------
@app.route("/api/word-to-text", methods=["POST"])
def word_to_text():
    cleanup_temp()
    path = save_uploads(request.files.getlist("files"))[0]
    doc = Document(path)

    out = unique_output("txt")
    with open(out, "w", encoding="utf-8") as f:
        for p in doc.paragraphs:
            f.write(p.text + "\n")

    return safe_send(out, "output.txt", "text/plain")

# -----------------------------------------------------------------------------
# TEXT → WORD
# -----------------------------------------------------------------------------
@app.route("/api/text-to-word", methods=["POST"])
def text_to_word():
    cleanup_temp()
    text = request.form.get("text", "")
    doc = Document()

    for l in text.splitlines():
        doc.add_paragraph(l)

    out = unique_output("docx")
    doc.save(out)

    return safe_send(
        out,
        "text.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# -----------------------------------------------------------------------------
# MERGE WORD
# -----------------------------------------------------------------------------
@app.route("/api/merge-word", methods=["POST"])
def merge_word():
    cleanup_temp()
    paths = save_uploads(request.files.getlist("files"))
    merged = Document()

    for p in paths:
        d = Document(p)
        for para in d.paragraphs:
            merged.add_paragraph(para.text)
        merged.add_page_break()

    out = unique_output("docx")
    merged.save(out)

    return safe_send(
        out,
        "merged.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)