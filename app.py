from flask import Flask, request, send_file, render_template
import os, uuid

from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from pdf2docx import Converter
from docx import Document
from PIL import Image
from reportlab.pdfgen import canvas

app = Flask(__name__)

# ---------- CONFIG ----------
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.join(BASE_DIR, "uploads")
OUTPUT = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

def uid(ext):
    return f"{uuid.uuid4().hex}.{ext}"

# ---------- HOME ----------
@app.route("/")
def home():
    return render_template("index.html")

# ---------- PROCESS ----------
@app.route("/process", methods=["POST"])
def process():
    tool = request.form.get("tool")
    password = request.form.get("password")
    text_input = request.form.get("text")
    files = request.files.getlist("file")

    if not tool:
        return "Invalid request", 400

    if tool != "Text to PDF" and (not files or files[0].filename == ""):
        return "No file uploaded", 400

    # save first file
    input_path = None
    if files and files[0].filename != "":
        input_file = files[0]
        input_path = os.path.join(UPLOAD, uid(input_file.filename.split(".")[-1]))
        input_file.save(input_path)

    # ===== PDF TO WORD =====
    if tool == "PDF to Word":
        out = os.path.join(OUTPUT, uid("docx"))
        cv = Converter(input_path)
        cv.convert(out)
        cv.close()
        return send_file(out, as_attachment=True)

    # ===== MERGE PDF =====
    if tool == "Merge PDF":
        merger = PdfMerger()
        for f in files:
            p = os.path.join(UPLOAD, uid("pdf"))
            f.save(p)
            merger.append(p)
        out = os.path.join(OUTPUT, uid("pdf"))
        merger.write(out)
        merger.close()
        return send_file(out, as_attachment=True)

    # ===== SPLIT PDF (FIRST PAGE) =====
    if tool == "Split PDF":
        reader = PdfReader(input_path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        out = os.path.join(OUTPUT, uid("pdf"))
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    # ===== ROTATE PDF =====
    if tool == "Rotate PDF":
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for p in reader.pages:
            p.rotate(90)
            writer.add_page(p)
        out = os.path.join(OUTPUT, uid("pdf"))
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    # ===== LOCK PDF =====
    if tool == "Lock PDF":
        if not password:
            return "Password required", 400
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        writer.encrypt(password)
        out = os.path.join(OUTPUT, uid("pdf"))
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    # ===== UNLOCK PDF =====
    if tool == "Unlock PDF":
        reader = PdfReader(input_path)
        if reader.is_encrypted:
            if not password or not reader.decrypt(password):
                return "Wrong password", 400
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        out = os.path.join(OUTPUT, uid("pdf"))
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    # ===== WORD TO PDF =====
    if tool == "Word to PDF":
        doc = Document(input_path)
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

    # ===== MERGE WORD =====
    if tool == "Merge Word":
        final = Document()
        for f in files:
            p = os.path.join(UPLOAD, uid("docx"))
            f.save(p)
            d = Document(p)
            for para in d.paragraphs:
                final.add_paragraph(para.text)
        out = os.path.join(OUTPUT, uid("docx"))
        final.save(out)
        return send_file(out, as_attachment=True)

    # ===== WORD TO TEXT =====
    if tool == "Word to Text":
        doc = Document(input_path)
        text = "\n".join(p.text for p in doc.paragraphs)
        out = os.path.join(OUTPUT, uid("txt"))
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        return send_file(out, as_attachment=True)

    # ===== TEXT TO PDF =====
    if tool == "Text to PDF":
        out = os.path.join(OUTPUT, uid("pdf"))
        c = canvas.Canvas(out)
        y = 800
        for line in (text_input or "").split("\n"):
            c.drawString(40, y, line)
            y -= 15
        c.save()
        return send_file(out, as_attachment=True)

    # ===== IMAGE TO PDF =====
    if tool == "Image to PDF":
        imgs = []
        for f in files:
            imgs.append(Image.open(f).convert("RGB"))
        out = os.path.join(OUTPUT, uid("pdf"))
        imgs[0].save(out, save_all=True, append_images=imgs[1:])
        return send_file(out, as_attachment=True)

    return "Tool not supported", 400

# ---------- RUN ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
