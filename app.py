import os
import io
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta

from flask import Flask, render_template, send_file, request, abort, Response, jsonify
from werkzeug.utils import secure_filename

from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from PIL import Image
from pdfminer.high_level import extract_text

# -----------------------------------------------------------------------------
# Flask app configuration
# -----------------------------------------------------------------------------
app = Flask(__name__, static_folder=None, template_folder='.')
@app.route('/')
def index():
    return render_template('index.html')

MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB per file
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_outputs")
CLEANUP_AGE_MINUTES = 30

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH

ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
ALLOWED_PDF_EXT = {'.pdf'}
ALLOWED_WORD_EXT = {'.docx', '.doc'}
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

def generate_unique_filename(original_filename, suffix=""):
    """Generate a unique filename with timestamp and random component"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_str = str(uuid.uuid4())[:8]
    name, ext = os.path.splitext(original_filename)
    safe_name = secure_filename(name)
    
    # If suffix is provided, include it
    if suffix:
        return f"{safe_name}_{suffix}_{timestamp}_{random_str}{ext}"
    return f"{safe_name}_{timestamp}_{random_str}{ext}"

def save_uploads(files):
    saved = []
    for storage in files:
        validate_file(storage.stream)
        filename = secure_filename(storage.filename)
        if not filename:
            abort(Response("Invalid filename.", status=400))
        
        # Generate unique filename
        unique_filename = generate_unique_filename(storage.filename)
        path = os.path.join(UPLOAD_DIR, unique_filename)
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
# Tool APIs - CORRECTED VERSION
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
        # Extract original filename for output naming
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted")
        output_name = os.path.splitext(output_name)[0] + ".docx"
        
        # Extract text from PDF
        text = extract_text(pdf_path) or ""
        doc = Document()
        
        # Split text into paragraphs and add to document
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            if para.strip():
                doc.add_paragraph(para.strip())
        
        # Create a BytesIO buffer for the Word file
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
    except Exception as e:
        abort(Response(f"Conversion failed: {str(e)}", status=500))
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

    merger = PdfMerger()
    try:
        for p in paths:
            merger.append(p)
        
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "merged")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        # Create a BytesIO buffer for the PDF
        buffer = io.BytesIO()
        merger.write(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )
    except Exception as e:
        abort(Response(f"Merging failed: {str(e)}", status=500))
    finally:
        for p in paths:
            safe_remove(p)
        merger.close()

@app.route('/api/compress-pdf', methods=['POST'])
def api_compress_pdf():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one PDF.", status=400))
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))
    
    try:
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "compressed")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        # Simple compression by copying (in production, implement actual compression)
        reader = PdfReader(pdf_path)
        writer = PdfWriter()
        
        for page in reader.pages:
            writer.add_page(page)
        
        # Create a BytesIO buffer for the PDF
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )
    except Exception as e:
        abort(Response(f"Compression failed: {str(e)}", status=500))
    finally:
        safe_remove(pdf_path)

@app.route('/api/rotate-pdf', methods=['POST'])
def api_rotate_pdf():
    cleanup_temp()
    rotation = int(request.form.get('rotation', '90'))
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
        
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, f"rotated_{rotation}")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        for page in reader.pages:
            page.rotate(rotation)
            writer.add_page(page)
        
        # Create a BytesIO buffer for the PDF
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )
    except Exception as e:
        abort(Response(f"Rotation failed: {str(e)}", status=500))
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
        abort(Response("Pages to keep are required.", status=400))
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))

    pages_to_keep = parse_pages(pages_str)

    writer = PdfWriter()
    try:
        reader = PdfReader(pdf_path)
        total = len(reader.pages)
        
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "pages_kept")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        for i in range(total):
            if (i+1) in pages_to_keep:
                writer.add_page(reader.pages[i])
        
        # Create a BytesIO buffer for the PDF
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )
    except Exception as e:
        abort(Response(f"Splitting failed: {str(e)}", status=500))
    finally:
        safe_remove(pdf_path)

@app.route('/api/lock-pdf', methods=['POST'])
def api_lock_pdf():
    cleanup_temp()
    pin = request.form.get('pin', '').strip()
    if not pin or len(pin) != 4 or not pin.isdigit():
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
        
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "locked")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(pin)
        
        # Create a BytesIO buffer for the PDF
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )
    except Exception as e:
        abort(Response(f"Locking failed: {str(e)}", status=500))
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
        
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "unlocked")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        if reader.is_encrypted:
            if not reader.decrypt(password):
                abort(Response("Incorrect password.", status=400))
        for page in reader.pages:
            writer.add_page(page)
        
        # Create a BytesIO buffer for the PDF
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )
    except Exception as e:
        abort(Response(f"Unlocking failed: {str(e)}", status=500))
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
        abort(Response("Only DOC/DOCX files are supported.", status=400))

    try:
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        # Read Word document
        doc = Document(doc_path)
        
        # Create PDF using reportlab
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        left_margin = 50
        top = height - 50
        line_height = 14
        
        for para in doc.paragraphs:
            if para.text.strip():
                lines = wrap_text(para.text, max_chars=95)
                for line in lines:
                    c.drawString(left_margin, top, line)
                    top -= line_height
                    if top < 50:
                        c.showPage()
                        top = height - 50
                # Add space between paragraphs
                top -= line_height / 2
                if top < 50:
                    c.showPage()
                    top = height - 50
        
        c.save()
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )

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
            abort(Response("Only DOC/DOCX files are allowed.", status=400))

    try:
        merged = Document()
        for idx, dp in enumerate(paths):
            d = Document(dp)
            for para in d.paragraphs:
                if para.text.strip():
                    merged.add_paragraph(para.text)
            if idx < len(paths) - 1:
                merged.add_paragraph("\n--- End of Document ---\n")
        
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "merged")
        output_name = os.path.splitext(output_name)[0] + ".docx"
        
        # Create a BytesIO buffer for the Word file
        buffer = io.BytesIO()
        merged.save(buffer)
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
    except Exception as e:
        abort(Response(f"Merging failed: {str(e)}", status=500))
    finally:
        for p in paths:
            safe_remove(p)

@app.route('/api/word-to-text', methods=['POST'])
def api_word_to_text():
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one Word file.", status=400))
    paths = save_uploads(files)
    doc_path = paths[0]
    if ext_of(doc_path) not in ALLOWED_WORD_EXT:
        abort(Response("Only DOC/DOCX files are allowed.", status=400))

    try:
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted")
        output_name = os.path.splitext(output_name)[0] + ".txt"
        
        doc = Document(doc_path)
        text_content = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_content.append(para.text)
        
        buffer = io.BytesIO('\n'.join(text_content).encode('utf-8'))
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='text/plain'
        )
    except Exception as e:
        abort(Response(f"Conversion failed: {str(e)}", status=500))
    finally:
        safe_remove(doc_path)

@app.route('/api/text-to-pdf', methods=['POST'])
def api_text_to_pdf():
    cleanup_temp()
    text = (request.form.get('text') or '').strip()
    if not text:
        abort(Response("Text content is required.", status=400))

    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_str = str(uuid.uuid4())[:8]
    output_name = f"text_converted_{timestamp}_{random_str}.pdf"

    # Create PDF in memory
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    left_margin = 50
    top = height - 50
    line_height = 14
    
    lines = text.splitlines()
    for line in lines:
        if line.strip():
            for chunk in wrap_text(line, max_chars=95):
                c.drawString(left_margin, top, chunk)
                top -= line_height
                if top < 50:
                    c.showPage()
                    top = height - 50
        else:
            # Empty line
            top -= line_height
            if top < 50:
                c.showPage()
                top = height - 50
    
    c.save()
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=output_name,
        mimetype='application/pdf'
    )

@app.route('/api/text-to-word', methods=['POST'])
def api_text_to_word():
    cleanup_temp()
    text = (request.form.get('text') or '').strip()
    if not text:
        abort(Response("Text content is required.", status=400))
    
    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_str = str(uuid.uuid4())[:8]
    output_name = f"text_converted_{timestamp}_{random_str}.docx"
    
    doc = Document()
    lines = text.splitlines()
    for line in lines:
        if line.strip():
            doc.add_paragraph(line)
    
    # Create a BytesIO buffer for the Word file
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=output_name,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )

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
        # Generate output filename
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "images_to_pdf")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        images = []
        for p in paths:
            img = Image.open(p).convert('RGB')
            images.append(img)
        
        # Create PDF in memory
        buffer = io.BytesIO()
        if len(images) == 1:
            images[0].save(buffer, format='PDF', save_all=True)
        else:
            first, rest = images[0], images[1:]
            first.save(buffer, format='PDF', save_all=True, append_images=rest)
        
        buffer.seek(0)
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=output_name,
            mimetype='application/pdf'
        )
    except Exception as e:
        abort(Response(f"Conversion failed: {str(e)}", status=500))
    finally:
        for p in paths:
            safe_remove(p)

# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------
@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large (max 50 MB)."}), 413

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description) if e.description else "Bad request."}), 400

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error."}), 500

# -----------------------------------------------------------------------------
# Gunicorn entrypoint
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=False)