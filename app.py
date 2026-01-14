from flask import Flask, request, send_file, render_template
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from PIL import Image
from docx import Document
from reportlab.pdfgen import canvas
import os
import uuid
app = Flask(__name__)

# 50 MB limit
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.route("/")
def index():
    return render_template("index.html")

# ---------- PDF MERGE ----------
@app.route("/merge-pdf", methods=["POST"])
def merge_pdf():
    files = request.files.getlist("files")
    merger = PdfMerger()

    for file in files:
        path = os.path.join(UPLOAD_FOLDER, file.filename)
        file.save(path)
        merger.append(path)

    output = f"{OUTPUT_FOLDER}/merged_{uuid.uuid4()}.pdf"
    merger.write(output)
    merger.close()

    return send_file(output, as_attachment=True)

# ---------- PDF SPLIT ----------
@app.route("/split-pdf", methods=["POST"])
def split_pdf():
    file = request.files["file"]
    start = int(request.form["start"]) - 1
    end = int(request.form["end"]) - 1

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    reader = PdfReader(path)
    writer = PdfWriter()

    for i in range(start, end + 1):
        writer.add_page(reader.pages[i])

    output = f"{OUTPUT_FOLDER}/split_{uuid.uuid4()}.pdf"
    with open(output, "wb") as f:
        writer.write(f)

    return send_file(output, as_attachment=True)

# ---------- PDF ROTATE ----------
@app.route("/rotate-pdf", methods=["POST"])
def rotate_pdf():
    file = request.files["file"]
    angle = int(request.form["angle"])

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    reader = PdfReader(path)
    writer = PdfWriter()

    for page in reader.pages:
        page.rotate(angle)
        writer.add_page(page)

    output = f"{OUTPUT_FOLDER}/rotated_{uuid.uuid4()}.pdf"
    with open(output, "wb") as f:
        writer.write(f)

    return send_file(output, as_attachment=True)

# ---------- DELETE PAGES ----------
@app.route("/delete-pages", methods=["POST"])
def delete_pages():
    file = request.files["file"]
    pages = list(map(lambda x: int(x) - 1, request.form["pages"].split(",")))

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    reader = PdfReader(path)
    writer = PdfWriter()

    for i, page in enumerate(reader.pages):
        if i not in pages:
            writer.add_page(page)

    output = f"{OUTPUT_FOLDER}/deleted_{uuid.uuid4()}.pdf"
    with open(output, "wb") as f:
        writer.write(f)

    return send_file(output, as_attachment=True)

# ---------- LOCK PDF ----------
@app.route("/lock-pdf", methods=["POST"])
def lock_pdf():
    file = request.files["file"]
    password = request.form["password"]

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    reader = PdfReader(path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    writer.encrypt(password)

    output = f"{OUTPUT_FOLDER}/locked_{uuid.uuid4()}.pdf"
    with open(output, "wb") as f:
        writer.write(f)

    return send_file(output, as_attachment=True)

# ---------- UNLOCK PDF ----------
@app.route("/unlock-pdf", methods=["POST"])
def unlock_pdf():
    file = request.files["file"]
    password = request.form["password"]

    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    reader = PdfReader(path)
    reader.decrypt(password)

    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)

    output = f"{OUTPUT_FOLDER}/unlocked_{uuid.uuid4()}.pdf"
    with open(output, "wb") as f:
        writer.write(f)

    return send_file(output, as_attachment=True)

# ---------- IMAGE → PDF ----------
@app.route("/image-to-pdf", methods=["POST"])
def image_to_pdf():
    images = request.files.getlist("files")
    image_list = []

    for img in images:
        image = Image.open(img).convert("RGB")
        image_list.append(image)

    output = f"{OUTPUT_FOLDER}/images_{uuid.uuid4()}.pdf"
    image_list[0].save(output, save_all=True, append_images=image_list[1:])

    return send_file(output, as_attachment=True)

# ---------- WORD → PDF ----------
@app.route("/word-to-pdf", methods=["POST"])
def word_to_pdf():
    file = request.files["file"]
    path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(path)

    output = f"{OUTPUT_FOLDER}/{uuid.uuid4()}.pdf"
    convert(path, output)

    return send_file(output, as_attachment=True)

# ---------- TEXT → PDF ----------
@app.route("/text-to-pdf", methods=["POST"])
def text_to_pdf():
    text = request.form["text"]

    output = f"{OUTPUT_FOLDER}/text_{uuid.uuid4()}.pdf"
    c = canvas.Canvas(output)
    c.drawString(40, 800, text)
    c.save()

    return send_file(output, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)