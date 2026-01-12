from flask import Flask, render_template, request, send_file
import os, uuid
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from pdf2docx import Converter
from docx import Document
from PIL import Image
from reportlab.pdfgen import canvas

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# ✅ 50 MB upload limit
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/process", methods=["POST"])
def process():
    tool = request.form.get("tool")
    password = request.form.get("password", "")
    files = request.files.getlist("file")

    uid = str(uuid.uuid4())
    output_path = os.path.join(OUTPUT_FOLDER, uid)

    if tool == "PDF to Word":
        pdf = files[0]
        pdf_path = os.path.join(UPLOAD_FOLDER, uid + ".pdf")
        docx_path = output_path + ".docx"
        pdf.save(pdf_path)
        cv = Converter(pdf_path)
        cv.convert(docx_path)
        cv.close()
        return send_file(docx_path, as_attachment=True)

    if tool == "Merge PDF":
        merger = PdfMerger()
        for f in files:
            path = os.path.join(UPLOAD_FOLDER, f.filename)
            f.save(path)
            merger.append(path)
        out = output_path + ".pdf"
        merger.write(out)
        merger.close()
        return send_file(out, as_attachment=True)

    if tool == "Split PDF":
        pdf = files[0]
        path = os.path.join(UPLOAD_FOLDER, uid + ".pdf")
        pdf.save(path)
        reader = PdfReader(path)
        writer = PdfWriter()
        writer.add_page(reader.pages[0])
        out = output_path + "_page1.pdf"
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    if tool == "Rotate PDF":
        pdf = files[0]
        path = os.path.join(UPLOAD_FOLDER, uid + ".pdf")
        pdf.save(path)
        reader = PdfReader(path)
        writer = PdfWriter()
        for page in reader.pages:
            page.rotate(90)
            writer.add_page(page)
        out = output_path + ".pdf"
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    if tool == "Lock PDF":
        pdf = files[0]
        path = os.path.join(UPLOAD_FOLDER, uid + ".pdf")
        pdf.save(path)
        reader = PdfReader(path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(password)
        out = output_path + ".pdf"
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    if tool == "Unlock PDF":
        pdf = files[0]
        path = os.path.join(UPLOAD_FOLDER, uid + ".pdf")
        pdf.save(path)
        reader = PdfReader(path)
        reader.decrypt(password)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        out = output_path + ".pdf"
        with open(out, "wb") as f:
            writer.write(f)
        return send_file(out, as_attachment=True)

    if tool == "Word to PDF":
        docx = files[0]
        path = os.path.join(UPLOAD_FOLDER, uid + ".docx")
        docx.save(path)
        doc = Document(path)
        out = output_path + ".pdf"
        c = canvas.Canvas(out)
        y = 800
        for p in doc.paragraphs:
            c.drawString(40, y, p.text)
            y -= 14
        c.save()
        return send_file(out, as_attachment=True)

    if tool == "Merge Word":
        doc = Document()
        for f in files:
            path = os.path.join(UPLOAD_FOLDER, f.filename)
            f.save(path)
            d = Document(path)
            for p in d.paragraphs:
                doc.add_paragraph(p.text)
        out = output_path + ".docx"
        doc.save(out)
        return send_file(out, as_attachment=True)

    if tool == "Word to Text":
        docx = files[0]
        path = os.path.join(UPLOAD_FOLDER, uid + ".docx")
        docx.save(path)
        doc = Document(path)
        out = output_path + ".txt"
        with open(out, "w", encoding="utf-8") as f:
            for p in doc.paragraphs:
                f.write(p.text + "\n")
        return send_file(out, as_attachment=True)

    if tool == "Text to PDF":
        txt = files[0]
        path = os.path.join(UPLOAD_FOLDER, uid + ".txt")
        txt.save(path)
        out = output_path + ".pdf"
        c = canvas.Canvas(out)
        y = 800
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                c.drawString(40, y, line.strip())
                y -= 14
        c.save()
        return send_file(out, as_attachment=True)

    if tool == "Image to PDF":
        img = Image.open(files[0])
        out = output_path + ".pdf"
        img.convert("RGB").save(out)
        return send_file(out, as_attachment=True)

    return "Unsupported tool", 400

if __name__ == "__main__":
    app.run(debug=True)