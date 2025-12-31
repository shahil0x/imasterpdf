from flask import Flask, request, send_file, render_template, abort
import os, uuid, zipfile

from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from pdf2docx import Converter
from docx import Document
from PIL import Image
import pandas as pd
import pdfplumber
from reportlab.pdfgen import canvas

# ---------------- APP SETUP ----------------

app = Flask(__name__)

UPLOAD = "uploads"
OUTPUT = "outputs"
os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

def uid(ext):
    return f"{uuid.uuid4().hex}.{ext}"

def require_file(key="file"):
    if key not in request.files or request.files[key].filename == "":
        abort(400, "No file uploaded")

# ---------------- HOME ----------------

@app.route("/")
def home():
    return render_template("indeyxx.html")

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
        p.rotate_clockwise(angle)
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

    remove = [int(x) for x in pages.split(",") if x.isdigit()]
    reader = PdfReader(request.files["file"])
    writer = PdfWriter()

    for i, p in enumerate(reader.pages):
        if (i + 1) not in remove:
            writer.add_page(p)

    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)

    return send_file(out, as_attachment=True)

@app.route("/pdf-to-word", methods=["POST"])
def pdf_to_word():
    require_file()
    in_path = os.path.join(UPLOAD, uid("pdf"))
    out = os.path.join(OUTPUT, uid("docx"))

    request.files["file"].save(in_path)
    cv = Converter(in_path)
    cv.convert(out)
    cv.close()

    return send_file(out, as_attachment=True)

@app.route("/pdf-to-images", methods=["POST"])
def pdf_to_images():
    require_file()
    zip_path = os.path.join(OUTPUT, uid("zip"))

    with zipfile.ZipFile(zip_path, "w") as z:
        with pdfplumber.open(request.files["file"]) as pdf:
            for i, page in enumerate(pdf.pages):
                img = page.to_image(resolution=150).original
                img_path = os.path.join(OUTPUT, f"page_{i+1}.png")
                img.save(img_path)
                z.write(img_path, os.path.basename(img_path))

    return send_file(zip_path, as_attachment=True)

@app.route("/pdf-to-excel", methods=["POST"])
def pdf_to_excel():
    require_file()
    rows = []

    with pdfplumber.open(request.files["file"]) as pdf:
        for p in pdf.pages:
            table = p.extract_table()
            if table:
                rows.extend(table)

    if not rows:
        abort(400, "No tables found in PDF")

    df = pd.DataFrame(rows)
    out = os.path.join(OUTPUT, uid("xlsx"))
    df.to_excel(out, index=False)

    return send_file(out, as_attachment=True)

# ---------------- IMAGE ----------------

@app.route("/image-to-pdf", methods=["POST"])
def image_to_pdf():
    images = request.files.getlist("images")
    if not images:
        abort(400, "No images uploaded")

    imgs = [Image.open(i).convert("RGB") for i in images if i.filename]
    out = os.path.join(OUTPUT, uid("pdf"))
    imgs[0].save(out, save_all=True, append_images=imgs[1:])

    return send_file(out, as_attachment=True)

# ---------------- WORD ----------------

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

# ---------------- TEXT ----------------

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

    c.save()
    return send_file(out, as_attachment=True)

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
