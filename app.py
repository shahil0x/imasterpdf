<<<<<<< HEAD
from flask import Flask, request, send_file
import os, uuid, zipfile

from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from pdf2docx import Converter
from docx import Document
from docx2pdf import convert
from PIL import Image
import pandas as pd
import pdfplumber
from reportlab.pdfgen import canvas

# ---------------- APP ----------------

app = Flask(__name__)

UPLOAD = "uploads"
OUTPUT = "outputs"
os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

def uid(ext):
    return f"{uuid.uuid4().hex}.{ext}"

# ---------------- HOME ----------------

@app.route("/")
def home():
    return "iMasterPDF is live"

# ---------------- PDF TOOLS ----------------

@app.route("/merge-pdf", methods=["POST"])
def merge_pdf():
    merger = PdfMerger()
    for f in request.files.getlist("files"):
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
    reader = PdfReader(f)
    writer = PdfWriter()
    start = int(request.form["start"]) - 1
    end = int(request.form["end"])
    for i in range(start, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)
    return send_file(out, as_attachment=True)

@app.route("/rotate-pdf", methods=["POST"])
def rotate_pdf():
    f = request.files["file"]
    angle = int(request.form["angle"])
    reader = PdfReader(f)
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
    f = request.files["file"]
    remove = list(map(int, request.form["pages"].split(",")))
    reader = PdfReader(f)
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
    f = request.files["file"]
    in_path = os.path.join(UPLOAD, uid("pdf"))
    out = os.path.join(OUTPUT, uid("docx"))
    f.save(in_path)
    cv = Converter(in_path)
    cv.convert(out)
    cv.close()
    return send_file(out, as_attachment=True)

@app.route("/pdf-to-images", methods=["POST"])
def pdf_to_images():
    f = request.files["file"]
    zip_path = os.path.join(OUTPUT, uid("zip"))
    with zipfile.ZipFile(zip_path, "w") as z:
        with pdfplumber.open(f) as pdf:
            for i, page in enumerate(pdf.pages):
                img = page.to_image(resolution=150).original
                img_path = os.path.join(OUTPUT, f"page_{i+1}.png")
                img.save(img_path)
                z.write(img_path, f"page_{i+1}.png")
    return send_file(zip_path, as_attachment=True)

@app.route("/pdf-to-excel", methods=["POST"])
def pdf_to_excel():
    f = request.files["file"]
    rows = []
    with pdfplumber.open(f) as pdf:
        for p in pdf.pages:
            table = p.extract_table()
            if table:
                rows.extend(table)
    df = pd.DataFrame(rows)
    out = os.path.join(OUTPUT, uid("xlsx"))
    df.to_excel(out, index=False)
    return send_file(out, as_attachment=True)

# ---------------- IMAGE ----------------

@app.route("/image-to-pdf", methods=["POST"])
def image_to_pdf():
    images = request.files.getlist("images")
    imgs = [Image.open(i).convert("RGB") for i in images]
    out = os.path.join(OUTPUT, uid("pdf"))
    imgs[0].save(out, save_all=True, append_images=imgs[1:])
    return send_file(out, as_attachment=True)

# ---------------- WORD ----------------

@app.route("/word-to-pdf", methods=["POST"])
def word_to_pdf():
    f = request.files["file"]
    in_path = os.path.join(UPLOAD, uid("docx"))
    out = os.path.join(OUTPUT, uid("pdf"))
    f.save(in_path)
    convert(in_path, out)
    return send_file(out, as_attachment=True)

