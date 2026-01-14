import os
import io
import shutil
import tempfile
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, send_file, request,
    abort, Response, jsonify, after_this_request
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
def cleanup_temp():
    cutoff = datetime.utcnow() - timedelta(minutes=CLEANUP_AGE_MINUTES)
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        for f in os.listdir(base):
            p = os.path.join(base, f)
            try:
                if datetime.utcfromtimestamp(os.path.getmtime(p)) < cutoff:
                    os.remove(p)
            except:
                pass

def save_uploads(files):
    paths = []
    for f in files:
        name = secure_filename(f.filename)
        path = os.path.join(UPLOAD_DIR, f"{int(datetime.utcnow().timestamp())}_{name}")
        f.save(path)
        paths.append(path)
    return paths

def wrap_text(text, width=95):
    words = text.split()
    lines, cur = [], []
    count = 0
    for w in words:
        if count + len(w) <= width:
            cur.append(w)
            count += len(w)
        else:
            lines.append(" ".join(cur))
            cur = [w]
            count = len(w)
    if cur:
        lines.append(" ".join(cur))
    return lines

def send_and_cleanup(path, filename, mimetype):
    @after_this_request
    def cleanup(response):
        try:
            os.remove(path)
        except:
            pass
        return response

    return send_file(
        path,
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

    out = os.path.join(OUTPUT_DIR, "word.pdf")
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
    os.remove(doc_path)

    return send_and_cleanup(out, "converted.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# MERGE PDF
# -----------------------------------------------------------------------------
@app.route("/api/merge-pdf", methods=["POST"])
def merge_pdf():
    cleanup_temp()
    paths = save_uploads(request.files.getlist("files"))
    writer = PdfWriter()

    for p in paths:
        r = PdfReader(p)
        for page in r.pages:
            writer.add_page(page)

    out = os.path.join(OUTPUT_DIR, "merged.pdf")
    with open(out, "wb") as f:
        writer.write(f)

    for p in paths:
        os.remove(p)

    return send_and_cleanup(out, "merged.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# ROTATE PDF
# -----------------------------------------------------------------------------
@app.route("/api/rotate-pdf", methods=["POST"])
def rotate_pdf():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    deg = int(request.form.get("rotation", 90))

    r = PdfReader(pdf)
    w = PdfWriter()
    for p in r.pages:
        p.rotate(deg)
        w.add_page(p)

    out = os.path.join(OUTPUT_DIR, "rotated.pdf")
    with open(out, "wb") as f:
        w.write(f)

    os.remove(pdf)
    return send_and_cleanup(out, "rotated.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# DELETE PAGES PDF
# -----------------------------------------------------------------------------
@app.route("/api/delete-pages-pdf", methods=["POST"])
def delete_pages():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    pages = {int(x) - 1 for x in request.form.get("pages").split(",")}

    r = PdfReader(pdf)
    w = PdfWriter()
    for i, p in enumerate(r.pages):
        if i not in pages:
            w.add_page(p)

    out = os.path.join(OUTPUT_DIR, "pages_removed.pdf")
    with open(out, "wb") as f:
        w.write(f)

    os.remove(pdf)
    return send_and_cleanup(out, "pages_removed.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# LOCK PDF
# -----------------------------------------------------------------------------
@app.route("/api/lock-pdf", methods=["POST"])
def lock_pdf():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    pin = request.form.get("pin")

    r = PdfReader(pdf)
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)
    w.encrypt(pin)

    out = os.path.join(OUTPUT_DIR, "locked.pdf")
    with open(out, "wb") as f:
        w.write(f)

    os.remove(pdf)
    return send_and_cleanup(out, "locked.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# UNLOCK PDF
# -----------------------------------------------------------------------------
@app.route("/api/unlock-pdf", methods=["POST"])
def unlock_pdf():
    cleanup_temp()
    pdf = save_uploads(request.files.getlist("files"))[0]
    pwd = request.form.get("password")

    r = PdfReader(pdf)
    r.decrypt(pwd)
    w = PdfWriter()
    for p in r.pages:
        w.add_page(p)

    out = os.path.join(OUTPUT_DIR, "unlocked.pdf")
    with open(out, "wb") as f:
        w.write(f)

    os.remove(pdf)
    return send_and_cleanup(out, "unlocked.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# IMAGES → PDF
# -----------------------------------------------------------------------------
@app.route("/api/images-to-pdf", methods=["POST"])
def images_to_pdf():
    cleanup_temp()
    paths = save_uploads(request.files.getlist("files"))
    imgs = [Image.open(p).convert("RGB") for p in paths]

    out = os.path.join(OUTPUT_DIR, "images.pdf")
    imgs[0].save(out, save_all=True, append_images=imgs[1:])

    for p in paths:
        os.remove(p)

    return send_and_cleanup(out, "images.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# TEXT → PDF
# -----------------------------------------------------------------------------
@app.route("/api/text-to-pdf", methods=["POST"])
def text_to_pdf():
    cleanup_temp()
    text = request.form.get("text", "")

    out = os.path.join(OUTPUT_DIR, "text.pdf")
    c = canvas.Canvas(out, pagesize=A4)
    y = A4[1] - 50

    for line in text.splitlines():
        c.drawString(50, y, line)
        y -= 14
        if y < 50:
            c.showPage()
            y = A4[1] - 50
    c.save()

    return send_and_cleanup(out, "text.pdf", "application/pdf")

# -----------------------------------------------------------------------------
# WORD → TEXT
# -----------------------------------------------------------------------------
@app.route("/api/word-to-text", methods=["POST"])
def word_to_text():
    cleanup_temp()
    doc = Document(save_uploads(request.files.getlist("files"))[0])

    out = os.path.join(OUTPUT_DIR, "output.txt")
    with open(out, "w", encoding="utf-8") as f:
        for p in doc.paragraphs:
            f.write(p.text + "\n")

    return send_and_cleanup(out, "output.txt", "text/plain")

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

    out = os.path.join(OUTPUT_DIR, "text.docx")
    doc.save(out)

    return send_and_cleanup(out, "text.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

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
        os.remove(p)

    out = os.path.join(OUTPUT_DIR, "merged.docx")
    merged.save(out)

    return send_and_cleanup(out, "merged.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)