import os
import io
import shutil
import tempfile
import uuid
import re
import time
import hashlib
import zipfile
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import concurrent.futures
import threading

from flask import Flask, render_template, send_file, request, abort, Response, jsonify, send_from_directory, after_this_request
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix

from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from pdfminer.high_level import extract_text
import numpy as np

# OCR Libraries - Only import when needed
try:
    import pytesseract
    from pdf2image import convert_from_path, convert_from_bytes
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# -----------------------------------------------------------------------------
# Flask app configuration
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Performance settings
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB per file
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_outputs")
CLEANUP_AGE_MINUTES = 30
MAX_WORKERS = 6
MAX_PAGES_TO_EXTRACT = 200
CACHE_ENABLED = True
OCR_ENABLED = OCR_AVAILABLE

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Thread pools for parallel processing
io_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# Cache for repeated conversions with TTL
conversion_cache = {}
CACHE_TTL_SECONDS = 3600  # 1 hour

ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif', '.gif'}
ALLOWED_PDF_EXT = {'.pdf'}
ALLOWED_WORD_EXT = {'.docx', '.doc'}
ALLOWED_TEXT_EXT = {'.txt'}

# -----------------------------------------------------------------------------
# Performance optimization utilities
# -----------------------------------------------------------------------------
class UltraFastProcessor:
    """Optimized processor for ultra-fast conversions"""
    
    @staticmethod
    def clean_text_for_xml(text):
        """Ultra-fast text cleaning with regex compilation"""
        if not text:
            return ""
        
        # Pre-compiled regex patterns
        control_chars = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')
        
        # Fast operations
        text = text.replace('\x00', '')
        text = control_chars.sub('', text)
        
        # Fast Unicode replacements
        replacements = [
            ('\u2028', ' '),
            ('\u2029', ' '),
            ('\uFEFF', ''),
        ]
        
        for old, new in replacements:
            text = text.replace(old, new)
        
        return text
    
    @staticmethod
    def fast_extract_text(pdf_path, use_ocr=False):
        """Ultra-fast text extraction with intelligent fallback and OCR support"""
        start_time = time.time()
        
        # Check cache first
        if CACHE_ENABLED:
            file_hash = hashlib.md5(pdf_path.encode()).hexdigest() + "_" + str(use_ocr)
            if file_hash in conversion_cache:
                cache_time, text = conversion_cache[file_hash]
                if time.time() - cache_time < CACHE_TTL_SECONDS:
                    return text
        
        # Determine extraction strategy
        file_size = os.path.getsize(pdf_path)
        
        # Strategy 1: Try regular extraction first (for text-based PDFs)
        try:
            with open(pdf_path, 'rb') as file:
                reader = PdfReader(file)
                text = []
                for i, page in enumerate(reader.pages[:MAX_PAGES_TO_EXTRACT]):
                    page_text = page.extract_text()
                    if page_text and len(page_text.strip()) > 50:  # Check if meaningful text
                        text.append(page_text)
                
                if text and len("".join(text).strip()) > 100:  # If enough text found
                    result = "\n".join(text)
                    if CACHE_ENABLED:
                        conversion_cache[file_hash] = (time.time(), result)
                    return result
        except:
            pass
        
        # Strategy 2: If no/insufficient text or OCR requested, use OCR
        if OCR_ENABLED and (use_ocr or file_size < 50 * 1024 * 1024):  # OCR for < 50MB files
            try:
                # Check if it's a scanned PDF by trying to extract text again
                has_text = False
                try:
                    small_text = extract_text(pdf_path, maxpages=2, caching=True) or ""
                    if len(small_text.strip()) > 100:
                        has_text = True
                except:
                    pass
                
                # If little text and OCR is available/requested
                if not has_text or use_ocr:
                    result = UltraFastProcessor._fast_ocr_extraction(pdf_path)
                    if result and len(result.strip()) > 50:
                        if CACHE_ENABLED:
                            conversion_cache[file_hash] = (time.time(), result)
                        return result
            except Exception as e:
                print(f"OCR extraction attempt failed: {e}")
        
        # Strategy 3: Optimized pdfminer as final fallback
        try:
            result = extract_text(
                pdf_path,
                maxpages=MAX_PAGES_TO_EXTRACT,
                caching=True,
                laparams=None
            ) or ""
            if CACHE_ENABLED:
                conversion_cache[file_hash] = (time.time(), result)
            return result
        except:
            return ""
    
    @staticmethod
    def _parallel_pdf_extraction(pdf_path):
        """Parallel text extraction optimized for speed"""
        try:
            with open(pdf_path, 'rb') as file:
                reader = PdfReader(file)
                total_pages = len(reader.pages)
                
                # Process pages in chunks
                chunk_size = 10
                chunks = [range(i, min(i + chunk_size, total_pages)) 
                         for i in range(0, min(total_pages, MAX_PAGES_TO_EXTRACT), chunk_size)]
                
                def process_chunk(chunk_range):
                    chunk_text = []
                    for i in chunk_range:
                        try:
                            page_text = reader.pages[i].extract_text()
                            if page_text:
                                chunk_text.append(page_text)
                        except:
                            pass
                    return "\n".join(chunk_text)
                
                # Process chunks in parallel
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = [executor.submit(process_chunk, chunk) for chunk in chunks]
                    results = [f.result() for f in concurrent.futures.as_completed(futures)]
                
                return "\n\n".join(filter(None, results))
        except:
            return ""
    
    @staticmethod
    def _fast_ocr_extraction(pdf_path, languages=['eng'], page_limit=50):
        """Fast OCR extraction with parallel processing"""
        if not OCR_ENABLED:
            return ""
        
        try:
            # Convert PDF to images with error handling
            try:
                images = convert_from_bytes(
                    open(pdf_path, 'rb').read(),
                    dpi=200,  # Balance speed and quality
                    thread_count=2,
                    fmt='jpeg',
                    size=(1650, None),
                    first_page=1,
                    last_page=page_limit  # Limit for performance
                )
            except Exception as e:
                print(f"PDF to image conversion failed: {e}")
                # Try alternative method
                images = convert_from_path(
                    pdf_path,
                    dpi=200,
                    thread_count=1,
                    fmt='jpeg',
                    size=(1650, None),
                    first_page=1,
                    last_page=page_limit
                )
            
            if not images:
                return ""
            
            # Process images in parallel
            def ocr_image(img):
                try:
                    # Preprocess image for better OCR
                    img = ImageOps.exif_transpose(img)
                    img = img.convert('L')  # Grayscale
                    
                    # Apply enhancements
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(1.3)
                    img = img.filter(ImageFilter.SHARPEN)
                    
                    # Use pytesseract with optimized settings
                    return pytesseract.image_to_string(
                        img,
                        lang='+'.join(languages),
                        config='--psm 1 --oem 3 -c preserve_interword_spaces=1'
                    )
                except Exception as e:
                    print(f"OCR on single image failed: {e}")
                    return ""
            
            # Parallel OCR processing with error handling
            with ThreadPoolExecutor(max_workers=min(4, len(images))) as executor:
                futures = [executor.submit(ocr_image, img) for img in images]
                texts = []
                for future in concurrent.futures.as_completed(futures):
                    try:
                        text = future.result(timeout=30)
                        if text and text.strip():
                            texts.append(text.strip())
                    except:
                        pass
            
            return "\n\n".join(texts) if texts else ""
        except Exception as e:
            print(f"OCR extraction error: {e}")
            return ""
    
    @staticmethod
    def is_image_pdf(pdf_path):
        """Detect if PDF is image-based (scanned)"""
        try:
            # Try to extract text from first few pages
            text = extract_text(pdf_path, maxpages=3, caching=True) or ""
            
            # Check if we got meaningful text
            if len(text.strip()) < 100:
                return True
            
            # Count alphabetic characters vs total characters
            alpha_chars = sum(1 for c in text if c.isalpha())
            total_chars = len(text)
            
            if total_chars > 0 and alpha_chars / total_chars < 0.3:  # Less than 30% alphabetic
                return True
            
            return False
        except:
            return True  # Assume image PDF if extraction fails
    
    @staticmethod
    def optimize_image_for_pdf(image_path, max_size=(2480, 3508)):  # A4 at 300 DPI
        """Optimize image for PDF conversion"""
        try:
            with Image.open(image_path) as img:
                # Convert to RGB if needed
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                
                # Resize if too large
                img.thumbnail(max_size, Image.Resampling.LANCZOS)
                
                # Optimize in memory
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                buffer.seek(0)
                return Image.open(buffer)
        except:
            return None

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
        abort(Response(f"File too large (max {MAX_CONTENT_LENGTH // (1024*1024)} MB).", status=400))

