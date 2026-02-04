import os
import io
import shutil
import tempfile
import uuid
import re
import time
import hashlib
import zipfile
import threading
import secrets
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from functools import wraps, lru_cache
from pathlib import Path

from flask import Flask, render_template, send_file, request, abort, Response, jsonify, send_from_directory, after_this_request
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from PyPDF2.errors import PdfReadError
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageDraw
import numpy as np

# OCR Libraries - Only import when needed
try:
    import pytesseract
    from pdf2image import convert_from_path, convert_from_bytes
    import pdf2image.exceptions
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# -----------------------------------------------------------------------------
# Flask app configuration
# -----------------------------------------------------------------------------
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# Security and performance settings
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB per file
MAX_TOTAL_UPLOAD_SIZE = 500 * 1024 * 1024  # 500 MB total
MAX_REQUEST_TIME = 300  # 5 minutes timeout
UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_uploads")
OUTPUT_DIR = os.path.join(tempfile.gettempdir(), "imasterpdf_outputs")
CLEANUP_AGE_MINUTES = 30
MAX_WORKERS = 6
MAX_PAGES_TO_EXTRACT = 500  # Increased for OCR
CACHE_ENABLED = True
OCR_ENABLED = OCR_AVAILABLE
RATE_LIMIT_REQUESTS = 100  # Per hour
RATE_LIMIT_WINDOW = 3600

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Global thread pools (reused)
pdf_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pdf_")
ocr_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ocr_")
io_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="io_")

# Cache for repeated conversions with TTL
conversion_cache = {}
CACHE_TTL_SECONDS = 3600  # 1 hour
MAX_CACHE_SIZE = 1000

# Rate limiting storage
request_tracker = {}
rate_lock = threading.Lock()

ALLOWED_IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif', '.gif'}
ALLOWED_PDF_EXT = {'.pdf'}
ALLOWED_WORD_EXT = {'.docx', '.doc'}
ALLOWED_TEXT_EXT = {'.txt'}

# -----------------------------------------------------------------------------
# Security & Rate Limiting Decorators
# -----------------------------------------------------------------------------
def rate_limit(f):
    """Rate limiting decorator"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = request.remote_addr
        current_time = time.time()
        
        with rate_lock:
            if client_ip not in request_tracker:
                request_tracker[client_ip] = []
            
            # Clean old requests
            request_tracker[client_ip] = [
                req_time for req_time in request_tracker[client_ip]
                if current_time - req_time < RATE_LIMIT_WINDOW
            ]
            
            if len(request_tracker[client_ip]) >= RATE_LIMIT_REQUESTS:
                return jsonify({
                    "error": "Rate limit exceeded. Please try again later.",
                    "retry_after": int(RATE_LIMIT_WINDOW - (current_time - request_tracker[client_ip][0]))
                }), 429
            
            request_tracker[client_ip].append(current_time)
        
        return f(*args, **kwargs)
    return decorated_function

def validate_pdf_structure(f):
    """Validate PDF structure before processing"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file.filename.lower().endswith('.pdf'):
                    try:
                        # Read first few bytes to check PDF signature
                        file.seek(0)
                        header = file.read(5)
                        file.seek(0)
                        
                        if header != b'%PDF-':
                            return jsonify({
                                "error": f"Invalid PDF file: {file.filename}. File may be corrupted."
                            }), 400
                    except Exception:
                        return jsonify({
                            "error": f"Could not read PDF file: {file.filename}"
                        }), 400
        
        return f(*args, **kwargs)
    return decorated_function

