import os
import uuid
import tempfile
from datetime import datetime, timedelta

from flask import Flask, request, render_template, jsonify, abort, Response
from werkzeug.utils import secure_filename

from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from PIL import Image
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# -----------------------------------------------------------------------------
# App Config
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)
@app.route("/test-download")
def test_download():
    data = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"

    return Response(
        data,
        headers={
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="test.pdf"',
            "Content-Length": str(len(data)),
        }
    )
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
                if os.path.isfile(path) and datetime.utcfromtimestamp(os.path.getmtime(path)) < cutoff:
                    os.remove(path)
            except:
                pass


def save_file(file):
    name = secure_filename(file.filename)
    path = os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{name}")
    file.save(path)
    return path


# ✅ RENDER-SAFE FILE STREAMING (CRITICAL)
def send_file_stream(path):
    def generate():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk

    response = Response(generate(), mimetype="application/octet-stream")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{os.path.basename(path)}"'
    )
    response.headers["Content-Length"] = os.path.getsize(path)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Accel-Buffering"] = "no"
    return response

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
# Contact API
# -----------------------------------------------------------------------------
@app.route("/api/contact", methods=["POST"])
def contact_api():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not email or not message:
        return jsonify({"error": "All fields required"}), 400

    return jsonify({"status": "ok"}), 200

# -----------------------------------------------------------------------------
# PDF TOOLS
# -----------------------------------------------------------------------------
@app.route("/api/merge-pdf", methods=["POST"])
def merge_pdf():
    cleanup_temp()
    files = request.files.getlist("files")
    if len(files) < 2:
        abort(400)

    merger = PdfMerger()
    paths = []

    for f in files:
        p = save_file(f)
        paths.append(p)
        merger.append(p)

    output = os.path.join(OUTPUT_DIR, f"merged_{uuid.uuid4()}.pdf")
    merger.write(output)
    merger.close()

    for p in paths:
        os.remove(p)

    return send_file_stream(output)


@app.route("/api/split-pdf", methods=["POST"])
def split_pdf():
    cleanup_temp()
    path = save_file(request.files["file"])
    start = int(request.form["start"]) - 1
    end = int(request.form["end"]) - 1

    reader = PdfReader(path)
    writer = PdfWriter()

    for i in range(start, end + 1):
        writer.add_page(reader.pages[i])

    output = os.path.join(OUTPUT_DIR, f"split_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file_stream(output)


@app.route("/api/rotate-pdf", methods=["POST"])
def rotate_pdf():
    cleanup_temp()
    path = save_file(request.files["file"])
    angle = int(request.form["angle"])

    reader = PdfReader(path)
    writer = PdfWriter()

    for page in reader.pages:
        page.rotate_clockwise(angle)
        writer.add_page(page)

    output = os.path.join(OUTPUT_DIR, f"rotated_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file_stream(output)


@app.route("/api/delete-pages", methods=["POST"])
def delete_pages():
    cleanup_temp()
    path = save_file(request.files["file"])
    pages = [int(x) - 1 for x in request.form["pages"].split(",")]

    reader = PdfReader(path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if i not in pages:
            writer.add_page(page)

    output = os.path.join(OUTPUT_DIR, f"deleted_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file_stream(output)


@app.route("/api/lock-pdf", methods=["POST"])
def lock_pdf():
    cleanup_temp()
    path = save_file(request.files["file"])
    password = request.form["password"]

    reader = PdfReader(path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(password)

    output = os.path.join(OUTPUT_DIR, f"locked_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file_stream(output)


@app.route("/api/unlock-pdf", methods=["POST"])
def unlock_pdf():
    cleanup_temp()
    path = save_file(request.files["file"])
    password = request.form["password"]

    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(password):
        abort(400)

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    output = os.path.join(OUTPUT_DIR, f"unlocked_{uuid.uuid4()}.pdf")
    with open(output, "wb") as f:
        writer.write(f)

    os.remove(path)
    return send_file_stream(output)

# -----------------------------------------------------------------------------
# IMAGE TO PDF
# -----------------------------------------------------------------------------
@app.route("/api/images-to-pdf", methods=["POST"])
def images_to_pdf():
    cleanup_temp()
    files = request.files.getlist("files")
    if not files:
        abort(400)

    paths = [save_file(f) for f in files]
    images = [Image.open(p).convert("RGB") for p in paths]

    output = os.path.join(OUTPUT_DIR, f"images_{uuid.uuid4()}.pdf")
    images[0].save(output, save_all=True, append_images=images[1:])

    for p in paths:
        os.remove(p)

    return send_file_stream(output)

# -----------------------------------------------------------------------------
# WORD TOOLS
# -----------------------------------------------------------------------------
@app.route("/api/merge-word", methods=["POST"])
def merge_word():
    cleanup_temp()
    files = request.files.getlist("files")
    if len(files) < 2:
        abort(400)

    merged = Document()
    paths = []

    for f in files:
        p = save_file(f)
        paths.append(p)
        doc = Document(p)
        for para in doc.paragraphs:
            merged.add_paragraph(para.text)
        merged.add_page_break()

    output = os.path.join(OUTPUT_DIR, f"merged_{uuid.uuid4()}.docx")
    merged.save(output)

    for p in paths:
        os.remove(p)

    return send_file_stream(output)


@app.route("/api/word-to-text", methods=["POST"])
def word_to_text():
    cleanup_temp()
    path = save_file(request.files["file"])
    doc = Document(path)

    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    output = os.path.join(OUTPUT_DIR, f"text_{uuid.uuid4()}.txt")

    with open(output, "w", encoding="utf-8") as f:
        f.write(text)

    os.remove(path)
    return send_file_stream(output)


@app.route("/api/text-to-word", methods=["POST"])
def text_to_word():
    cleanup_temp()
    text = request.form["text"]

    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)

    output = os.path.join(OUTPUT_DIR, f"text_{uuid.uuid4()}.docx")
    doc.save(output)

    return send_file_stream(output)

# -----------------------------------------------------------------------------
# TEXT TO PDF
# -----------------------------------------------------------------------------
@app.route("/api/text-to-pdf", methods=["POST"])
def text_to_pdf():
    cleanup_temp()
    text = request.form["text"]

    output = os.path.join(OUTPUT_DIR, f"text_{uuid.uuid4()}.pdf")
    c = canvas.Canvas(output, pagesize=A4)
    t = c.beginText(40, 800)

    for line in text.splitlines():
        t.textLine(line)

    c.drawText(t)
    c.save()

    return send_file_stream(output)

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
    app.run(host="0.0.0.0", port=8000)