def generate_unique_filename(original_filename, suffix=""):
    """Generate a unique filename with UUID and timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:12]
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
    """Fast cleanup with bulk operations"""
    cutoff = datetime.utcnow() - timedelta(minutes=CLEANUP_AGE_MINUTES)
    
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        try:
            for name in os.listdir(base):
                path = os.path.join(base, name)
                try:
                    mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
                    if mtime < cutoff:
                        if os.path.isdir(path):
                            shutil.rmtree(path, ignore_errors=True)
                        else:
                            os.remove(path)
                except:
                    pass
        except:
            pass

def safe_add_paragraph(doc, text):
    """Safely add a paragraph to a Word document"""
    try:
        cleaned_text = UltraFastProcessor.clean_text_for_xml(text)
        if cleaned_text.strip():
            doc.add_paragraph(cleaned_text.strip())
    except:
        pass

def parse_pages(pages_str):
    """Fast page parsing with set operations"""
    pages = set()
    if not pages_str:
        return pages
    
    parts = [p.strip() for p in pages_str.split(',') if p.strip()]
    for part in parts:
        if '-' in part:
            try:
                a, b = map(int, part.split('-', 1))
                pages.update(range(min(a, b), max(a, b) + 1))
            except:
                abort(Response("Invalid page range.", status=400))
        else:
            try:
                pages.add(int(part))
            except:
                abort(Response("Invalid page number.", status=400))
    return pages

def safe_remove(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except:
        pass

def safe_remove_all(paths):
    for path in paths:
        safe_remove(path)

def wrap_text(text, max_chars=95):
    """Fast text wrapping"""
    if len(text) <= max_chars:
        return [text]
    
    words = text.split(' ')
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        word_length = len(word)
        if current_length + word_length + (1 if current_line else 0) <= max_chars:
            current_line.append(word)
            current_length += word_length + (1 if current_line else 0)
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
            current_length = word_length
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines

# -----------------------------------------------------------------------------
# SPA Routes for each tool page
# -----------------------------------------------------------------------------

@app.route('/')
@app.route('/index')
@app.route('/index.html')
def index():
    return render_template('index.html')

@app.route('/split')
@app.route('/split.html')
def split_pdf():
    return render_template('split.html')

@app.route('/mergepdf')
@app.route('/mergepdf.html')
def merge_pdf():
    return render_template('mergepdf.html')

@app.route('/deletepdf')
@app.route('/deletepdf.html')
def delete_pdf():
    return render_template('deletepdf.html')

@app.route('/rotatepdf')
@app.route('/rotatepdf.html')
def rotate_pdf():
    return render_template('rotatepdf.html')

@app.route('/pdftoword')
@app.route('/pdftoword.html')
def pdf_to_word():
    return render_template('pdftoword.html')

@app.route('/lockpdf')
@app.route('/lockpdf.html')
def lock_pdf():
    return render_template('lockpdf.html')

@app.route('/unlockpdf')
@app.route('/unlockpdf.html')
def unlock_pdf():
    return render_template('unlockpdf.html')

@app.route('/wordtopdf')
@app.route('/wordtopdf.html')
def word_to_pdf():
    return render_template('wordtopdf.html')

@app.route('/mergeword')
@app.route('/mergeword.html')
def merge_word():
    return render_template('mergeword.html')

@app.route('/wordtotext')
@app.route('/wordtotext.html')
def word_to_text():
    return render_template('wordtotext.html')

@app.route('/texttopdf')
@app.route('/texttopdf.html')
def text_to_pdf():
    return render_template('texttopdf.html')

@app.route('/texttoword')
@app.route('/texttoword.html')
def text_to_word():
    return render_template('texttoword.html')

@app.route('/imagestopdf')
@app.route('/imagestopdf.html')
def images_to_pdf():
    return render_template('imagestopdf.html')

# New OCR route
@app.route('/ocrpdf')
@app.route('/ocrpdf.html')
def ocr_pdf():
    return render_template('ocrpdf.html')

# -----------------------------------------------------------------------------
# Catch-all route for other .html files
# -----------------------------------------------------------------------------
@app.route('/<path:filename>.html')
def serve_html(filename):
    try:
        return render_template(f'{filename}.html')
    except:
        abort(404)

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
        return jsonify({"error": "Please provide name, email, and message."}), 400
    return jsonify({"status": "ok", "received": {"name": name, "email": email}}), 200

# -----------------------------------------------------------------------------
# Tool APIs - PDF Operations (ULTRA-FAST)
# -----------------------------------------------------------------------------

@app.route('/api/merge-pdf', methods=['POST'])
def api_merge_pdf():
    """Ultra-fast PDF merging"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) < 2:
        return jsonify({"error": "Upload at least two PDFs."}), 400
    
    # Save files in parallel
    paths = save_uploads(files)
    
    # Validate all are PDFs
    for p in paths:
        if ext_of(p) not in ALLOWED_PDF_EXT:
            safe_remove_all(paths)
            return jsonify({"error": "Only PDF files are allowed."}), 400

    try:
        # Merge PDFs in memory
        merger = PdfMerger()
        for p in paths:
            merger.append(p, import_outline=False)  # Disable outline for speed
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "merged")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        buffer = io.BytesIO()
        merger.write(buffer)
        buffer.seek(0)
        merger.close()
        
        # Prepare response
        response = send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )
        
        # Cleanup
        @after_this_request
        def cleanup(response):
            safe_remove_all(paths)
            return response
        
        print(f"Merged {len(files)} PDFs in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove_all(paths)
        return jsonify({"error": f"Merging failed: {str(e)}"}), 500

@app.route('/api/split-pdf', methods=['POST'])
def api_split_pdf():
    """Ultra-fast PDF splitting"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF."}), 400
    
    ranges_str = request.form.get('ranges', '').strip()
    if not ranges_str:
        return jsonify({"error": "Page ranges are required."}), 400
    
    # Save file
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400
    
    try:
        # Read PDF once
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
            total_pages = len(reader.pages)
        
        # Parse ranges
        ranges = []
        parts = [p.strip() for p in ranges_str.split(',') if p.strip()]
        for part in parts:
            if '-' in part:
                try:
                    start, end = map(int, part.split('-', 1))
                    if 1 <= start <= total_pages and 1 <= end <= total_pages:
                        ranges.append((min(start, end)-1, max(start, end)))
                    else:
                        raise ValueError
                except:
                    safe_remove(pdf_path)
                    return jsonify({"error": f"Page range out of bounds (1-{total_pages})."}), 400
            else:
                try:
                    page = int(part)
                    if 1 <= page <= total_pages:
                        ranges.append((page-1, page))
                    else:
                        raise ValueError
                except:
                    safe_remove(pdf_path)
                    return jsonify({"error": f"Page out of bounds (1-{total_pages})."}), 400
        
        # Create ZIP in memory with parallel processing
        zip_buffer = io.BytesIO()
        
        def create_split(range_idx, start_idx, end_page):
            writer = PdfWriter()
            for page_idx in range(start_idx, end_page):
                writer.add_page(reader.pages[page_idx])
            
            split_buffer = io.BytesIO()
            writer.write(split_buffer)
            writer.close()
            split_buffer.seek(0)
            
            original_name = secure_filename(files[0].filename)
            split_name = generate_unique_filename(original_name, f"split_{range_idx+1}")
            split_name = os.path.splitext(split_name)[0] + ".pdf"
            
            return split_name, split_buffer.getvalue()
        
        # Process splits in parallel
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = []
                for i, (start_idx, end_page) in enumerate(ranges):
                    future = executor.submit(create_split, i, start_idx, end_page)
                    futures.append(future)
                
                for future in concurrent.futures.as_completed(futures):
                    split_name, split_data = future.result()
                    zipf.writestr(split_name, split_data)
        
        zip_buffer.seek(0)
        original_name = secure_filename(files[0].filename)
        zip_name = generate_unique_filename(original_name, "split_parts")
        zip_name = os.path.splitext(zip_name)[0] + ".zip"
        
        response = send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=zip_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(pdf_path)
            return response
        
        print(f"Split PDF into {len(ranges)} parts in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(pdf_path)
        return jsonify({"error": f"Splitting failed: {str(e)}"}), 500

@app.route('/api/delete-pages-pdf', methods=['POST'])
def api_delete_pages_pdf():
    """Ultra-fast page deletion"""
    start_time = time.time()
    cleanup_temp()
    
    pages_str = request.form.get('pages', '').strip()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF."}), 400
    if not pages_str:
        return jsonify({"error": "Pages to remove are required."}), 400
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400

    try:
        # Read and process in one pass
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
        
        pages_to_remove = parse_pages(pages_str)
        
        writer = PdfWriter()
        for i, page in enumerate(reader.pages):
            if (i + 1) not in pages_to_remove:
                writer.add_page(page)
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "pages_removed")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        writer.close()
        
        response = send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(pdf_path)
            return response
        
        print(f"Deleted pages in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(pdf_path)
        return jsonify({"error": f"Page removal failed: {str(e)}"}), 500

@app.route('/api/rotate-pdf', methods=['POST'])
def api_rotate_pdf():
    """Ultra-fast PDF rotation"""
    start_time = time.time()
    cleanup_temp()
    
    rotation = int(request.form.get('rotation', '90'))
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF."}), 400
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400

    try:
        # Read and rotate in one pass
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
        
        writer = PdfWriter()
        for page in reader.pages:
            page.rotate(rotation)
            writer.add_page(page)
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, f"rotated_{rotation}")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        writer.close()
        
        response = send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(pdf_path)
            return response
        
        print(f"Rotated PDF in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(pdf_path)
        return jsonify({"error": f"Rotation failed: {str(e)}"}), 500

@app.route('/api/lock-pdf', methods=['POST'])
def api_lock_pdf():
    """Ultra-fast PDF encryption"""
    start_time = time.time()
    cleanup_temp()
    
    pin = request.form.get('pin', '').strip()
    if not pin or len(pin) != 4 or not pin.isdigit():
        return jsonify({"error": "PIN must be exactly 4 digits."}), 400
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF."}), 400
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400

    try:
        # Read and encrypt in one pass
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
        
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        
        # Encrypt with fast settings
        writer.encrypt(
            user_password=pin,
            owner_password=None,
            use_128bit=True,
            permissions_flag=0
        )
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "locked")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        writer.close()
        
        response = send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(pdf_path)
            return response
        
        print(f"Locked PDF in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(pdf_path)
        return jsonify({"error": f"Locking failed: {str(e)}"}), 500

@app.route('/api/unlock-pdf', methods=['POST'])
def api_unlock_pdf():
    """Ultra-fast PDF decryption"""
    start_time = time.time()
    cleanup_temp()
    
    password = request.form.get('password', '').strip()
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF."}), 400
    if not password:
        return jsonify({"error": "Password is required."}), 400
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400

    try:
        # Read and decrypt
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
        
        if reader.is_encrypted:
            if not reader.decrypt(password):
                safe_remove(pdf_path)
                return jsonify({"error": "Incorrect password."}), 400
        
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "unlocked")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        buffer = io.BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        writer.close()
        
        response = send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(pdf_path)
            return response
        
        print(f"Unlocked PDF in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(pdf_path)
        return jsonify({"error": f"Unlocking failed: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# OCR PDF API (Backend OCR - Recommended & Correct)
# -----------------------------------------------------------------------------

@app.route('/api/ocr-pdf', methods=['POST'])
def api_ocr_pdf():
    """Backend OCR processing - Industry standard approach"""
    if not OCR_ENABLED:
        return jsonify({"error": "OCR is not available. Please install required packages."}), 400
    
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF or image."}), 400
    
    language = request.form.get('language', 'eng').strip().lower()
    output_format = request.form.get('format', 'pdf').strip().lower()
    
    # Map language codes
    language_map = {
        'english': 'eng',
        'spanish': 'spa',
        'french': 'fra',
        'german': 'deu',
        'chinese': 'chi_sim',
        'arabic': 'ara',
        'russian': 'rus',
        'hindi': 'hin',
        'portuguese': 'por',
        'italian': 'ita'
    }
    
    lang_code = language_map.get(language, language)
    
    paths = save_uploads(files)
    file_path = paths[0]
    
    try:
        # Check if it's PDF or image
        is_pdf = ext_of(file_path) in ALLOWED_PDF_EXT
        is_image = ext_of(file_path) in ALLOWED_IMAGE_EXT
        
        if not (is_pdf or is_image):
            safe_remove(file_path)
            return jsonify({"error": "Only PDF or image files are allowed for OCR."}), 400
        
        # Process OCR
        if is_pdf:
            # Convert PDF to images
            images = convert_from_bytes(
                open(file_path, 'rb').read(),
                dpi=300,  # Good quality for OCR
                thread_count=2,
                fmt='jpeg',
                size=(2480, None)  # A4 size
            )
        else:
            # Load single image
            images = [Image.open(file_path)]
        
        # Process images in parallel
        def process_image(img):
            try:
                # Preprocess image
                img = ImageOps.exif_transpose(img)
                img = img.convert('L')  # Grayscale for better OCR
                
                # Apply image enhancement with PIL (no cv2)
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.5)
                enhancer = ImageEnhance.Sharpness(img)
                img = enhancer.enhance(1.2)
                img = img.filter(ImageFilter.SHARPEN)
                
                # Perform OCR
                text = pytesseract.image_to_string(
                    img,
                    lang=lang_code,
                    config='--psm 3 --oem 3 -c preserve_interword_spaces=1'
                )
                
                # Also get bounding boxes for PDF generation
                if output_format == 'pdf':
                    data = pytesseract.image_to_data(
                        img,
                        lang=lang_code,
                        config='--psm 3 --oem 3',
                        output_type=pytesseract.Output.DICT
                    )
                    return text, data
                return text, None
            except Exception as e:
                print(f"OCR processing error: {e}")
                return "", None
        
        # Parallel processing
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(process_image, images))
        
        # Combine results
        all_texts = [r[0] for r in results if r[0]]
        all_data = [r[1] for r in results if r[1] is not None]
        
        combined_text = "\n\n".join(all_texts)
        cleaned_text = UltraFastProcessor.clean_text_for_xml(combined_text)
        
        # Generate output based on format
        original_name = secure_filename(files[0].filename)
        
        if output_format == 'pdf':
            # Create searchable PDF
            output_name = generate_unique_filename(original_name, "ocr_searchable")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            # Create PDF with text layer
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            
            # Add OCR text as invisible layer
            c.setFont("Helvetica", 1)  # Very small font
            c.setFillColorRGB(1, 1, 1, alpha=0)  # Fully transparent
            
            # Simple text placement (for demo)
            y = height - 50
            for line in cleaned_text.split('\n'):
                if line.strip():
                    c.drawString(50, y, line.strip())
                    y -= 15
                    if y < 50:
                        c.showPage()
                        y = height - 50
            
            # Add original image as background
            if images:
                img_buffer = io.BytesIO()
                images[0].save(img_buffer, format='JPEG', quality=85)
                img_buffer.seek(0)
                c.drawImage(img_buffer, 0, 0, width=width, height=height)
            
            c.save()
            buffer.seek(0)
            
            mimetype = 'application/pdf'
            
        elif output_format == 'word':
            # Create Word document
            output_name = generate_unique_filename(original_name, "ocr_text")
            output_name = os.path.splitext(output_name)[0] + ".docx"
            
            doc = Document()
            if cleaned_text:
                # Add in chunks
                paragraphs = [p for p in cleaned_text.split('\n\n') if p.strip()]
                for para in paragraphs[:200]:  # Limit
                    safe_add_paragraph(doc, para)
            else:
                doc.add_paragraph("No text could be extracted via OCR.")
            
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            
        else:  # text
            # Create plain text
            output_name = generate_unique_filename(original_name, "ocr_text")
            output_name = os.path.splitext(output_name)[0] + ".txt"
            
            buffer = io.BytesIO(cleaned_text.encode('utf-8'))
            buffer.seek(0)
            
            mimetype = 'text/plain'
        
        response = send_file(
            buffer,
            mimetype=mimetype,
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(file_path)
            return response
        
        print(f"OCR processed in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(file_path)
        return jsonify({"error": f"OCR processing failed: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# Tool APIs - PDF to Word (ULTRA-FAST with automatic OCR detection)
# -----------------------------------------------------------------------------

@app.route('/api/pdf-to-word', methods=['POST'])
def api_pdf_to_word():
    """Ultra-fast PDF to Word with automatic OCR detection"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF."}), 400
    
    # Auto-detect if OCR is needed
    force_ocr = request.form.get('force_ocr', 'auto').lower()
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400

    try:
        # Auto-detect if OCR is needed
        use_ocr = False
        if force_ocr == 'true':
            use_ocr = True
        elif force_ocr == 'auto' and OCR_ENABLED:
            # Check if it's an image PDF
            use_ocr = UltraFastProcessor.is_image_pdf(pdf_path)
        
        # Extract text (with OCR if needed)
        text = UltraFastProcessor.fast_extract_text(pdf_path, use_ocr=use_ocr)
        
        # Generate output name
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted_to_word")
        output_name = os.path.splitext(output_name)[0] + ".docx"
        
        # Create document efficiently
        doc = Document()
        
        if text:
            # Process in chunks for speed
            paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
            
            # Limit for very large documents
            if len(paragraphs) > 300:
                paragraphs = paragraphs[:300]
                doc.add_paragraph("[Document truncated - showing first 300 paragraphs]")
            
            # Add paragraphs in batches
            for para in paragraphs:
                safe_add_paragraph(doc, para)
        else:
            doc.add_paragraph("No text could be extracted from this PDF.")
        
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        
        response = send_file(
            buffer,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(pdf_path)
            return response
        
        print(f"PDF to Word in {time.time() - start_time:.2f}s (OCR: {use_ocr})")
        return response
        
    except Exception as e:
        safe_remove(pdf_path)
        return jsonify({"error": f"Conversion failed: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# Tool APIs - Word Operations (ULTRA-FAST)
# -----------------------------------------------------------------------------

@app.route('/api/word-to-pdf', methods=['POST'])
def api_word_to_pdf():
    """Ultra-fast Word to PDF conversion"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one Word file."}), 400

    paths = save_uploads(files)
    doc_path = paths[0]

    if ext_of(doc_path) not in ALLOWED_WORD_EXT:
        safe_remove(doc_path)
        return jsonify({"error": "Only DOC/DOCX files are supported."}), 400

    try:
        # Fast text extraction
        doc = Document(doc_path)
        text_content = []
        for para in doc.paragraphs:
            if para.text.strip():
                cleaned = UltraFastProcessor.clean_text_for_xml(para.text)
                if cleaned.strip():
                    text_content.append(cleaned.strip())
        
        text = "\n".join(text_content[:500])  # Limit text
        
        # Create PDF
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted_to_pdf")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
        left_margin = 50
        top = height - 50
        line_height = 14
        
        if text:
            # Fast text rendering
            paragraphs = text.split('\n\n')
            for para in paragraphs[:100]:  # Limit
                if para.strip():
                    lines = wrap_text(para, max_chars=95)
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
        
        response = send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(doc_path)
            return response
        
        print(f"Word to PDF in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(doc_path)
        return jsonify({"error": f"Conversion failed: {str(e)}"}), 500

@app.route('/api/merge-word', methods=['POST'])
def api_merge_word():
    """Ultra-fast Word document merging"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) < 2:
        return jsonify({"error": "Upload at least two Word files."}), 400
    
    paths = save_uploads(files)
    for p in paths:
        if ext_of(p) not in ALLOWED_WORD_EXT:
            safe_remove_all(paths)
            return jsonify({"error": "Only DOC/DOCX files are allowed."}), 400

    try:
        # Merge documents efficiently
        merged = Document()
        
        for idx, doc_path in enumerate(paths):
            d = Document(doc_path)
            
            # Extract text efficiently
            paragraphs = []
            for para in d.paragraphs:
                if para.text.strip():
                    cleaned = UltraFastProcessor.clean_text_for_xml(para.text)
                    if cleaned.strip():
                        paragraphs.append(cleaned.strip())
            
            # Add to merged document with limits
            for para in paragraphs[:100]:  # Limit per document
                safe_add_paragraph(merged, para)
            
            # Add separator between documents
            if idx < len(paths) - 1:
                merged.add_paragraph("\n" + "=" * 50 + "\n")
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "merged")
        output_name = os.path.splitext(output_name)[0] + ".docx"
        
        buffer = io.BytesIO()
        merged.save(buffer)
        buffer.seek(0)
        
        response = send_file(
            buffer,
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove_all(paths)
            return response
        
        print(f"Merged {len(files)} Word docs in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove_all(paths)
        return jsonify({"error": f"Merging failed: {str(e)}"}), 500

@app.route('/api/word-to-text', methods=['POST'])
def api_word_to_text():
    """Ultra-fast Word to Text conversion"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one Word file."}), 400
    
    paths = save_uploads(files)
    doc_path = paths[0]
    
    if ext_of(doc_path) not in ALLOWED_WORD_EXT:
        safe_remove(doc_path)
        return jsonify({"error": "Only DOC/DOCX files are allowed."}), 400

    try:
        # Fast text extraction
        doc = Document(doc_path)
        text_content = []
        
        for para in doc.paragraphs:
            if para.text.strip():
                cleaned = UltraFastProcessor.clean_text_for_xml(para.text)
                if cleaned.strip():
                    text_content.append(cleaned)
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "extracted_text")
        output_name = os.path.splitext(output_name)[0] + ".txt"
        
        buffer = io.BytesIO('\n'.join(text_content).encode('utf-8'))
        buffer.seek(0)
        
        response = send_file(
            buffer,
            mimetype='text/plain',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove(doc_path)
            return response
        
        print(f"Word to Text in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove(doc_path)
        return jsonify({"error": f"Conversion failed: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# Tool APIs - Text Operations (ULTRA-FAST)
# -----------------------------------------------------------------------------

@app.route('/api/text-to-pdf', methods=['POST'])
def api_text_to_pdf():
    """Ultra-fast Text to PDF conversion"""
    start_time = time.time()
    
    text = (request.form.get('text') or '').strip()
    if not text:
        return jsonify({"error": "Text content is required."}), 400

    cleaned_text = UltraFastProcessor.clean_text_for_xml(text)
    
    unique_id = str(uuid.uuid4())[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"text_converted_{timestamp}_{unique_id}.pdf"

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    left_margin = 50
    top = height - 50
    line_height = 14
    
    # Fast text processing
    lines = cleaned_text.splitlines()[:500]  # Limit lines
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
    
    print(f"Text to PDF in {time.time() - start_time:.2f}s")
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=output_name
    )

@app.route('/api/text-to-word', methods=['POST'])
def api_text_to_word():
    """Ultra-fast Text to Word conversion"""
    start_time = time.time()
    
    text = (request.form.get('text') or '').strip()
    if not text:
        return jsonify({"error": "Text content is required."}), 400
    
    cleaned_text = UltraFastProcessor.clean_text_for_xml(text)
    
    unique_id = str(uuid.uuid4())[:12]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"text_converted_{timestamp}_{unique_id}.docx"
    
    doc = Document()
    
    if cleaned_text:
        lines = cleaned_text.splitlines()[:300]  # Limit lines
        for line in lines:
            if line.strip():
                safe_add_paragraph(doc, line)
    else:
        doc.add_paragraph("No text content provided.")
    
    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    
    print(f"Text to Word in {time.time() - start_time:.2f}s")
    
    return send_file(
        buffer,
        mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        as_attachment=True,
        download_name=output_name
    )

# -----------------------------------------------------------------------------
# Tool APIs - Images to PDF (ULTRA-FAST)
# -----------------------------------------------------------------------------

@app.route('/api/images-to-pdf', methods=['POST'])
def api_images_to_pdf():
    """Ultra-fast Images to PDF conversion"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) < 1:
        return jsonify({"error": "Upload at least one image."}), 400
    
    paths = save_uploads(files)
    
    # Validate all are images
    for p in paths:
        if ext_of(p) not in ALLOWED_IMAGE_EXT:
            safe_remove_all(paths)
            return jsonify({"error": "Only image files (JPG, PNG, WEBP, BMP, TIFF, GIF) are allowed."}), 400

    try:
        # Optimize images in parallel
        def optimize_image(image_path):
            return UltraFastProcessor.optimize_image_for_pdf(image_path)
        
        with ThreadPoolExecutor(max_workers=4) as executor:
            images = list(executor.map(optimize_image, paths))
        
        # Filter out None values
        images = [img for img in images if img is not None]
        
        if not images:
            safe_remove_all(paths)
            return jsonify({"error": "Failed to process images."}), 400
        
        # Create PDF
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "images_to_pdf")
        output_name = os.path.splitext(output_name)[0] + ".pdf"
        
        buffer = io.BytesIO()
        if len(images) == 1:
            images[0].save(buffer, format='PDF', save_all=True)
        else:
            first, rest = images[0], images[1:]
            first.save(buffer, format='PDF', save_all=True, append_images=rest)
        
        buffer.seek(0)
        
        response = send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=output_name
        )
        
        @after_this_request
        def cleanup(response):
            safe_remove_all(paths)
            return response
        
        print(f"Converted {len(images)} images to PDF in {time.time() - start_time:.2f}s")
        return response
        
    except Exception as e:
        safe_remove_all(paths)
        return jsonify({"error": f"Conversion failed: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# Health check endpoint
# -----------------------------------------------------------------------------
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ocr_available": OCR_ENABLED,
        "cache_size": len(conversion_cache)
    }), 200

# -----------------------------------------------------------------------------
# Error handlers
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"error": "Page not found. Please check the URL."}), 404

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"File too large (max {MAX_CONTENT_LENGTH // (1024*1024)} MB)."}), 413

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description) if e.description else "Bad request."}), 400

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error."}), 500

