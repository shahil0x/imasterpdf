from flask import (
    Flask, request, send_file, render_template,
    abort, redirect, url_for, flash
)

import os, uuid
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from docx import Document
from PIL import Image
from reportlab.pdfgen import canvas

# ---------------- APP SETUP ----------------

app = Flask(__name__)
app.secret_key = "imasterpdf_secret_key"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.join(BASE_DIR, "uploads")
OUTPUT = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

def uid(ext):
    return f"{uuid.uuid4().hex}.{ext}"

def require_file(key="file"):
    if key not in request.files or request.files[key].filename == "":
        abort(400, "No file uploaded")

# ---------------- PAGES (ADSENSE REQUIRED) ----------------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/privacy-policy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        flash("Thank you! We will contact you soon.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

# ---------------- PDF TOOLS ----------------

@app.route("/merge-pdf", methods=["POST"])
def merge_pdf():
    files = request.files.getlist("files")
    if not files:
        abort(400, "No files selected")

    merger = PdfMerger()

    for f in files:
        if f.filename:
            path = os.path.join(UPLOAD, uid("pdf"))
            f.save(path)
            merger.append(path)

    out = os.path.join(OUTPUT, uid("pdf"))
    merger.write(out)
    merger.close()

    return send_file(out, as_attachment=True)

@app.route("/split-pdf", methods=["POST"])
def split_pdf():
    require_file()
    f = request.files["file"]

    reader = PdfReader(f)
    start = int(request.form.get("start", 1)) - 1
    end = int(request.form.get("end", len(reader.pages)))

    writer = PdfWriter()
    for i in range(start, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])

    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)

    return send_file(out, as_attachment=True)

@app.route("/rotate-pdf", methods=["POST"])
def rotate_pdf():
    require_file()
    angle = int(request.form.get("angle", 90))

    reader = PdfReader(request.files["file"])
    writer = PdfWriter()

    for p in reader.pages:
        p.rotate(angle)
        writer.add_page(p)

    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)

    return send_file(out, as_attachment=True)

@app.route("/delete-pages", methods=["POST"])
def delete_pages():
    require_file()
    pages = request.form.get("pages", "").strip()
    if not pages:
        abort(400, "No pages specified")

    remove = {int(x) for x in pages.split(",") if x.isdigit()}

    reader = PdfReader(request.files["file"])
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if (i + 1) not in remove:
            writer.add_page(page)

    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)

    return send_file(out, as_attachment=True)

# ---------------- IMAGE TO PDF ----------------

@app.route("/image-to-pdf", methods=["POST"])
def image_to_pdf():
    images = request.files.getlist("images")
    if not images:
        abort(400, "No images uploaded")

    imgs = [Image.open(i).convert("RGB") for i in images if i.filename]
    if not imgs:
        abort(400, "Invalid images")

    out = os.path.join(OUTPUT, uid("pdf"))
    imgs[0].save(out, save_all=True, append_images=imgs[1:])

    return send_file(out, as_attachment=True)

# ---------------- WORD TOOLS ----------------

@app.route("/word-to-text", methods=["POST"])
def word_to_text():
    require_file()
    doc = Document(request.files["file"])
    text = "\n".join(p.text for p in doc.paragraphs)

    out = os.path.join(OUTPUT, uid("txt"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)

    return send_file(out, as_attachment=True)

@app.route("/merge-word", methods=["POST"])
def merge_word():
    files = request.files.getlist("files")
    if not files:
        abort(400, "No Word files uploaded")

    final = Document()

    for d in files:
        doc = Document(d)
        for p in doc.paragraphs:
            final.add_paragraph(p.text)

    out = os.path.join(OUTPUT, uid("docx"))
    final.save(out)

    return send_file(out, as_attachment=True)

# ---------------- TEXT TO PDF ----------------

@app.route("/text-to-pdf", methods=["POST"])
def text_to_pdf():
    text = request.form.get("text", "").strip()
    if not text:
        abort(400, "No text provided")

    out = os.path.join(OUTPUT, uid("pdf"))
    c = canvas.Canvas(out)

    y = 800
    for line in text.split("\n"):
        c.drawString(40, y, line)
        y -= 15
        if y < 40:
            c.showPage()
            y = 800

    c.save()
    return send_file(out, as_attachment=True)

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
