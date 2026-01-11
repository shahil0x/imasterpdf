from flask import Flask, request, send_file, render_template
import os, uuid

from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from pdf2docx import Converter
from docx import Document
from PIL import Image
from reportlab.pdfgen import canvas

app = Flask(__name__)

# =======================
# PATHS
# =======================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def uid(ext):
    return f"{uuid.uuid4().hex}.{ext}"

# =======================
# HOME
# =======================
@app.route("/")
def home():
    return render_template("index.html")

# =======================
# UNIVERSAL PROCESS ROUTE
# =======================
@app.route("/process", methods=["POST"])
def process_file():
    tool = request.form.get("tool")
    file = request.files.get("file")

    if not tool or not file:
        return "Missing tool or file", 400

    # Save uploaded file
    in_path = os.path.join(UPLOAD_DIR, uid(file.filename.split(".")[-1]))
    file.save(in_path)

    # ================= PDF → WORD =================
    if tool == "PDF to Word":
        out_path = os.path.join(OUTPUT_DIR, uid("docx"))
        cv = Converter(in_path)
        cv.convert(out_path)
        cv.close()
        return send_file(out_path, as_attachment=True, download_name="converted.docx")

    # ================= MERGE PDF =================
    if tool == "Merge PDF":
        return "Merge PDF requires multiple files", 400

    # ================= SPLIT PDF =================
    if tool == "Split PDF":
        reader = PdfReader(in_path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        out_path = os.path.join(OUTPUT_DIR, uid("pdf"))
        with open(out_path, "wb") as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True)

    # ================= ROTATE PDF =================
    if tool == "Rotate PDF":
        reader = PdfReader(in_path)
        writer = PdfWriter()
        for p in reader.pages:
            p.rotate(90)
            writer.add_page(p)
        out_path = os.path.join(OUTPUT_DIR, uid("pdf"))
        with open(out_path, "wb") as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True)

    # ================= LOCK PDF =================
    if tool == "Lock PDF":
        reader = PdfReader(in_path)
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        writer.encrypt("1234")
        out_path = os.path.join(OUTPUT_DIR, uid("pdf"))
        with open(out_path, "wb") as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True)

    # ================= UNLOCK PDF =================
    if tool == "Unlock PDF":
        reader = PdfReader(in_path)
        if reader.is_encrypted:
            reader.decrypt("1234")
        writer = PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        out_path = os.path.join(OUTPUT_DIR, uid("pdf"))
        with open(out_path, "wb") as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True)

    # ================= WORD → PDF =================
    if tool == "Word to PDF":
        doc = Document(in_path)
        out_path = os.path.join(OUTPUT_DIR, uid("pdf"))
        c = canvas.Canvas(out_path)
        y = 800
        for p in doc.paragraphs:
            c.drawString(40, y, p.text)
            y -= 15
            if y < 40:
                c.showPage()
                y = 800
        c.save()
        return send_file(out_path, as_attachment=True)

    # ================= TEXT → PDF =================
    if tool == "Text to PDF":
        text = request.form.get("text", "")
        out_path = os.path.join(OUTPUT_DIR, uid("pdf"))
        c = canvas.Canvas(out_path)
        y = 800
        for line in text.split("\n"):
            c.drawString(40, y, line)
            y -= 15
        c.save()
        return send_file(out_path, as_attachment=True)

    # ================= IMAGE → PDF =================
    if tool == "Image to PDF":
        img = Image.open(in_path).convert("RGB")
        out_path = os.path.join(OUTPUT_DIR, uid("pdf"))
        img.save(out_path)
        return send_file(out_path, as_attachment=True)

    return "Unsupported tool", 400

# =======================
# RUN
# =======================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)