import os
import io
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta

from flask import Flask, render_template, send_file, request, abort, Response, jsonify, send_from_directory
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
app = Flask(__name__)

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
    """Generate a unique filename with UUID and timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:12]  # Use first 12 chars of UUID
    name, ext = os.path.splitext(original_filename)
    safe_name = secure_filename(name)
    
    if suffix:
        return f"{safe_name}_{suffix}_{timestamp}_{unique_id}{ext}"
    return f"{safe_name}_{timestamp}_{unique_id}{ext}"

def save_uploads(files):
    saved = []
    for storage in files:
        validate_file(storage.stream)
        filename = secure_filename(storage.filename)
        if not filename:
            abort(Response("Invalid filename.", status=400))
        
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
# SPA Routes for each tool page
# -----------------------------------------------------------------------------

@app.route('/')
def index():
    """Main landing page"""
    return render_template('index.html')

@app.route('/split')
@app.route('/split.html')
def split_pdf():
    """Split PDF tool page"""
    return render_template('split.html')

@app.route('/mergepdf')
@app.route('/mergepdf.html')
def merge_pdf():
    """Merge PDF tool page"""
    return render_template('mergepdf.html')

@app.route('/deletepdf')
@app.route('/deletepdf.html')
def delete_pdf():
    """Delete pages from PDF tool page"""
    return render_template('deletepdf.html')

@app.route('/rotatepdf')
@app.route('/rotatepdf.html')
def rotate_pdf():
    """Rotate PDF pages tool page"""
    return render_template('rotatepdf.html')

@app.route('/pdftoword')
@app.route('/pdftoword.html')
def pdf_to_word():
    """PDF to Word converter page"""
    return render_template('pdftoword.html')

@app.route('/lockpdf')
@app.route('/lockpdf.html')
def lock_pdf():
    """Lock PDF with password page"""
    return render_template('lockpdf.html')

@app.route('/unlockpdf')
@app.route('/unlockpdf.html')
def unlock_pdf():
    """Unlock PDF page"""
    return render_template('unlockpdf.html')

@app.route('/wordtopdf')
@app.route('/wordtopdf.html')
def word_to_pdf():
    """Word to PDF converter page"""
    return render_template('wordtopdf.html')

@app.route('/mergeword')
@app.route('/mergeword.html')
def merge_word():
    """Merge Word documents page"""
    return render_template('mergeword.html')

@app.route('/wordtotext')
@app.route('/wordtotext.html')
def word_to_text():
    """Word to Text converter page"""
    return render_template('wordtotext.html')

@app.route('/texttopdf')
@app.route('/texttopdf.html')
def text_to_pdf():
    """Text to PDF converter page"""
    return render_template('texttopdf.html')

@app.route('/texttoword')
@app.route('/texttoword.html')
def text_to_word():
    """Text to Word converter page"""
    return render_template('texttoword.html')

@app.route('/imagestopdf')
@app.route('/imagestopdf.html')
def images_to_pdf():
    """Images to PDF converter page"""
    return render_template('imagestopdf.html')

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
    return jsonify({"status": "ok", "received": {"name": name, "email": email}}), 200

# -----------------------------------------------------------------------------
# Tool APIs - PDF Operations
# -----------------------------------------------------------------------------

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
        
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "merged")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
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

@app.route('/api/split-pdf', methods=['POST'])
def api_split_pdf():
    """Split PDF by page ranges"""
    cleanup_temp()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        abort(Response("Upload exactly one PDF.", status=400))
    
    ranges_str = request.form.get('ranges', '').strip()
    if not ranges_str:
        abort(Response("Page ranges are required.", status=400))
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))
    
    try:
        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        
        # Parse page ranges (e.g., "1-3,5,7-9")
        ranges = []
        parts = [p.strip() for p in ranges_str.split(',') if p.strip()]
        for part in parts:
            if '-' in part:
                start, end = part.split('-', 1)
                try:
                    start = int(start); end = int(end)
                    if 1 <= start <= total_pages and 1 <= end <= total_pages:
                        ranges.append((min(start, end)-1, max(start, end)))
                    else:
                        abort(Response(f"Page range out of bounds (1-{total_pages}).", status=400))
                except ValueError:
                    abort(Response("Invalid page range format.", status=400))
            else:
                try:
                    page = int(part)
                    if 1 <= page <= total_pages:
                        ranges.append((page-1, page))
                    else:
                        abort(Response(f"Page out of bounds (1-{total_pages}).", status=400))
                except ValueError:
                    abort(Response("Invalid page number.", status=400))
        
        # Create ZIP file with all split PDFs
        zip_buffer = io.BytesIO()
        import zipfile
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for i, (start_idx, end_page) in enumerate(ranges):
                writer = PdfWriter()
                for page_idx in range(start_idx, end_page):
                    writer.add_page(reader.pages[page_idx])
                
                split_buffer = io.BytesIO()
                writer.write(split_buffer)
                split_buffer.seek(0)
                
                original_name = secure_filename(files[0].filename)
                split_name = generate_unique_filename(original_name, f"split_{i+1}")
                split_name = os.path.splitext(split_name)[0] + ".pdf"
                
                zipf.writestr(split_name, split_buffer.getvalue())
                writer.close()
        
        zip_buffer.seek(0)
        original_name = secure_filename(files[0].filename)
        zip_name = generate_unique_filename(original_name, "split_parts")
        zip_name = os.path.splitext(zip_name)[0] + ".zip"
        
        return send_file(
            zip_buffer,
            as_attachment=True,
            download_name=zip_name,
            mimetype='application/zip'
        )
    except Exception as e:
        abort(Response(f"Splitting failed: {str(e)}", status=500))
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
        abort(Response("Pages to remove are required.", status=400))
    paths = save_uploads(files)
    pdf_path = paths[0]
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        abort(Response("Only PDF files are allowed.", status=400))

    pages_to_remove = parse_pages(pages_str)

    writer = PdfWriter()
    try:
        reader = PdfReader(pdf_path)
        total = len(reader.pages)
        
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "pages_removed")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        for i in range(total):
            if (i+1) not in pages_to_remove:
                writer.add_page(reader.pages[i])
        
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
        abort(Response(f"Page removal failed: {str(e)}", status=500))
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
        
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, f"rotated_{rotation}")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        for page in reader.pages:
            page.rotate(rotation)
            writer.add_page(page)
        
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
        
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "locked")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(pin)
        
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
        
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "unlocked")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        if reader.is_encrypted:
            if not reader.decrypt(password):
                abort(Response("Incorrect password.", status=400))
        for page in reader.pages:
            writer.add_page(page)
        
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

# -----------------------------------------------------------------------------
# Tool APIs - PDF to Word
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
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted_to_word")
        output_name = os.path.splitext(output_name)[0] + ".docx"
        
        text = extract_text(pdf_path) or ""
        doc = Document()
        
        paragraphs = text.split('\n\n')
        for para in paragraphs:
            if para.strip():
                doc.add_paragraph(para.strip())
        
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

# -----------------------------------------------------------------------------
# Tool APIs - Word Operations
# -----------------------------------------------------------------------------

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
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted_to_pdf")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        doc = Document(doc_path)
        
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
        
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "merged")
        output_name = os.path.splitext(output_name)[0] + ".docx"
        
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
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "extracted_text")
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

# -----------------------------------------------------------------------------
# Tool APIs - Text Operations
# -----------------------------------------------------------------------------

@app.route('/api/text-to-pdf', methods=['POST'])
def api_text_to_pdf():
    cleanup_temp()
    text = (request.form.get('text') or '').strip()
    if not text:
        abort(Response("Text content is required.", status=400))

    unique_id = str(uuid.uuid4())[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"text_converted_{timestamp}_{unique_id}.pdf"

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
    
    unique_id = str(uuid.uuid4())[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"text_converted_{timestamp}_{unique_id}.docx"
    
    doc = Document()
    lines = text.splitlines()
    for line in lines:
        if line.strip():
            doc.add_paragraph(line)
    
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name=output_name,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )

# -----------------------------------------------------------------------------
# Tool APIs - Images to PDF
# -----------------------------------------------------------------------------

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
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "images_to_pdf")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        images = []
        for p in paths:
            img = Image.open(p).convert('RGB')
            images.append(img)
        
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
# Health check endpoint
# -----------------------------------------------------------------------------
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200

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
# Static file serving for templates (if needed)
# -----------------------------------------------------------------------------
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# -----------------------------------------------------------------------------
# Run the application
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)