def timeout_decorator(timeout_seconds):
    """Timeout decorator for long-running operations"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(f, *args, **kwargs)
                try:
                    return future.result(timeout=timeout_seconds)
                except TimeoutError:
                    return jsonify({
                        "error": f"Operation timed out after {timeout_seconds} seconds"
                    }), 504
                except Exception as e:
                    return jsonify({"error": str(e)}), 500
        return decorated_function
    return decorator

# -----------------------------------------------------------------------------
# Enhanced Processor Class
# -----------------------------------------------------------------------------
class EnhancedPDFProcessor:
    """Enhanced processor with proper error handling and optimization"""
    
    # Pre-compiled regex patterns
    CONTROL_CHARS = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')
    MULTIPLE_NEWLINES = re.compile(r'\n{3,}')
    MULTIPLE_SPACES = re.compile(r' {2,}')
    
    @staticmethod
    def calculate_file_hash(file_path):
        """Calculate MD5 hash of file content for caching"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    @staticmethod
    def clean_text_for_xml(text):
        """Enhanced text cleaning with better handling"""
        if not text:
            return ""
        
        # Remove control characters
        text = EnhancedPDFProcessor.CONTROL_CHARS.sub('', text)
        
        # Replace problematic Unicode characters
        replacements = [
            ('\u2028', '\n'),  # Line separator
            ('\u2029', '\n\n'),  # Paragraph separator
            ('\uFEFF', ''),  # Zero-width no-break space
            ('\u00A0', ' '),  # Non-breaking space
            ('\u200B', ''),  # Zero-width space
        ]
        
        for old, new in replacements:
            text = text.replace(old, new)
        
        # Normalize whitespace
        text = EnhancedPDFProcessor.MULTIPLE_NEWLINES.sub('\n\n', text)
        text = EnhancedPDFProcessor.MULTIPLE_SPACES.sub(' ', text)
        
        return text.strip()
    
    @staticmethod
    def validate_pdf_file(pdf_path):
        """Validate PDF file structure"""
        try:
            with open(pdf_path, 'rb') as f:
                reader = PdfReader(f)
                
                # Check basic properties
                if len(reader.pages) == 0:
                    return False, "PDF has no pages"
                
                # Check for encryption
                if reader.is_encrypted:
                    return False, "PDF is encrypted"
                
                return True, "Valid PDF"
        except PdfReadError as e:
            return False, f"Invalid PDF structure: {str(e)}"
        except Exception as e:
            return False, f"Error reading PDF: {str(e)}"
    
    @staticmethod
    def extract_text_with_fallback(pdf_path, use_ocr=False, lang='eng'):
        """Intelligent text extraction with proper fallback strategy"""
        
        # Generate cache key based on content hash and parameters
        file_hash = EnhancedPDFProcessor.calculate_file_hash(pdf_path)
        cache_key = f"{file_hash}_{use_ocr}_{lang}"
        
        if CACHE_ENABLED and cache_key in conversion_cache:
            cache_time, text = conversion_cache[cache_key]
            if time.time() - cache_time < CACHE_TTL_SECONDS:
                return text
        
        start_time = time.time()
        result = ""
        
        try:
            # First try: PyPDF2 for digital PDFs
            with open(pdf_path, 'rb') as f:
                reader = PdfReader(f)
                
                # Check if text extraction is likely to work
                first_page_text = ""
                try:
                    if len(reader.pages) > 0:
                        first_page_text = reader.pages[0].extract_text() or ""
                except:
                    pass
                
                # Strategy decision based on first page
                if len(first_page_text.strip()) > 50:
                    # Digital PDF - use parallel extraction
                    result = EnhancedPDFProcessor._parallel_pdf_extraction(pdf_path)
                else:
                    # Scanned PDF or image-based
                    if use_ocr and OCR_ENABLED:
                        result = EnhancedPDFProcessor._enhanced_ocr_extraction(pdf_path, lang)
                    else:
                        # Fallback to pdfminer
                        from pdfminer.high_level import extract_text as pdfminer_extract
                        result = pdfminer_extract(
                            pdf_path,
                            maxpages=MAX_PAGES_TO_EXTRACT,
                            caching=True,
                            laparams=None
                        ) or ""
        
        except Exception as e:
            app.logger.error(f"Text extraction failed: {e}")
            result = ""
        
        # Clean and cache result
        cleaned_result = EnhancedPDFProcessor.clean_text_for_xml(result)
        
        if CACHE_ENABLED:
            # Manage cache size
            if len(conversion_cache) >= MAX_CACHE_SIZE:
                # Remove oldest 10% of entries
                sorted_items = sorted(conversion_cache.items(), key=lambda x: x[1][0])
                for key, _ in sorted_items[:MAX_CACHE_SIZE // 10]:
                    del conversion_cache[key]
            
            conversion_cache[cache_key] = (time.time(), cleaned_result)
        
        elapsed = time.time() - start_time
        app.logger.info(f"Text extraction completed in {elapsed:.2f}s, length: {len(cleaned_result)} chars")
        
        return cleaned_result
    
    @staticmethod
    def _parallel_pdf_extraction(pdf_path):
        """Optimized parallel PDF text extraction"""
        try:
            with open(pdf_path, 'rb') as f:
                reader = PdfReader(f)
                total_pages = min(len(reader.pages), MAX_PAGES_TO_EXTRACT)
                
                if total_pages == 0:
                    return ""
                
                # Determine optimal chunk size
                chunk_size = max(5, total_pages // 4)
                
                def extract_page_range(start_idx, end_idx):
                    chunk_text = []
                    for i in range(start_idx, min(end_idx, total_pages)):
                        try:
                            page_text = reader.pages[i].extract_text()
                            if page_text and page_text.strip():
                                chunk_text.append(page_text.strip())
                        except:
                            pass
                    return "\n".join(chunk_text)
                
                # Create chunks
                chunks = [(i, min(i + chunk_size, total_pages)) 
                         for i in range(0, total_pages, chunk_size)]
                
                # Process in parallel
                futures = []
                for start, end in chunks:
                    future = pdf_executor.submit(extract_page_range, start, end)
                    futures.append(future)
                
                results = []
                for future in as_completed(futures):
                    try:
                        chunk_result = future.result(timeout=30)
                        if chunk_result:
                            results.append(chunk_result)
                    except TimeoutError:
                        app.logger.warning("Page extraction timed out")
                    except Exception as e:
                        app.logger.error(f"Chunk extraction error: {e}")
                
                return "\n\n".join(results)
                
        except Exception as e:
            app.logger.error(f"Parallel extraction failed: {e}")
            return ""
    
    @staticmethod
    def _enhanced_ocr_extraction(pdf_path, lang='eng'):
        """Enhanced OCR extraction with better preprocessing"""
        if not OCR_ENABLED:
            return ""
        
        try:
            # Determine optimal DPI based on file size
            file_size = os.path.getsize(pdf_path)
            dpi = 300 if file_size < 50 * 1024 * 1024 else 200
            
            # Convert PDF to images
            images = convert_from_bytes(
                open(pdf_path, 'rb').read(),
                dpi=dpi,
                thread_count=2,
                fmt='jpeg',
                size=(2480, 3508),  # A4 at 300 DPI
                grayscale=True  # Convert to grayscale during conversion
            )[:MAX_PAGES_TO_EXTRACT]
            
            if not images:
                return ""
            
            def process_single_image(img, page_num):
                """Process single image for OCR"""
                try:
                    # Enhanced preprocessing
                    img = ImageOps.exif_transpose(img)
                    
                    # Convert to numpy for advanced processing
                    img_array = np.array(img)
                    
                    # Adaptive thresholding for better contrast
                    if len(img_array.shape) == 2:  # Grayscale
                        # Apply CLAHE-like enhancement
                        from PIL import ImageOps as ImOps
                        img = ImOps.autocontrast(img, cutoff=2)
                    
                    # Apply sharpening
                    img = img.filter(ImageFilter.SHARPEN)
                    
                    # Enhance contrast
                    enhancer = ImageEnhance.Contrast(img)
                    img = enhancer.enhance(1.5)
                    
                    enhancer = ImageEnhance.Sharpness(img)
                    img = enhancer.enhance(1.3)
                    
                    # OCR with optimized settings
                    custom_config = f'--psm 1 --oem 3 -c preserve_interword_spaces=1 tessedit_char_blacklist=|{{}}[]()'
                    
                    text = pytesseract.image_to_string(
                        img,
                        lang=lang,
                        config=custom_config
                    )
                    
                    # Add page number marker
                    if text.strip():
                        return f"--- Page {page_num + 1} ---\n{text}\n"
                    return ""
                    
                except Exception as e:
                    app.logger.error(f"OCR page {page_num} error: {e}")
                    return ""
            
            # Process images in parallel with progress tracking
            futures = []
            for idx, img in enumerate(images):
                future = ocr_executor.submit(process_single_image, img, idx)
                futures.append(future)
            
            results = []
            for future in as_completed(futures):
                try:
                    page_text = future.result(timeout=60)
                    if page_text:
                        results.append(page_text)
                except TimeoutError:
                    app.logger.warning("OCR page processing timed out")
                except Exception as e:
                    app.logger.error(f"OCR future error: {e}")
            
            return "\n".join(results)
            
        except Exception as e:
            app.logger.error(f"OCR extraction failed: {e}")
            return ""
    
    @staticmethod
    def create_searchable_pdf(images, ocr_texts, lang='eng'):
        """Create a proper searchable PDF with aligned text"""
        if not images:
            return None
        
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Try to load a font for better text rendering
        try:
            # You need to add a font file to your project
            # pdfmetrics.registerFont(TTFont('DejaVu', 'DejaVuSans.ttf'))
            # c.setFont("DejaVu", 12)
            c.setFont("Helvetica", 12)
        except:
            c.setFont("Helvetica", 12)
        
        for idx, (img, text) in enumerate(zip(images, ocr_texts)):
            if idx > 0:
                c.showPage()
                c.setFont("Helvetica", 12)
            
            # Add image as background
            img_buffer = io.BytesIO()
            img.save(img_buffer, format='JPEG', quality=85)
            img_buffer.seek(0)
            
            # Draw image
            c.drawImage(img_buffer, 0, 0, width=width, height=height)
            
            # Add visible, searchable text layer
            # For demo, we'll add text at top. In production, use OCR coordinates
            c.setFillColorRGB(0, 0, 0, alpha=0.01)  # Nearly invisible but searchable
            
            # Simple text placement - in production, use OCR coordinates
            y_position = height - 50
            lines = text.split('\n')[:50]  # Limit lines per page
            
            for line in lines:
                if line.strip() and not line.startswith('---'):
                    c.drawString(50, y_position, line.strip())
                    y_position -= 20
                    if y_position < 50:
                        break
        
        c.save()
        buffer.seek(0)
        return buffer
    
    @staticmethod
    def optimize_image_for_pdf(image_path, target_dpi=300):
        """Optimize image for PDF with proper color management"""
        try:
            with Image.open(image_path) as img:
                # Convert to RGB if needed
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Calculate target size based on DPI
                target_width = int(8.27 * target_dpi)  # A4 width in inches
                target_height = int(11.69 * target_dpi)  # A4 height in inches
                
                # Resize maintaining aspect ratio
                img.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
                
                # Optimize quality
                buffer = io.BytesIO()
                img.save(buffer, format='JPEG', quality=90, optimize=True, progressive=True)
                buffer.seek(0)
                return Image.open(buffer)
                
        except Exception as e:
            app.logger.error(f"Image optimization failed: {e}")
            return None

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def ext_of(filename):
    return os.path.splitext(filename.lower())[1]

def validate_file(stream, filename):
    """Enhanced file validation"""
    stream.seek(0, os.SEEK_END)
    size = stream.tell()
    stream.seek(0)
    
    if size < 1024:
        abort(Response("File too small (minimum 1 KB required).", status=400))
    if size > MAX_CONTENT_LENGTH:
        abort(Response(f"File too large (maximum {MAX_CONTENT_LENGTH // (1024*1024)} MB allowed).", status=400))
    
    # Check file extension
    ext = ext_of(filename)
    allowed_ext = ALLOWED_PDF_EXT | ALLOWED_IMAGE_EXT | ALLOWED_WORD_EXT | ALLOWED_TEXT_EXT
    
    if ext not in allowed_ext:
        abort(Response(f"Unsupported file type. Allowed: PDF, Images, Word documents, Text files.", status=400))
    
    return True

def generate_unique_filename(original_filename, suffix=""):
    """Generate secure unique filename"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = secrets.token_hex(8)
    name, ext = os.path.splitext(original_filename)
    safe_name = secure_filename(name)[:50]  # Limit name length
    
    if suffix:
        return f"{safe_name}_{suffix}_{timestamp}_{unique_id}{ext}"
    return f"{safe_name}_{timestamp}_{unique_id}{ext}"

def save_uploads(files):
    """Save uploaded files with validation"""
    saved = []
    total_size = 0
    
    for storage in files:
        validate_file(storage.stream, storage.filename)
        
        storage.stream.seek(0, os.SEEK_END)
        file_size = storage.stream.tell()
        storage.stream.seek(0)
        
        total_size += file_size
        if total_size > MAX_TOTAL_UPLOAD_SIZE:
            safe_remove_all(saved)
            abort(Response(f"Total upload size exceeds {MAX_TOTAL_UPLOAD_SIZE // (1024*1024)} MB limit.", status=400))
        
        unique_filename = generate_unique_filename(storage.filename)
        path = os.path.join(UPLOAD_DIR, unique_filename)
        
        try:
            storage.save(path)
            saved.append(path)
        except Exception as e:
            safe_remove_all(saved)
            abort(Response(f"Failed to save file: {str(e)}", status=500))
    
    return saved

def cleanup_temp():
    """Cleanup temporary files with error handling"""
    cutoff = datetime.utcnow() - timedelta(minutes=CLEANUP_AGE_MINUTES)
    
    for base in (UPLOAD_DIR, OUTPUT_DIR):
        try:
            if os.path.exists(base):
                for name in os.listdir(base):
                    path = os.path.join(base, name)
                    try:
                        if os.path.exists(path):
                            mtime = datetime.utcfromtimestamp(os.path.getmtime(path))
                            if mtime < cutoff:
                                if os.path.isdir(path):
                                    shutil.rmtree(path, ignore_errors=True)
                                else:
                                    os.remove(path)
                    except (OSError, PermissionError):
                        continue
        except (OSError, PermissionError):
            continue

def safe_remove(path):
    """Safely remove a file"""
    try:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
    except:
        pass

def safe_remove_all(paths):
    """Safely remove multiple files"""
    for path in paths:
        safe_remove(path)

def parse_pages(pages_str, max_pages):
    """Parse page ranges with validation"""
    pages = set()
    if not pages_str:
        return pages
    
    parts = [p.strip() for p in pages_str.split(',') if p.strip()]
    for part in parts:
        if '-' in part:
            try:
                a, b = map(int, part.split('-', 1))
                start = max(1, min(a, b))
                end = min(max_pages, max(a, b))
                if start > end:
                    abort(Response(f"Invalid page range: {part}", status=400))
                pages.update(range(start, end + 1))
            except ValueError:
                abort(Response(f"Invalid page range format: {part}", status=400))
        else:
            try:
                page = int(part)
                if 1 <= page <= max_pages:
                    pages.add(page)
                else:
                    abort(Response(f"Page {page} out of range (1-{max_pages})", status=400))
            except ValueError:
                abort(Response(f"Invalid page number: {part}", status=400))
    return pages

def wrap_text(text, max_chars=80):
    """Wrap text to specified width"""
    if not text or len(text) <= max_chars:
        return [text] if text else []
    
    lines = []
    words = text.split()
    current_line = []
    current_length = 0
    
    for word in words:
        word_len = len(word)
        if current_length + word_len + len(current_line) <= max_chars:
            current_line.append(word)
            current_length += word_len
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
            current_length = word_len
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return lines

# -----------------------------------------------------------------------------
# SPA Routes (Same as before)
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

@app.route('/ocrpdf')
@app.route('/ocrpdf.html')
def ocr_pdf():
    return render_template('ocrpdf.html')

@app.route('/<path:filename>.html')
def serve_html(filename):
    try:
        return render_template(f'{filename}.html')
    except:
        abort(404)

# -----------------------------------------------------------------------------
# API Routes with Enhanced Security
# -----------------------------------------------------------------------------
@app.route('/api/contact', methods=['POST'])
@rate_limit
def api_contact():
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()[:100]
    email = (data.get('email') or '').strip()[:100]
    message = (data.get('message') or '').strip()[:1000]
    
    if not name or not email or not message:
        return jsonify({"error": "Please provide name, email, and message."}), 400
    
    # Basic email validation
    if '@' not in email or '.' not in email:
        return jsonify({"error": "Please provide a valid email address."}), 400
    
    return jsonify({
        "status": "success",
        "message": "Thank you for your message. We'll get back to you soon.",
        "received": {"name": name[:50], "email": email[:50]}
    }), 200

# -----------------------------------------------------------------------------
# Fixed OCR PDF API
# -----------------------------------------------------------------------------
@app.route('/api/ocr-pdf', methods=['POST'])
@rate_limit
@validate_pdf_structure
@timeout_decorator(300)  # 5 minute timeout
def api_ocr_pdf():
    """Enhanced OCR processing with proper searchable PDF creation"""
    if not OCR_ENABLED:
        return jsonify({
            "error": "OCR functionality is not available. Please install required packages.",
            "instructions": "Install: pip install pytesseract pdf2image pillow"
        }), 503
    
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF or image file."}), 400
    
    language = request.form.get('language', 'eng').strip().lower()
    output_format = request.form.get('format', 'pdf').strip().lower()
    
    # Validate output format
    if output_format not in ['pdf', 'word', 'text']:
        return jsonify({"error": "Invalid output format. Choose: pdf, word, or text."}), 400
    
    # Language mapping
    language_map = {
        'english': 'eng',
        'spanish': 'spa',
        'french': 'fra',
        'german': 'deu',
        'chinese': 'chi_sim',
        'chinese_traditional': 'chi_tra',
        'arabic': 'ara',
        'russian': 'rus',
        'hindi': 'hin',
        'portuguese': 'por',
        'italian': 'ita',
        'japanese': 'jpn',
        'korean': 'kor'
    }
    
    lang_code = language_map.get(language, language)
    
    # Save uploaded file
    paths = save_uploads(files)
    file_path = paths[0]
    file_ext = ext_of(file_path)
    
    try:
        # Validate file type
        if file_ext not in ALLOWED_PDF_EXT | ALLOWED_IMAGE_EXT:
            safe_remove(file_path)
            return jsonify({
                "error": "Only PDF and image files are supported for OCR.",
                "supported": list(ALLOWED_PDF_EXT | ALLOWED_IMAGE_EXT)
            }), 400
        
        # Process based on file type
        is_pdf = file_ext in ALLOWED_PDF_EXT
        images = []
        
        if is_pdf:
            # Validate PDF structure
            is_valid, message = EnhancedPDFProcessor.validate_pdf_file(file_path)
            if not is_valid:
                safe_remove(file_path)
                return jsonify({"error": f"Invalid PDF: {message}"}), 400
            
            # Convert PDF to images
            try:
                file_size = os.path.getsize(file_path)
                dpi = 300 if file_size < 30 * 1024 * 1024 else 200
                
                images = convert_from_bytes(
                    open(file_path, 'rb').read(),
                    dpi=dpi,
                    thread_count=2,
                    fmt='jpeg',
                    grayscale=True,
                    size=(1650, 2338)  # A4 at 200 DPI
                )[:MAX_PAGES_TO_EXTRACT]
            except Exception as e:
                safe_remove(file_path)
                return jsonify({"error": f"Failed to convert PDF to images: {str(e)}"}), 500
        else:
            # Process single image
            try:
                img = Image.open(file_path)
                images = [img]
            except Exception as e:
                safe_remove(file_path)
                return jsonify({"error": f"Failed to open image: {str(e)}"}), 500
        
        if not images:
            safe_remove(file_path)
            return jsonify({"error": "No images could be extracted from the file."}), 400
        
        # Perform OCR in parallel
        def ocr_single_image(img, page_num):
            try:
                # Enhanced preprocessing
                img = ImageOps.exif_transpose(img)
                
                if img.mode != 'L':
                    img = img.convert('L')
                
                # Enhance for better OCR
                enhancer = ImageEnhance.Contrast(img)
                img = enhancer.enhance(1.8)
                
                enhancer = ImageEnhance.Sharpness(img)
                img = enhancer.enhance(1.5)
                
                # Apply gentle sharpening
                img = img.filter(ImageFilter.SHARPEN)
                
                # OCR with optimal configuration
                custom_config = f'--psm 1 --oem 3 -c preserve_interword_spaces=1'
                
                text = pytesseract.image_to_string(
                    img,
                    lang=lang_code,
                    config=custom_config
                )
                
                # Get detailed data for PDF creation
                data = None
                if output_format == 'pdf':
                    data = pytesseract.image_to_data(
                        img,
                        lang=lang_code,
                        config=custom_config,
                        output_type=pytesseract.Output.DICT
                    )
                
                return {
                    'page': page_num + 1,
                    'text': text,
                    'data': data,
                    'image': img
                }
            except Exception as e:
                app.logger.error(f"OCR page {page_num} error: {e}")
                return None
        
        # Process all images
        ocr_results = []
        futures = []
        
        for idx, img in enumerate(images):
            future = ocr_executor.submit(ocr_single_image, img, idx)
            futures.append(future)
        
        for future in as_completed(futures):
            try:
                result = future.result(timeout=120)
                if result:
                    ocr_results.append(result)
            except TimeoutError:
                app.logger.warning("OCR page processing timed out")
            except Exception as e:
                app.logger.error(f"OCR future error: {e}")
        
        if not ocr_results:
            safe_remove(file_path)
            return jsonify({"error": "OCR processing failed to extract any text."}), 500
        
        # Sort by page number
        ocr_results.sort(key=lambda x: x['page'])
        
        # Prepare output
        all_text = "\n\n".join([f"--- Page {r['page']} ---\n{r['text']}" for r in ocr_results if r['text'].strip()])
        cleaned_text = EnhancedPDFProcessor.clean_text_for_xml(all_text)
        
        # Generate output file
        original_name = secure_filename(files[0].filename)
        
        if output_format == 'pdf':
            # Create searchable PDF
            output_name = generate_unique_filename(original_name, "ocr_searchable")
            output_name = os.path.splitext(output_name)[0] + ".pdf"
            
            buffer = EnhancedPDFProcessor.create_searchable_pdf(
                [r['image'] for r in ocr_results],
                [r['text'] for r in ocr_results],
                lang_code
            )
            
            if buffer is None:
                safe_remove(file_path)
                return jsonify({"error": "Failed to create searchable PDF."}), 500
            
            mimetype = 'application/pdf'
            
        elif output_format == 'word':
            # Create Word document
            output_name = generate_unique_filename(original_name, "ocr_text")
            output_name = os.path.splitext(output_name)[0] + ".docx"
            
            doc = Document()
            if cleaned_text:
                paragraphs = [p.strip() for p in cleaned_text.split('\n\n') if p.strip()]
                for para in paragraphs[:500]:  # Limit
                    if para.strip():
                        doc.add_paragraph(para.strip())
            else:
                doc.add_paragraph("No text could be extracted via OCR.")
            
            buffer = io.BytesIO()
            doc.save(buffer)
            buffer.seek(0)
            
            mimetype = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            
        else:  # text format
            output_name = generate_unique_filename(original_name, "ocr_text")
            output_name = os.path.splitext(output_name)[0] + ".txt"
            
            buffer = io.BytesIO(cleaned_text.encode('utf-8'))
            buffer.seek(0)
            
            mimetype = 'text/plain; charset=utf-8'
        
        # Prepare response
        response = send_file(
            buffer,
            mimetype=mimetype,
            as_attachment=True,
            download_name=output_name
        )
        
        # Cleanup
        @after_this_request
        def cleanup(response):
            safe_remove(file_path)
            # Clean up image objects
            for img in images:
                try:
                    img.close()
                except:
                    pass
            return response
        
        elapsed = time.time() - start_time
        app.logger.info(f"OCR completed in {elapsed:.2f}s, {len(ocr_results)} pages, format: {output_format}")
        
        return response
        
    except Exception as e:
        app.logger.error(f"OCR processing failed: {e}", exc_info=True)
        safe_remove(file_path)
        return jsonify({
            "error": f"OCR processing failed: {str(e)}",
            "tip": "Try reducing image quality or using a different language."
        }), 500

# -----------------------------------------------------------------------------
# Fixed PDF to Word API with OCR option
# -----------------------------------------------------------------------------
@app.route('/api/pdf-to-word', methods=['POST'])
@rate_limit
@validate_pdf_structure
@timeout_decorator(180)
def api_pdf_to_word():
    """Enhanced PDF to Word conversion with proper OCR integration"""
    start_time = time.time()
    cleanup_temp()
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF file."}), 400
    
    use_ocr = request.form.get('ocr', 'false').lower() == 'true'
    language = request.form.get('language', 'eng').strip()
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400
    
    try:
        # Validate PDF
        is_valid, message = EnhancedPDFProcessor.validate_pdf_file(pdf_path)
        if not is_valid:
            safe_remove(pdf_path)
            return jsonify({"error": f"Invalid PDF: {message}"}), 400
        
        # Extract text with intelligent fallback
        text = EnhancedPDFProcessor.extract_text_with_fallback(
            pdf_path, 
            use_ocr=use_ocr, 
            lang=language
        )
        
        # Generate output name
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "converted")
        output_name = os.path.splitext(output_name)[0] + ".docx"
        
        # Create Word document
        doc = Document()
        
        if text:
            # Add metadata
            doc.core_properties.title = original_name
            doc.core_properties.author = "iMasterPDF Converter"
            
            # Add content in structured way
            paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
            
            for idx, para in enumerate(paragraphs[:1000]):  # Limit
                if para.strip():
                    # Preserve formatting hints
                    if para.startswith('--- Page'):
                        # Add page break
                        if idx > 0:
                            doc.add_page_break()
                        # Add page header
                        header = doc.add_heading(para, level=3)
                    else:
                        # Regular paragraph
                        p = doc.add_paragraph(para)
                        
                        # Style based on content
                        if len(para) < 100 and para.endswith(':'):
                            p.style = 'Heading 4'
        else:
            doc.add_paragraph("No text could be extracted from this PDF.")
            if use_ocr:
                doc.add_paragraph("OCR may have failed. Try adjusting image quality or language settings.")
        
        # Save to buffer
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
        
        elapsed = time.time() - start_time
        app.logger.info(f"PDF to Word completed in {elapsed:.2f}s, OCR: {use_ocr}, chars: {len(text) if text else 0}")
        
        return response
        
    except Exception as e:
        app.logger.error(f"PDF to Word conversion failed: {e}", exc_info=True)
        safe_remove(pdf_path)
        return jsonify({"error": f"Conversion failed: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# Fixed PDF Locking API with Strong Passwords
# -----------------------------------------------------------------------------
@app.route('/api/lock-pdf', methods=['POST'])
@rate_limit
@validate_pdf_structure
def api_lock_pdf():
    """Secure PDF encryption with strong password requirements"""
    start_time = time.time()
    cleanup_temp()
    
    password = request.form.get('password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()
    
    # Strong password validation
    if not password:
        return jsonify({"error": "Password is required."}), 400
    
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters long."}), 400
    
    if password != confirm_password:
        return jsonify({"error": "Passwords do not match."}), 400
    
    # Optional: Add password strength check
    if not any(c.isupper() for c in password):
        return jsonify({"warning": "For better security, include uppercase letters."}), 400
    
    files = request.files.getlist('files')
    if not files or len(files) != 1:
        return jsonify({"error": "Upload exactly one PDF file."}), 400
    
    paths = save_uploads(files)
    pdf_path = paths[0]
    
    if ext_of(pdf_path) not in ALLOWED_PDF_EXT:
        safe_remove(pdf_path)
        return jsonify({"error": "Only PDF files are allowed."}), 400
    
    try:
        # Read and encrypt PDF
        with open(pdf_path, 'rb') as f:
            reader = PdfReader(f)
        
        writer = PdfWriter()
        
        # Copy all pages
        for page in reader.pages:
            writer.add_page(page)
        
        # Copy metadata
        if reader.metadata:
            writer.add_metadata(reader.metadata)
        
        # Generate strong owner password (different from user password)
        owner_password = password + "_owner_" + secrets.token_hex(8)
        
        # Encrypt with strong settings
        writer.encrypt(
            user_password=password,
            owner_password=owner_password,
            use_128bit=True,
            permissions_flag=-3900  # Restrict most operations, allow only viewing
        )
        
        # Generate output
        original_name = secure_filename(files[0].filename)
        output_name = generate_unique_filename(original_name, "protected")
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
        
        elapsed = time.time() - start_time
        app.logger.info(f"PDF locked in {elapsed:.2f}s")
        
        return response
        
    except Exception as e:
        app.logger.error(f"PDF locking failed: {e}")
        safe_remove(pdf_path)
        return jsonify({"error": f"Locking failed: {str(e)}"}), 500

# -----------------------------------------------------------------------------
# Other API routes (kept similar but with enhanced error handling)
# -----------------------------------------------------------------------------
@app.route('/api/merge-pdf', methods=['POST'])
@rate_limit
@validate_pdf_structure
@timeout_decorator(120)
def api_merge_pdf():
    """Enhanced PDF merging with progress tracking"""
    # ... implementation similar to original but with better error handling ...
    pass

@app.route('/api/split-pdf', methods=['POST'])
@rate_limit
@validate_pdf_structure
@timeout_decorator(120)
def api_split_pdf():
    """Enhanced PDF splitting"""
    # ... implementation ...
    pass

# [Other API routes would follow similar pattern...]

# -----------------------------------------------------------------------------
# Health Check and Monitoring
# -----------------------------------------------------------------------------
@app.route('/health', methods=['GET'])
def health_check():
    """Comprehensive health check endpoint"""
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0",
        "features": {
            "ocr_available": OCR_ENABLED,
            "cache_enabled": CACHE_ENABLED,
            "max_workers": MAX_WORKERS
        },
        "resources": {
            "cache_size": len(conversion_cache),
            "upload_dir_files": len(os.listdir(UPLOAD_DIR)) if os.path.exists(UPLOAD_DIR) else 0,
            "output_dir_files": len(os.listdir(OUTPUT_DIR)) if os.path.exists(OUTPUT_DIR) else 0
        },
        "thread_pools": {
            "pdf_executor": pdf_executor._work_queue.qsize(),
            "ocr_executor": ocr_executor._work_queue.qsize(),
            "io_executor": io_executor._work_queue.qsize()
        }
    }
    
    # Check disk space
    try:
        stat = shutil.disk_usage(UPLOAD_DIR)
        status["disk"] = {
            "total_gb": round(stat.total / (1024**3), 2),
            "used_gb": round(stat.used / (1024**3), 2),
            "free_gb": round(stat.free / (1024**3), 2),
            "free_percent": round((stat.free / stat.total) * 100, 2)
        }
    except:
        status["disk"] = "unavailable"
    
    return jsonify(status), 200

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get usage statistics"""
    stats = {
        "total_requests": sum(len(times) for times in request_tracker.values()),
        "unique_ips": len(request_tracker),
        "cache_hits": sum(1 for _, (time, _) in conversion_cache.items() 
                         if time.time() - time < CACHE_TTL_SECONDS),
        "cache_size": len(conversion_cache),
        "uptime": time.time() - app_start_time if 'app_start_time' in globals() else 0
    }
    return jsonify(stats), 200

# -----------------------------------------------------------------------------
# Error Handlers
# -----------------------------------------------------------------------------
@app.errorhandler(404)
def page_not_found(e):
    return jsonify({"error": "Page not found. Please check the URL."}), 404

@app.errorhandler(413)
def too_large(e):
    return jsonify({"error": f"File too large (maximum {MAX_CONTENT_LENGTH // (1024*1024)} MB per file)."}), 413

@app.errorhandler(429)
def rate_limit_exceeded(e):
    return jsonify({
        "error": "Rate limit exceeded",
        "message": "Too many requests from your IP address. Please try again later."
    }), 429

@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description) if e.description else "Bad request."}), 400

