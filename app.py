import os
import io
import uuid
import shutil
import tempfile
from datetime import datetime, timedelta

from flask import Flask, request, send_file, render_template, jsonify, abort, Response
from werkzeug.utils import secure_filename

from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from PIL import Image
from docx2pdf import convert
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# -----------------------------------------------------------------------------
# App Config
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "imaster_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "imaster_outputs")
CLEANUP_MINUTES = 30

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def cleanup_temp():
    cutoff = datetime.utcnow() - timedelta(minutes=CLEANUP_MINUTES)
    for folder in (UPLOAD_DIR, OUTPUT_DIR):
        for f in os.listdir(folder):
            path = os.path.join(folder, f)
            try:
                if datetime.utcfromtimestamp(os.path.getmtime(path)) < cutoff:
                    os.remove(path)
            except:
                pass

def save_file(file):
    name = secure_filename(file.filename)
    unique = f"{uuid.uuid4()}_{name}"
    path = os.path.join(UPLOAD_DIR, unique)
    file.save(path)
    return path

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
def index(slug=None):
    return render_template("index.html")

# -----------------------------------------------------------------------------
# TOOL APIs (SIMPLIFIED FROM CODE 2)
# -----------------------------------------------------------------------------

# ---------- MERGE PDF ----------
@app.route("/api/merge-pdf", methods=["POST"])
def merge_pdf():
    cleanup_temp()
    files = request.files.getlist("files")
    if len(files) < 2:
        abort(Response("Upload at least two PDFs", 400))

    merger = PdfMerger()
    paths = []

    for f in files:
        path = save_file(f)
        paths.append(path)
        merger.append(path)

    output = os.path.join(OUTPUT_DIR, f"merged_{uuid.uuid4()}.pdf")
    merger.write(output)
    merger.close()

    for p in paths:
        os.remove(p)

    return send_file(output, as_attachment=True)

# ---------- SPLIT PDF ----------
@app.route("/api/split-pdf", methods=["POST"])
def split_pdf():
    cleanup_temp()
    file = request.files["file"]
    start = int(request.form["start"]) - 1
    end = int(request.form["end"]) - 1

    path = save_file(file)
    reader = PdfReader(path)
    writer = PdfWriter()

    for i in range(start, end + 1):
        writer.add_page(reader.pages[i])

    output = os.path.join(OUTPUT_DIR, f"split_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file(output, as_attachment=True)

# ---------- ROTATE PDF ----------
@app.route("/api/rotate-pdf", methods=["POST"])
def rotate_pdf():
    cleanup_temp()
    file = request.files["file"]
    angle = int(request.form["angle"])

    path = save_file(file)
    reader = PdfReader(path)
    writer = PdfWriter()

    for page in reader.pages:
        page.rotate(angle)
        writer.add_page(page)

    output = os.path.join(OUTPUT_DIR, f"rotated_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file(output, as_attachment=True)

# ---------- DELETE PAGES ----------
@app.route("/api/delete-pages", methods=["POST"])
def delete_pages():
    cleanup_temp()
    file = request.files["file"]
    pages = [int(p) - 1 for p in request.form["pages"].split(",")]

    path = save_file(file)
    reader = PdfReader(path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if i not in pages:
            writer.add_page(page)

    output = os.path.join(OUTPUT_DIR, f"deleted_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file(output, as_attachment=True)

# ---------- LOCK PDF ----------
@app.route("/api/lock-pdf", methods=["POST"])
def lock_pdf():
    cleanup_temp()
    file = request.files["file"]
    password = request.form["password"]

    path = save_file(file)
    reader = PdfReader(path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(password)
    output = os.path.join(OUTPUT_DIR, f"locked_{uuid.uuid4()}.pdf")

    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file(output, as_attachment=True)

# ---------- UNLOCK PDF ----------
@app.route("/api/unlock-pdf", methods=["POST"])
def unlock_pdf():
    cleanup_temp()
    file = request.files["file"]
    password = request.form["password"]

    path = save_file(file)
    reader = PdfReader(path)

    if reader.is_encrypted:
        if not reader.decrypt(password):
            abort(Response("Wrong password", 400))

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    output = os.path.join(OUTPUT_DIR, f"unlocked_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file(output, as_attachment=True)

# ---------- IMAGE → PDF ----------
@app.route("/api/images-to-pdf", methods=["POST"])
def images_to_pdf():
    cleanup_temp()
    images = request.files.getlist("files")
    if not images:
        abort(Response("Upload images", 400))

    imgs = [Image.open(img).convert("RGB") for img in images]
    output = os.path.join(OUTPUT_DIR, f"images_{uuid.uuid4()}.pdf")

    imgs[0].save(output, save_all=True, append_images=imgs[1:])
    return send_file(output, as_attachment=True)

# ---------- WORD → PDF ----------
@app.route("/api/word-to-pdf", methods=["POST"])
def word_to_pdf():
    cleanup_temp()
    file = request.files["file"]
    path = save_file(file)

    output = os.path.join(OUTPUT_DIR, f"{uuid.uuid4()}.pdf")
    convert(path, output)

    os.remove(path)
    return send_file(output, as_attachment=True)

# ---------- TEXT → PDF ----------
@app.route("/api/text-to-pdf", methods=["POST"])
def text_to_pdf():
    cleanup_temp()
    text = request.form["text"]

    output = os.path.join(OUTPUT_DIR, f"text_{uuid.uuid4()}.pdf")
    c = canvas.Canvas(output, pagesize=A4)
    c.drawString(40, 800, text)
    c.save()

    return send_file(output, as_attachment=True)

# -----------------------------------------------------------------------------
# Errors
# -----------------------------------------------------------------------------
@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"error": "File too large (50MB max)"}), 413

# -----------------------------------------------------------------------------
# Run
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)