@app.route("/word-to-text", methods=["POST"])
def word_to_text():
    doc = Document(request.files["file"])
    text = "\n".join(p.text for p in doc.paragraphs)
    out = os.path.join(OUTPUT, uid("txt"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return send_file(out, as_attachment=True)

@app.route("/merge-word", methods=["POST"])
def merge_word():
    final = Document()
    for d in request.files.getlist("files"):
        doc = Document(d)
        for p in doc.paragraphs:
            final.add_paragraph(p.text)
    out = os.path.join(OUTPUT, uid("docx"))
    final.save(out)
    return send_file(out, as_attachment=True)

# ---------------- TEXT ----------------

@app.route("/text-to-pdf", methods=["POST"])
def text_to_pdf():
    text = request.form["text"]
    out = os.path.join(OUTPUT, uid("pdf"))
    c = canvas.Canvas(out)
    y = 800
    for line in text.split("\n"):
        c.drawString(40, y, line)
        y -= 15
    c.save()
    return send_file(out, as_attachment=True)
=======
from flask import Flask, render_template, request, send_file
import os, uuid, zipfile
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from pdf2docx import Converter
from docx import Document
from docx2pdf import convert
from PIL import Image
import pandas as pd
import pdfplumber
from reportlab.pdfgen import canvas

app = Flask(__name__)
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
UPLOAD, OUTPUT = "uploads", "outputs"
os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

def uid(ext):
    return f"{uuid.uuid4().hex}.{ext}"

@app.route("/")
def home():
    return render_template("indeyxx.html")

# ---------- PDF TOOLS ----------

@app.route("/merge-pdf", methods=["POST"])
def merge_pdf():
    merger = PdfMerger()
    for f in request.files.getlist("files"):
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
    reader = PdfReader(f)
    writer = PdfWriter()
    start = int(request.form["start"]) - 1
    end = int(request.form["end"])
    for i in range(start, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    out = os.path.join(OUTPUT, uid("pdf"))
    with open(out, "wb") as o:
        writer.write(o)
    return send_file(out, as_attachment=True)

@app.route("/rotate-pdf", methods=["POST"])
def rotate_pdf():
    f = request.files["file"]
    angle = int(request.form["angle"])
    reader = PdfReader(f)
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
    f = request.files["file"]
    remove = list(map(int, request.form["pages"].split(",")))
    reader = PdfReader(f)
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
    f = request.files["file"]
    in_path = os.path.join(UPLOAD, uid("pdf"))
    out = os.path.join(OUTPUT, uid("docx"))
    f.save(in_path)
    cv = Converter(in_path)
    cv.convert(out)
    cv.close()
    return send_file(out, as_attachment=True)

@app.route("/pdf-to-images", methods=["POST"])
def pdf_to_images():
    f = request.files["file"]
    zip_path = os.path.join(OUTPUT, uid("zip"))
    with zipfile.ZipFile(zip_path, 'w') as z:
        with pdfplumber.open(f) as pdf:
            for i, page in enumerate(pdf.pages):
                img = page.to_image(resolution=150).original
                img_path = os.path.join(OUTPUT, f"page_{i+1}.png")
                img.save(img_path)
                z.write(img_path, f"page_{i+1}.png")
    return send_file(zip_path, as_attachment=True)

@app.route("/pdf-to-excel", methods=["POST"])
def pdf_to_excel():
    f = request.files["file"]
    rows = []
    with pdfplumber.open(f) as pdf:
        for p in pdf.pages:
            table = p.extract_table()
            if table:
                rows.extend(table)
    df = pd.DataFrame(rows)
    out = os.path.join(OUTPUT, uid("xlsx"))
    df.to_excel(out, index=False)
    return send_file(out, as_attachment=True)

# ---------- IMAGE ----------

@app.route("/image-to-pdf", methods=["POST"])
def image_to_pdf():
    images = request.files.getlist("images")
    imgs = [Image.open(i).convert("RGB") for i in images]
    out = os.path.join(OUTPUT, uid("pdf"))
    imgs[0].save(out, save_all=True, append_images=imgs[1:])
    return send_file(out, as_attachment=True)

# ---------- WORD ----------

@app.route("/word-to-pdf", methods=["POST"])
def word_to_pdf():
    f = request.files["file"]
    in_path = os.path.join(UPLOAD, uid("docx"))
    out = os.path.join(OUTPUT, uid("pdf"))
    f.save(in_path)
    convert(in_path, out)
    return send_file(out, as_attachment=True)

@app.route("/word-to-text", methods=["POST"])
def word_to_text():
    doc = Document(request.files["file"])
    text = "\n".join(p.text for p in doc.paragraphs)
    out = os.path.join(OUTPUT, uid("txt"))
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return send_file(out, as_attachment=True)

@app.route("/merge-word", methods=["POST"])
def merge_word():
    final = Document()
    for d in request.files.getlist("files"):
        doc = Document(d)
        for p in doc.paragraphs:
            final.add_paragraph(p.text)
    out = os.path.join(OUTPUT, uid("docx"))
    final.save(out)
    return send_file(out, as_attachment=True)

# ---------- TEXT ----------

@app.route("/text-to-pdf", methods=["POST"])
def text_to_pdf():
    text = request.form["text"]
    out = os.path.join(OUTPUT, uid("pdf"))
    c = canvas.Canvas(out)
    y = 800
    for line in text.split("\n"):
        c.drawString(40, y, line)
        y -= 15
    c.save()
    return send_file(out, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)
>>>>>>> 00799e05e3e02922ce1f2a9b1dd634d6a050d2bc
