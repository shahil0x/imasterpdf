import os
import io
import shutil
import tempfile
from datetime import datetime, timedelta

from flask import Flask, render_template, send_file, request, abort, Response, jsonify
from werkzeug.utils import secure_filename

from PyPDF2 import PdfReader, PdfWriter
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from PIL import Image
from pdfminer.high_level import extract_text
# from weasyprint import HTML  # Render-friendly Word→PDF

# -----------------------------------------------------------------------------
# Flask app configuration
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)

MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB per file
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_outputs")
CLEANUP_AGE_MINUTES = 30

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
ALLOWED_PDF_EXT = {'.pdf'}
ALLOWED_WORD_EXT = {'.docx'}  # DOCX only for Word→PDF
ALLOWED_TEXT_EXT = {'.txt'}

# -----------------------------------------------------------------------------
# Utility helpers
# -----------------------------------------------------------------------------
def ext_of(filename):
    return os.path.splitext(filename.lower())[1]

def validate_file(stream):
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    if size < 1024:
        abort(Response("File too small (min 1 KB).", status=400))
    if size > MAX_CONTENT_LENGTH:
        abort(Response("File too large (max 50 MB).", status=400))

def save_uploads(files):
    saved = []
    for storage in files:
        validate_file(storage.stream)
        filename = secure_filename(storage.filename)
        if not filename:
            abort(Response("Invalid filename.", status=400))
        path = os.path.join(UPLOAD_DIR, f"{datetime.utcnow().timestamp()}_{filename}")
        storage.save(path)
        saved.append(path)
    return saved

def cleanup_temp():
    cutoff = datetime.utcnow() - timedelta(minutes=CLEANUP_AGE_MINUTES)
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        for name in os.listdir(base):
            path = os.path.join(base, name)
            try:
                mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
                if mtime < cutoff:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
            except Exception:
                pass

def wrap_text(text, max_chars=95):
    words = text.split(' ')
    lines, current = [], []
    length = 0
    for w in words:
        add_len = len(w) + (1 if current else 0)
        if length + add_len <= max_chars:
            current.append(w)
            length += add_len
        else:
            lines.append(' '.join(current))
            current = [w]
            length = len(w)
    if current:
        lines.append(' '.join(current))
    return lines

def parse_pages(pages_str):
    pages = set()
    parts = [p.strip() for p in pages_str.split(',') if p.strip()]
    for part in parts:
        if '-' in part:
            a, b = part.split('-', 1)
            try:
                start = int(a); end = int(b)
                for i in range(min(start, end), max(start, end)+1):
                    pages.add(i)
            except ValueError:
                abort(Response("Invalid page range.", status=400))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                abort(Response("Invalid page number.", status=400))
    return pages

def safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# -----------------------------------------------------------------------------
# SPA routes (render_template single index.html)
# -----------------------------------------------------------------------------
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/about', methods=['GET'])
def about():
    return render_template('index.html')

@app.route('/privacy', methods=['GET'])
def privacy():
    return render_template('index.html')

@app.route('/terms', methods=['GET'])
def terms():
    return render_template('index.html')

@app.route('/tool', methods=['GET'])
def tool():
    return render_template('index.html')

@app.route('/blog', methods=['GET'])
def blog():
    return render_template('index.html')

@app.route('/blog/<slug>', methods=['GET'])
def blog_article(slug):
    return render_template('index.html')

@app.route('/contact', methods=['GET'])
def contact():
    return render_template('index.html')

# -----------------------------------------------------------------------------
# Contact API
# -----------------------------------------------------------------------------
@app.route('/api/contact', methods=['POST'])
def api_contact():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    email = (data.get('email') or '').strip()
    message = (data.get('message') or '').strip()
    if not name or not email or not message:
        return Response("Please provide name, email, and message.", status=400)
    # In production, integrate with email service or ticketing system.
    # For now, acknowledge receipt.
    return jsonify({"status": "ok", "received": {"name": name, "email": email}}), 200

# -----------------------------------------------------------------------------
# Tool APIs
# -----------------------------------------------------------------------------
@app.route('/api/pdf-to-word', methods=['POST'])
def api_pdf_to_word():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one PDF.", status=400))
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))

    try:
        text = extract_text(pdf_path) or ""
        doc = Document()
        for line in text.splitlines():
            doc.add_paragraph(line)
        out_path = os.path.join(OUTPUT_DIR, f"converted_{int(datetime.utcnow().timestamp())}.docx")
        doc.save(out_path)
        return send_file(out_path, as_attachment=True, download_name="output.docx")
    finally:
        safe_remove(pdf_path)

