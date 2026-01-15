from flask import Flask, request, send_file, render_template
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from PIL import Image
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

app = Flask(__name__)

UPLOAD = "uploads"
OUTPUT = "outputs"

os.makedirs(UPLOAD, exist_ok=True)
os.makedirs(OUTPUT, exist_ok=True)

def clean(folder):
    for f in os.listdir(folder):
        os.remove(os.path.join(folder, f))

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/convert", methods=["POST"])
def convert():
    tool = request.form.get("tool")
    password = request.form.get("password")
    text_data = request.form.get("textdata")
    files = request.files.getlist("files")

    clean(UPLOAD)
    clean(OUTPUT)

    # 🔥 Unique ID per conversion
    uid = uuid.uuid4().hex[:8]

    saved = []
    for f in files:
        filename = secure_filename(f.filename)
        path = os.path.join(UPLOAD, f"{uuid.uuid4().hex}_{filename}")
        f.save(path)
        saved.append(path)

    try:
        # ---------- PDF → WORD ----------
        if tool == "pdf_to_word":
            subprocess.run([
                "libreoffice", "--headless",
                "--convert-to", "docx",
                saved[0], "--outdir", OUTPUT
            ])
            src = os.path.join(OUTPUT, os.listdir(OUTPUT)[0])
            dst = os.path.join(OUTPUT, f"pdf_to_word_{uid}.docx")
            os.rename(src, dst)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- WORD → PDF ----------
        if tool == "word_to_pdf":
            subprocess.run([
                "libreoffice", "--headless",
                "--convert-to", "pdf",
                saved[0], "--outdir", OUTPUT
            ])
            src = os.path.join(OUTPUT, os.listdir(OUTPUT)[0])
            dst = os.path.join(OUTPUT, f"word_to_pdf_{uid}.pdf")
            os.rename(src, dst)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- MERGE PDF ----------
        if tool == "merge_pdf":
            merger = PdfMerger()
            for f in saved:
                merger.append(f)
            dst = os.path.join(OUTPUT, f"merge_pdf_{uid}.pdf")
            merger.write(dst)
            merger.close()
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- SPLIT PDF ----------
        if tool == "split_pdf":
            reader = PdfReader(saved[0])
            writer = PdfWriter()
            writer.add_page(reader.pages[0])
            dst = os.path.join(OUTPUT, f"split_pdf_{uid}.pdf")
            with open(dst, "wb") as f:
                writer.write(f)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- ROTATE PDF ----------
        if tool == "rotate_pdf":
            reader = PdfReader(saved[0])
            writer = PdfWriter()
            for p in reader.pages:
                p.rotate(90)
                writer.add_page(p)
            dst = os.path.join(OUTPUT, f"rotate_pdf_{uid}.pdf")
            with open(dst, "wb") as f:
                writer.write(f)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- LOCK PDF ----------
        if tool == "lock_pdf":
            reader = PdfReader(saved[0])
            writer = PdfWriter()
            for p in reader.pages:
                writer.add_page(p)
            writer.encrypt(password)
            dst = os.path.join(OUTPUT, f"lock_pdf_{uid}.pdf")
            with open(dst, "wb") as f:
                writer.write(f)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- UNLOCK PDF ----------
        if tool == "unlock_pdf":
            reader = PdfReader(saved[0])
            reader.decrypt(password)
            writer = PdfWriter()
            for p in reader.pages:
                writer.add_page(p)
            dst = os.path.join(OUTPUT, f"unlock_pdf_{uid}.pdf")
            with open(dst, "wb") as f:
                writer.write(f)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- WORD → TEXT ----------
        if tool == "word_to_text":
            doc = Document(saved[0])
            dst = os.path.join(OUTPUT, f"word_to_text_{uid}.txt")
            with open(dst, "w", encoding="utf-8") as f:
                for p in doc.paragraphs:
                    f.write(p.text + "\n")
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- MERGE WORD ----------
        if tool == "merge_word":
            final = Document()
            for f in saved:
                d = Document(f)
                for p in d.paragraphs:
                    final.add_paragraph(p.text)
            dst = os.path.join(OUTPUT, f"merge_word_{uid}.docx")
            final.save(dst)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- IMAGES → PDF ----------
        if tool == "images_to_pdf":
            images = [Image.open(f).convert("RGB") for f in saved]
            dst = os.path.join(OUTPUT, f"images_to_pdf_{uid}.pdf")
            images[0].save(dst, save_all=True, append_images=images[1:])
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- TEXT → PDF ----------
        if tool == "text_to_pdf":
            dst = os.path.join(OUTPUT, f"text_to_pdf_{uid}.pdf")
            c = canvas.Canvas(dst)
            c.drawString(40, 800, text_data)
            c.save()
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

        # ---------- TEXT → WORD ----------
        if tool == "text_to_word":
            doc = Document()
            doc.add_paragraph(text_data)
            dst = os.path.join(OUTPUT, f"text_to_word_{uid}.docx")
            doc.save(dst)
            return send_file(dst, as_attachment=True, download_name=os.path.basename(dst))

    finally:
        clean(UPLOAD)

    return send_file(output, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)