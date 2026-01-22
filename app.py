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
import zipfile
from pdfminer.high_level import extract_text
import traceback

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

def safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

# -----------------------------------------------------------------------------
# Home page route
# -----------------------------------------------------------------------------
@app.route('/')
def index():
    """Main landing page"""
    return render_template('index.html')

# -----------------------------------------------------------------------------
# Tool page routes
# -----------------------------------------------------------------------------
@app.route('/word-to-pdf')
def word_to_pdf_page():
    return render_template('word-to-pdf.html')

@app.route('/merge-word')
def merge_word_page():
    return render_template('merge-word.html')

@app.route('/word-to-text')
def word_to_text_page():
    return render_template('word-to-text.html')

@app.route('/text-to-pdf')
def text_to_pdf_page():
    return render_template('text-to-pdf.html')

@app.route('/text-to-word')
def text_to_word_page():
    return render_template('text-to-word.html')

@app.route('/images-to-pdf')
def images_to_pdf_page():
    return render_template('images-to-pdf.html')

@app.route('/lock-pdf')
def lock_pdf_page():
    return render_template('lock-pdf.html')

@app.route('/pdf-to-word')
def pdf_to_word_page():
    return render_template('pdf-to-word.html')

@app.route('/merge-pdf')
def merge_pdf_page():
    return render_template('merge-pdf.html')

@app.route('/rotate-pdf')
def rotate_pdf_page():
    return render_template('rotate-pdf.html')

@app.route('/delete-pages-pdf')
def delete_pages_pdf_page():
    return render_template('delete-pages-pdf.html')

@app.route('/unlock-pdf')
def unlock_pdf_page():
    return render_template('unlock-pdf.html')

# -----------------------------------------------------------------------------
# Blog and info pages
# -----------------------------------------------------------------------------
@app.route('/blog')
def blog_page():
    return render_template('index.html')

@app.route('/about')
def about_page():
    return render_template('index.html')

@app.route('/contact')
def contact_page():
    return render_template('index.html')

@app.route('/privacy')
def privacy_page():
    return render_template('index.html')

@app.route('/terms')
def terms_page():
    return render_template('index.html')

# -----------------------------------------------------------------------------
# API Endpoints
# -----------------------------------------------------------------------------

