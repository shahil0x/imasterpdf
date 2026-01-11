from flask import Flask, request, send_file, render_template, abort
import os, uuid

from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from docx import Document
from PIL import Image
from reportlab.pdfgen import canvas
from pdf2docx import Converter

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.join(BASE_DIR, "uploads")
OUTPUT = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

def uid(ext):
    return f"{uuid.uuid4().hex}.{ext}"

# ---------------- PAGES ----------------
@app.route("/")
def home():
    return render_template("index.html")
# ---------------- PDF TOOLS ----------------
@app.route("/merge-pdf", methods=["POST"])
def merge_pdf():
    files = request.files.getlist("files")
    merger = PdfMerger()
    for f in files:
        path = os.path.join(UPLOAD, uid("pdf"))
        f.save(path)
        merger.append(path)
    out = os.path.join(OUTPUT, uid("pdf"))
    merger.write(out)
    merger.close()
    return send_file(out, as_attachment=True)

@app.route("/split-pdf", methods=["POST"])
def split_pdf():
    f = request.files["file"]
    start = int(request.form.get("start", 1)) - 1
    end = int(request.form.get("end", 999))
    reader = PdfReader(f)
    writer = PdfWriter()
    for i in range(start, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)
    return send_file(out, as_attachment=True)

@app.route("/rotate-pdf", methods=["POST"])
def rotate_pdf():
    f = request.files["file"]
    angle = int(request.form.get("angle", 90))
    reader = PdfReader(f)
    writer = PdfWriter()
    for p in reader.pages:
        p.rotate(angle)
        writer.add_page(p)
    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)
    return send_file(out, as_attachment=True)

@app.route("/pdf-to-word", methods=["POST"])
def pdf_to_word():
    pdf = request.files["file"]
    pdf_path = os.path.join(UPLOAD, uid("pdf"))
    docx_path = os.path.join(OUTPUT, uid("docx"))
    pdf.save(pdf_path)
    cv = Converter(pdf_path)
    cv.convert(docx_path)
    cv.close()
    return send_file(docx_path, as_attachment=True)

@app.route("/lock-pdf", methods=["POST"])
def lock_pdf():
    f = request.files["file"]
    password = request.form.get("password")
    reader = PdfReader(f)
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    writer.encrypt(password)
    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)
    return send_file(out, as_attachment=True)

@app.route("/unlock-pdf", methods=["POST"])
def unlock_pdf():
    f = request.files["file"]
    password = request.form.get("password")
    reader = PdfReader(f)
    if reader.is_encrypted:
        if not reader.decrypt(password):
            return "Wrong password", 400
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)
    return send_file(out, as_attachment=True)

# ---------------- WORD ----------------
@app.route("/word-to-pdf", methods=["POST"])
def word_to_pdf():
    doc = Document(request.files["file"])
    out = os.path.join(OUTPUT, uid("pdf"))
    c = canvas.Canvas(out)
    y = 800
    for p in doc.paragraphs:
        c.drawString(40, y, p.text)
        y -= 15
        if y < 40:
            c.showPage()
            y = 800
    c.save()
    return send_file(out, as_attachment=True)

@app.route("/merge-word", methods=["POST"])
def merge_word():
    files = request.files.getlist("files")
    final = Document()
    for f in files:
        doc = Document(f)
        for p in doc.paragraphs:
            final.add_paragraph(p.text)
    out = os.path.join(OUTPUT, uid("docx"))
    final.save(out)
    return send_file(out, as_attachment=True)

@app.route("/word-to-text", methods=["POST"])
def word_to_text():
    doc = Document(request.files["file"])
    text = "\n".join(p.text for p in doc.paragraphs)
    out = os.path.join(OUTPUT, uid("txt"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return send_file(out, as_attachment=True)

# ---------------- TEXT ----------------
@app.route("/text-to-pdf", methods=["POST"])
def text_to_pdf():
    text = request.form.get("text")
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

@app.route("/text-to-word", methods=["POST"])
def text_to_word():
    text = request.form.get("text")
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    out = os.path.join(OUTPUT, uid("docx"))
    doc.save(out)
    return send_file(out, as_attachment=True)

# ---------------- IMAGE ----------------
@app.route("/image-to-pdf", methods=["POST"])
def image_to_pdf():
    images = request.files.getlist("images")
    imgs = [Image.open(i).convert("RGB") for i in images]
    out = os.path.join(OUTPUT, uid("pdf"))
    imgs[0].save(out, save_all=True, append_images=imgs[1:])
    return send_file(out, as_attachment=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