@app.route('/api/merge-pdf', methods=['POST'])
def api_merge_pdf():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) < 2:
        abort(Response("Upload at least two PDFs.", status=400))
    paths = save_uploads(files)
    for p in paths:
        if ext_of(p) not in ALLOWED_PDF_EXT:
            abort(Response("Only PDF files are allowed.", status=400))

    writer = PdfWriter()
    try:
        for p in paths:
            reader = PdfReader(p)
            for page in reader.pages:
                writer.add_page(page)
        out_path = os.path.join(OUTPUT_DIR, f"merged_{int(datetime.utcnow().timestamp())}.pdf")
        with open(out_path, 'wb') as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True, download_name="merged.pdf")
    finally:
        for p in paths: safe_remove(p)

@app.route('/api/rotate-pdf', methods=['POST'])
def api_rotate_pdf():
    cleanup_temp()
    rotation = int(request.form.get('rotation', '90'))
    rotate_all = request.form.get('rotate_all', 'true') == 'true'
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one PDF.", status=400))
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))

    writer = PdfWriter()
    try:
        reader = PdfReader(pdf_path)
        for idx, page in enumerate(reader.pages):
            if rotate_all or idx == 0:
                page.rotate(rotation)
            writer.add_page(page)
        out_path = os.path.join(OUTPUT_DIR, f"rotated_{int(datetime.utcnow().timestamp())}.pdf")
        with open(out_path, 'wb') as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True, download_name="rotated.pdf")
    finally:
        safe_remove(pdf_path)

@app.route('/api/delete-pages-pdf', methods=['POST'])
def api_delete_pages_pdf():
    cleanup_temp()
    pages_str = request.form.get('pages', '').strip()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one PDF.", status=400))
    if not pages_str:
        abort(Response("Pages to delete are required.", status=400))
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))

    to_delete = parse_pages(pages_str)

    writer = PdfWriter()
    try:
        reader = PdfReader(pdf_path)
        total = len(reader.pages)
        for i in range(total):
            if (i+1) not in to_delete:
                writer.add_page(reader.pages[i])
        out_path = os.path.join(OUTPUT_DIR, f"pages_removed_{int(datetime.utcnow().timestamp())}.pdf")
        with open(out_path, 'wb') as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True, download_name="pages_removed.pdf")
    finally:
        safe_remove(pdf_path)

@app.route('/api/lock-pdf', methods=['POST'])
def api_lock_pdf():
    cleanup_temp()
    pin = request.form.get('pin', '').strip()
    if not pin or not pin.isdigit() or len(pin) != 4:
        abort(Response("PIN must be exactly 4 digits.", status=400))
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one PDF.", status=400))
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))

    writer = PdfWriter()
    try:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(pin)
        out_path = os.path.join(OUTPUT_DIR, f"locked_{int(datetime.utcnow().timestamp())}.pdf")
        with open(out_path, 'wb') as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True, download_name="locked.pdf")
    finally:
        safe_remove(pdf_path)

@app.route('/api/unlock-pdf', methods=['POST'])
def api_unlock_pdf():
    cleanup_temp()
    password = request.form.get('password', '').strip()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one PDF.", status=400))
    if not password:
        abort(Response("Password is required.", status=400))
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))

    writer = PdfWriter()
    try:
        reader = PdfReader(pdf_path)
        if reader.is_encrypted:
            if not reader.decrypt(password):
                abort(Response("Incorrect password.", status=400))
        for page in reader.pages:
            writer.add_page(page)
        out_path = os.path.join(OUTPUT_DIR, f"unlocked_{int(datetime.utcnow().timestamp())}.pdf")
        with open(out_path, 'wb') as f:
            writer.write(f)
        return send_file(out_path, as_attachment=True, download_name="unlocked.pdf")
    finally:
        safe_remove(pdf_path)