@app.route('/api/word-to-pdf', methods=['POST'])
def api_word_to_pdf():
    """Convert Word documents to PDF"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload at least one Word file"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_WORD_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only DOC/DOCX files are supported"}), 400
        
        try:
            # Create PDF from Word document
            doc = Document(paths[0])
            
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            left_margin = 50
            top = height - 50
            line_height = 14
            
            # Process each paragraph
            for para in doc.paragraphs:
                if para.text.strip():
                    lines = wrap_text(para.text)
                    for line in lines:
                        c.drawString(left_margin, top, line)
                        top -= line_height
                        if top < 50:
                            c.showPage()
                            top = height - 50
                    top -= line_height / 2
            
            c.save()
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "converted")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"Word to PDF conversion error: {str(e)}")
            return jsonify({"error": f"Conversion failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/merge-word', methods=['POST'])
def api_merge_word():
    """Merge multiple Word documents into one"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) < 2:
            return jsonify({"error": "Upload at least two Word files"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_WORD_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only DOC/DOCX files are supported"}), 400
        
        try:
            # Merge documents
            merged_doc = Document()
            
            for idx, path in enumerate(paths):
                doc = Document(path)
                
                # Add content from this document
                for para in doc.paragraphs:
                    if para.text.strip():
                        merged_doc.add_paragraph(para.text)
                
                # Add separator between documents (except after last one)
                if idx < len(paths) - 1:
                    merged_doc.add_paragraph("\n" + "="*50 + "\n")
            
            # Save to buffer
            buffer = io.BytesIO()
            merged_doc.save(buffer)
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "merged")
            output_name = os.path.splitext(output_name)[0] + ".docx"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            
        except Exception as e:
            app.logger.error(f"Word merge error: {str(e)}")
            return jsonify({"error": f"Merging failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/word-to-text', methods=['POST'])
def api_word_to_text():
    """Extract text from Word document"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload a Word file"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_WORD_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only DOC/DOCX files are supported"}), 400
        
        try:
            # Extract text from Word document
            doc = Document(paths[0])
            text_content = []
            
            for para in doc.paragraphs:
                if para.text.strip():
                    text_content.append(para.text)
            
            # Create text file
            text = '\n'.join(text_content)
            buffer = io.BytesIO(text.encode('utf-8'))
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "extracted")
            output_name = os.path.splitext(output_name)[0] + ".txt"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='text/plain'
            )
            
        except Exception as e:
            app.logger.error(f"Word to text error: {str(e)}")
            return jsonify({"error": f"Extraction failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/text-to-pdf', methods=['POST'])
def api_text_to_pdf():
    """Convert text to PDF"""
    try:
        cleanup_temp()
        
        text = request.form.get('text', '').strip()
        if not text:
            return jsonify({"error": "Text content is required"}), 400
        
        try:
            # Create PDF from text
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            left_margin = 50
            top = height - 50
            line_height = 14
            
            # Split text into lines
            lines = text.split('\n')
            for line in lines:
                if line.strip():
                    wrapped_lines = wrap_text(line)
                    for wrapped_line in wrapped_lines:
                        c.drawString(left_margin, top, wrapped_line)
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
            
            # Create filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_name = f"text_converted_{timestamp}.pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"Text to PDF error: {str(e)}")
            return jsonify({"error": f"Conversion failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/text-to-word', methods=['POST'])
def api_text_to_word():
    """Convert text to Word document"""
    try:
        cleanup_temp()
        
        text = request.form.get('text', '').strip()
        if not text:
            return jsonify({"error": "Text content is required"}), 400
        
        try:
            # Create Word document from text
            doc = Document()
            
            # Split text into paragraphs
            paragraphs = text.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    doc.add_paragraph(para.strip())
            
            # Save to buffer
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            # Create filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_name = f"text_converted_{timestamp}.docx"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            
        except Exception as e:
            app.logger.error(f"Text to Word error: {str(e)}")
            return jsonify({"error": f"Conversion failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/images-to-pdf', methods=['POST'])
def api_images_to_pdf():
    """Convert images to PDF"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload at least one image"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_IMAGE_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only image files are supported (JPG, PNG, WEBP, BMP, TIFF)"}), 400
        
        try:
            # Convert images to PDF
            images = []
            for path in paths:
                img = Image.open(path)
                # Convert to RGB if necessary (for JPEG compatibility)
                if img.mode in ('RGBA', 'LA', 'P'):
                    rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                    rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    images.append(rgb_img)
                else:
                    images.append(img.convert('RGB'))
            
            # Save as PDF
            buffer = io.BytesIO()
            if len(images) == 1:
                images[0].save(buffer, format='PDF', save_all=True)
            else:
                images[0].save(buffer, format='PDF', save_all=True, append_images=images[1:])
            
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "images_pdf")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"Images to PDF error: {str(e)}")
            return jsonify({"error": f"Conversion failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/lock-pdf', methods=['POST'])
def api_lock_pdf():
    """Add password protection to PDF"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload a PDF file"}), 400
        
        password = request.form.get('password', '').strip()
        if not password:
            return jsonify({"error": "Password is required"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_PDF_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only PDF files are supported"}), 400
        
        try:
            # Read PDF and add password protection
            reader = PdfReader(paths[0])
            writer = PdfWriter()
            
            # Copy all pages
            for page in reader.pages:
                writer.add_page(page)
            
            # Encrypt with password
            writer.encrypt(password)
            
            # Save to buffer
            buffer = io.BytesIO()
            writer.write(buffer)
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "protected")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"PDF lock error: {str(e)}")
            return jsonify({"error": f"Encryption failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/pdf-to-word', methods=['POST'])
def api_pdf_to_word():
    """Convert PDF to Word document"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload a PDF file"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_PDF_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only PDF files are supported"}), 400
        
        try:
            # Extract text from PDF
            text = extract_text(paths[0])
            
            if not text or len(text.strip()) == 0:
                return jsonify({"error": "No extractable text found in PDF"}), 400
            
            # Create Word document
            doc = Document()
            
            # Split text into paragraphs
            paragraphs = text.split('\n\n')
            for para in paragraphs:
                if para.strip():
                    doc.add_paragraph(para.strip())
            
            # Save to buffer
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "converted")
            output_name = os.path.splitext(output_name)[0] + ".docx"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            
        except Exception as e:
            app.logger.error(f"PDF to Word error: {str(e)}")
            return jsonify({"error": f"Conversion failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/merge-pdf', methods=['POST'])
def api_merge_pdf():
    """Merge multiple PDFs into one"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) < 2:
            return jsonify({"error": "Upload at least two PDF files"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_PDF_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only PDF files are supported"}), 400
        
        try:
            # Merge PDFs
            merger = PdfMerger()
            
            for path in paths:
                merger.append(path)
            
            # Save to buffer
            buffer = io.BytesIO()
            merger.write(buffer)
            buffer.seek(0)
            merger.close()
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "merged")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"PDF merge error: {str(e)}")
            return jsonify({"error": f"Merging failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/rotate-pdf', methods=['POST'])
def api_rotate_pdf():
    """Rotate PDF pages"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload a PDF file"}), 400
        
        rotation = int(request.form.get('rotation', 90))
        if rotation not in [90, -90, 180]:
            return jsonify({"error": "Rotation must be 90, -90, or 180 degrees"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_PDF_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only PDF files are supported"}), 400
        
        try:
            # Read PDF and rotate pages
            reader = PdfReader(paths[0])
            writer = PdfWriter()
            
            # Rotate each page
            for page in reader.pages:
                page.rotate(rotation)
                writer.add_page(page)
            
            # Save to buffer
            buffer = io.BytesIO()
            writer.write(buffer)
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, f"rotated_{rotation}")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"PDF rotate error: {str(e)}")
            return jsonify({"error": f"Rotation failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/delete-pages-pdf', methods=['POST'])
def api_delete_pages_pdf():
    """Delete pages from PDF"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload a PDF file"}), 400
        
        pages_str = request.form.get('pages', '').strip()
        if not pages_str:
            return jsonify({"error": "Pages to delete are required"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_PDF_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only PDF files are supported"}), 400
        
        try:
            # Parse pages to delete
            pages_to_delete = set()
            parts = [p.strip() for p in pages_str.split(',') if p.strip()]
            
            for part in parts:
                if '-' in part:
                    try:
                        start, end = map(int, part.split('-'))
                        for page in range(start, end + 1):
                            pages_to_delete.add(page)
                    except ValueError:
                        return jsonify({"error": f"Invalid page range: {part}"}), 400
                else:
                    try:
                        pages_to_delete.add(int(part))
                    except ValueError:
                        return jsonify({"error": f"Invalid page number: {part}"}), 400
            
            # Read PDF and delete pages
            reader = PdfReader(paths[0])
            writer = PdfWriter()
            total_pages = len(reader.pages)
            
            # Add pages that are NOT in the delete list
            for i in range(total_pages):
                if (i + 1) not in pages_to_delete:
                    writer.add_page(reader.pages[i])
            
            # Save to buffer
            buffer = io.BytesIO()
            writer.write(buffer)
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "pages_deleted")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"PDF delete pages error: {str(e)}")
            return jsonify({"error": f"Page deletion failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

@app.route('/api/unlock-pdf', methods=['POST'])
def api_unlock_pdf():
    """Remove password from PDF"""
    try:
        cleanup_temp()
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or len(files) == 0:
            return jsonify({"error": "Upload a PDF file"}), 400
        
        password = request.form.get('password', '').strip()
        if not password:
            return jsonify({"error": "Password is required"}), 400
        
        paths = save_uploads(files)
        
        # Validate file types
        for path in paths:
            if ext_of(path) not in ALLOWED_PDF_EXT:
                for p in paths:
                    safe_remove(p)
                return jsonify({"error": "Only PDF files are supported"}), 400
        
        try:
            # Read encrypted PDF
            reader = PdfReader(paths[0])
            
            # Check if PDF is encrypted
            if not reader.is_encrypted:
                return jsonify({"error": "PDF is not password protected"}), 400
            
            # Try to decrypt
            if not reader.decrypt(password):
                return jsonify({"error": "Incorrect password"}), 400
            
            # Create unlocked PDF
            writer = PdfWriter()
            
            # Copy all pages
            for page in reader.pages:
                writer.add_page(page)
            
            # Save to buffer
            buffer = io.BytesIO()
            writer.write(buffer)
            buffer.seek(0)
            
            # Create filename
            original_name = secure_filename(files[0].filename)
            output_name = generate_unique_filename(original_name, "unlocked")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            return send_file(
                buffer,
                as_attachment=True,
                download_name=output_name,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            app.logger.error(f"PDF unlock error: {str(e)}")
            return jsonify({"error": f"Unlocking failed: {str(e)}"}), 500
            
    except Exception as e:
        app.logger.error(f"API error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500
        
    finally:
        for path in paths:
            safe_remove(path)

# -----------------------------------------------------------------------------
# Contact API
# -----------------------------------------------------------------------------
@app.route('/api/contact', methods=['POST'])
def api_contact():
    try:
        data = request.get_json(silent=True) or request.form
        name = data.get('name', '').strip()
        email = data.get('email', '').strip()
        message = data.get('message', '').strip()
        
        if not name or not email or not message:
            return jsonify({"error": "Please provide name, email, and message"}), 400
        
        # Here you would typically send an email or save to database
        # For now, just return success
        return jsonify({
            "success": True,
            "message": "Message received successfully",
            "data": {"name": name, "email": email}
        }), 200
        
    except Exception as e:
        app.logger.error(f"Contact API error: {str(e)}")
        return jsonify({"error": "Failed to process contact form"}), 500

# -----------------------------------------------------------------------------
# Health check endpoint
# -----------------------------------------------------------------------------
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "service": "iMasterPDF",
        "timestamp": datetime.now().isoformat()
    }), 200

# -----------------------------------------------------------------------------
# Static file serving
# -----------------------------------------------------------------------------
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"error": "Page not found"}), 404

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": "File too large (max 50 MB)"}), 413

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description) if e.description else "Bad request"}), 400

@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"Server error: {str(e)}\n{traceback.format_exc()}")
    return jsonify({"error": "Internal server error"}), 500

# -----------------------------------------------------------------------------
# Run the application
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    print("Starting iMasterPDF server...")
    print(f"Upload directory: {UPLOAD_DIR}")
    print(f"Output directory: {OUTPUT_DIR}")
    app.run(host='0.0.0.0', port=8000, debug=True)