# -----------------------------------------------------------------------------
# Static file serving
# -----------------------------------------------------------------------------
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

# -----------------------------------------------------------------------------
# CORS Configuration
# -----------------------------------------------------------------------------
@app.after_request
def after_request(response):
    """Add CORS headers"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-Requested-With')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

# -----------------------------------------------------------------------------
# Cache management
# -----------------------------------------------------------------------------
def cleanup_cache():
    """Periodically clean old cache entries"""
    while True:
        time.sleep(300)  # Run every 5 minutes
        try:
            current_time = time.time()
            expired_keys = []
            
            for key, (cache_time, _) in list(conversion_cache.items()):
                if current_time - cache_time > CACHE_TTL_SECONDS:
                    expired_keys.append(key)
            
            for key in expired_keys:
                del conversion_cache[key]
            
            # Keep cache size manageable
            if len(conversion_cache) > 200:
                keys = list(conversion_cache.keys())[:-200]
                for key in keys:
                    del conversion_cache[key]
        except:
            pass

# Start cleanup thread
cache_cleaner = threading.Thread(target=cleanup_cache, daemon=True)
cache_cleaner.start()

# -----------------------------------------------------------------------------
# Install OCR dependencies instructions
# -----------------------------------------------------------------------------
def check_ocr_dependencies():
    """Check and report OCR dependencies"""
    if not OCR_AVAILABLE:
        print("\n" + "="*60)
        print("OCR FEATURE SETUP REQUIRED")
        print("="*60)
        print("\nFor OCR functionality, install these dependencies:")
        print("\n1. System dependencies (Ubuntu/Debian):")
        print("   sudo apt-get update")
        print("   sudo apt-get install -y tesseract-ocr")
        print("   sudo apt-get install -y libtesseract-dev")
        print("   sudo apt-get install -y poppler-utils")
        print("\n2. Python packages:")
        print("   pip install pytesseract")
        print("   pip install pdf2image")
        print("   pip install pillow")
        print("\n3. For Windows:")
        print("   Download and install Tesseract OCR:")
        print("   https://github.com/UB-Mannheim/tesseract/wiki")
        print("\n4. Set environment variable:")
        print("   export TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata/")
        print("="*60 + "\n")
    
    return OCR_AVAILABLE

# Check on startup
check_ocr_dependencies()

# -----------------------------------------------------------------------------
# Run the application
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    print(f"\n🚀 Starting iMasterPDF with ULTRA-FAST processing")
    print(f"   Max workers: {MAX_WORKERS}")
    print(f"   OCR enabled: {OCR_ENABLED}")
    print(f"   Cache enabled: {CACHE_ENABLED}")
    print(f"   Max pages to extract: {MAX_PAGES_TO_EXTRACT}")
    print(f"   Upload directory: {UPLOAD_DIR}")
    print(f"   Output directory: {OUTPUT_DIR}")
    
    app.run(host='0.0.0.0', port=8000, debug=False, threaded=True)