@app.route('/api/word-to-pdf', methods=['POST'])
def api_word_to_pdf():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one Word file.", status=400))

    paths = save_uploads(files)
    doc_path = paths[0]

    if ext_of(doc_path) not in ALLOWED_WORD_EXT:
        abort(Response("Only DOCX files are supported.", status=400))

    try:
        doc = Document(doc_path)
        html_parts = []
        for para in doc.paragraphs:
            html_parts.append(f"<p>{para.text}</p>")

        html_content = f"""
        <html>
          <head>
            <meta charset="utf-8">
            <style>
              body {{ font-family: Arial, sans-serif; }}
              p {{ margin: 8px 0; }}
            </style>
          </head>
          <body>
            {''.join(html_parts)}
          </body>
        </html>
        """

        out_path = os.path.join(OUTPUT_DIR, f"word_{int(datetime.utcnow().timestamp())}.pdf")
        HTML(string=html_content).write_pdf(out_path)
        return send_file(out_path, as_attachment=True, download_name="converted.pdf")

    except Exception as e:
        abort(Response(f"Conversion failed: {str(e)}", status=500))

    finally:
        safe_remove(doc_path)

@app.route('/api/merge-word', methods=['POST'])
def api_merge_word():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) < 2:
        abort(Response("Upload at least two Word files.", status=400))
    paths = save_uploads(files)
    for p in paths:
        if ext_of(p) not in ALLOWED_WORD_EXT:
            abort(Response("Only DOCX files are allowed.", status=400))

    try:
        merged = Document()
        for idx, dp in enumerate(paths):
            d = Document(dp)
            for para in d.paragraphs:
                merged.add_paragraph(para.text)
            if idx < len(paths) - 1:
                merged.add_page_break()
        out_path = os.path.join(OUTPUT_DIR, f"merged_{int(datetime.utcnow().timestamp())}.docx")
        merged.save(out_path)
        return send_file(out_path, as_attachment=True, download_name="merged.docx")
    finally:
        for p in paths: safe_remove(p)

@app.route('/api/word-to-text', methods=['POST'])
def api_word_to_text():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one Word file.", status=400))
    paths = save_uploads(files)
    doc_path = paths[0]
    if ext_of(doc_path) not in ALLOWED_WORD_EXT:
        abort(Response("Only DOCX files are allowed.", status=400))

    try:
        doc = Document(doc_path)
        text_io = io.StringIO()
        for para in doc.paragraphs:
            text_io.write(para.text + "\n")
        out_bytes = io.BytesIO(text_io.getvalue().encode('utf-8'))
        return send_file(out_bytes, as_attachment=True, download_name="output.txt", mimetype='text/plain')
    finally:
        safe_remove(doc_path)

@app.route('/api/text-to-pdf', methods=['POST'])
def api_text_to_pdf():
    cleanup_temp()
    text = (request.form.get('text') or '').strip()
    if not text:
        abort(Response("Text content is required.", status=400))

    out_path = os.path.join(OUTPUT_DIR, f"text_{int(datetime.utcnow().timestamp())}.pdf")
    c = canvas.Canvas(out_path, pagesize=A4)
    width, height = A4
    left_margin = 50
    top = height - 50
    line_height = 14
    for line in text.splitlines():
        for chunk in wrap_text(line, max_chars=95):
            c.drawString(left_margin, top, chunk)
            top -= line_height
            if top < 50:
                c.showPage()
                top = height - 50
    c.save()
    return send_file(out_path, as_attachment=True, download_name="text.pdf")

@app.route('/api/text-to-word', methods=['POST'])
def api_text_to_word():
    cleanup_temp()
    text = (request.form.get('text') or '').strip()
    if not text:
        abort(Response("Text content is required.", status=400))
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    out_path = os.path.join(OUTPUT_DIR, f"text_{int(datetime.utcnow().timestamp())}.docx")
    doc.save(out_path)
    return send_file(out_path, as_attachment=True, download_name="text.docx")

@app.route('/api/images-to-pdf', methods=['POST'])
def api_images_to_pdf():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) < 1:
        abort(Response("Upload at least one image.", status=400))
    paths = save_uploads(files)
    for p in paths:
        if ext_of(p) not in ALLOWED_IMAGE_EXT:
            abort(Response("Only image files (JPG, PNG, WEBP, BMP, TIFF) are allowed.", status=400))

    try:
        images = []
        for p in paths:
            img = Image.open(p).convert('RGB')
            images.append(img)
        out_path = os.path.join(OUTPUT_DIR, f"images_{int(datetime.utcnow().timestamp())}.pdf")
        if len(images) == 1:
            images[0].save(out_path, save_all=True)
        else:
            first, rest = images[0], images[1:]
            first.save(out_path, save_all=True, append_images=rest)
        return send_file(out_path, as_attachment=True, download_name="images.pdf")
    finally:
        for p in paths: safe_remove(p)

# -----------------------------------------------------------------------------
# Gunicorn entrypoint
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)# 