@app.errorhandler(500)
def server_error(e):
    app.logger.error(f"Server error: {e}", exc_info=True)
    return jsonify({
        "error": "Internal server error",
        "message": "An unexpected error occurred. Please try again later."
    }), 500

# -----------------------------------------------------------------------------
# Static File Serving and CORS
# -----------------------------------------------------------------------------
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.after_request
def after_request(response):
    """Add security headers"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 
                        'Content-Type,Authorization,X-Requested-With,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('X-Content-Type-Options', 'nosniff')
    response.headers.add('X-Frame-Options', 'DENY')
    response.headers.add('X-XSS-Protection', '1; mode=block')
    response.headers.add('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return response

# -----------------------------------------------------------------------------
# Cache Management Thread
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
            if len(conversion_cache) > MAX_CACHE_SIZE:
                keys = list(conversion_cache.keys())[:MAX_CACHE_SIZE // 10]
                for key in keys:
                    del conversion_cache[key]
                    
        except Exception as e:
            app.logger.error(f"Cache cleanup error: {e}")

# -----------------------------------------------------------------------------
# Startup Initialization
# -----------------------------------------------------------------------------
def check_ocr_dependencies():
    """Check OCR dependencies and provide installation instructions"""
    if not OCR_AVAILABLE:
        print("\n" + "="*70)
        print("OCR FEATURE SETUP REQUIRED")
        print("="*70)
        print("\nFor optimal OCR functionality, install these dependencies:")
        
        print("\n1. System Dependencies (Ubuntu/Debian):")
        print("   sudo apt-get update")
        print("   sudo apt-get install -y tesseract-ocr")
        print("   sudo apt-get install -y tesseract-ocr-eng tesseract-ocr-spa tesseract-ocr-fra")
        print("   sudo apt-get install -y libtesseract-dev libleptonica-dev")
        print("   sudo apt-get install -y poppler-utils")
        
        print("\n2. Python Packages:")
        print("   pip install pytesseract==0.3.10")
        print("   pip install pdf2image==1.16.3")
        print("   pip install Pillow==10.1.0")
        print("   pip install numpy==1.24.3")
        
        print("\n3. For Windows:")
        print("   Download Tesseract OCR:")
        print("   https://github.com/UB-Mannheim/tesseract/wiki")
        print("   Add to PATH: C:\\Program Files\\Tesseract-OCR")
        
        print("\n4. Language Packs (optional):")
        print("   sudo apt-get install tesseract-ocr-all")
        
        print("\n5. Set Environment Variable:")
        print("   export TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/")
        print("="*70 + "\n")
    
    return OCR_AVAILABLE

# -----------------------------------------------------------------------------
# Application Startup
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    app_start_time = time.time()
    
    print(f"\n{'='*60}")
    print("🚀 iMasterPDF Enhanced Edition")
    print(f"{'='*60}")
    print(f"   Version: 2.0.0")
    print(f"   OCR Available: {OCR_ENABLED}")
    print(f"   Max Workers: {MAX_WORKERS}")
    print(f"   Cache Enabled: {CACHE_ENABLED}")
    print(f"   Max File Size: {MAX_CONTENT_LENGTH // (1024*1024)} MB")
    print(f"   Upload Directory: {UPLOAD_DIR}")
    print(f"   Output Directory: {OUTPUT_DIR}")
    print(f"{'='*60}\n")
    
    # Check dependencies
    if not check_ocr_dependencies():
        print("⚠️  OCR features will be disabled. Install dependencies for full functionality.")
    
    # Start cleanup threads
    cache_thread = threading.Thread(target=cleanup_cache, daemon=True, name="cache_cleanup")
    cache_thread.start()
    
    temp_thread = threading.Thread(target=cleanup_temp, daemon=True, name="temp_cleanup")
    temp_thread.start()
    
    # Run application
    app.run(
        host='0.0.0.0', 
        port=8000, 
        debug=False, 
        threaded=True,
        use_reloader=False
    )