import pytesseract
from pdf2image import convert_from_path
from docx import Document
from PIL import Image
import os
import tempfile
import zipfile
import io

# =========================
# TESSERACT PATH Configuration
# =========================

def setup_tesseract():
    """Try to auto-detect tesseract path for different OS"""
    possible_paths = [
        # Windows paths
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        # Linux paths
        '/usr/bin/tesseract',
        '/usr/local/bin/tesseract',
        # macOS paths
        '/opt/homebrew/bin/tesseract',
        # Environment variable
        os.environ.get('TESSERACT_CMD', ''),
    ]
    
    for path in possible_paths:
        if path and os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            print(f"✅ Tesseract found at: {path}")
            return True
    
    print("⚠️  WARNING: Tesseract not found automatically.")
    print("Please install Tesseract-OCR and set the path.")
    return False

# Initialize tesseract
setup_tesseract()

# =========================
# OCR Detection Functions
# =========================

def is_scanned_pdf(pdf_path, text_threshold=100):
    """
    Check if PDF contains extractable text.
    Returns True if it's a scanned PDF (needs OCR).
    """
    try:
        from PyPDF2 import PdfReader
        
        with open(pdf_path, 'rb') as file:
            reader = PdfReader(file)
            
            # Check first few pages for text
            text = ""
            for i, page in enumerate(reader.pages[:3]):
                page_text = page.extract_text() or ""
                text += page_text
                
                # If we find enough text, it's not a scanned PDF
                if len(text.strip()) > text_threshold:
                    return False
            
            # If very little or no text found, likely scanned
            return len(text.strip()) < text_threshold
    except Exception as e:
        print(f"PDF scan check error: {e}")
        return True

def is_image_based_document(file_path):
    """
    Check if file is an image that needs OCR
    """
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
    file_ext = os.path.splitext(file_path.lower())[1]
    
    # If it's an image file, it needs OCR
    if file_ext in image_extensions:
        return True
    
    # For DOCX, check if it contains images but no text
    if file_ext in {'.docx', '.doc'}:
        try:
            doc = Document(file_path)
            
            # Count paragraphs with text
            text_paragraphs = 0
            for para in doc.paragraphs:
                if para.text.strip():
                    text_paragraphs += 1
            
            # If document has few text paragraphs, it might be image-based
            if text_paragraphs < 3:
                return True
            return False
        except:
            return False
    
    return False

# =========================
# Core OCR Functions
# =========================

def pdf_to_text_with_ocr(pdf_path, max_pages=None):
    """Convert scanned PDF to text using OCR"""
    try:
        print(f"Starting OCR for PDF: {os.path.basename(pdf_path)}")
        
        # Convert PDF to images
        images = convert_from_path(pdf_path, dpi=200)
        
        # Limit pages if specified
        if max_pages and max_pages > 0:
            images = images[:max_pages]
        
        full_text = ""
        total_pages = len(images)
        
        for i, img in enumerate(images):
            print(f"Processing page {i+1}/{total_pages}...")
            
            # Convert PIL Image to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Perform OCR
            custom_config = r'--oem 3 --psm 6'
            text = pytesseract.image_to_string(img, config=custom_config)
            
            if text.strip():
                full_text += f"--- Page {i+1} ---\n{text}\n\n"
            else:
                full_text += f"--- Page {i+1} ---\n[No text detected]\n\n"
        
        print(f"✅ OCR completed. Extracted {len(full_text)} characters.")
        return full_text
        
    except Exception as e:
        print(f"❌ OCR Error: {e}")
        raise Exception(f"OCR processing failed: {str(e)}")

def pdf_to_word_with_ocr(pdf_path, output_docx=None):
    """Convert scanned PDF to Word document using OCR"""
    try:
        # Extract text using OCR
        text = pdf_to_text_with_ocr(pdf_path)
        
        # Create Word document
        doc = Document()
        
        if text.strip():
            # Add OCR result to document
            for line in text.split('\n'):
                if line.strip():
                    doc.add_paragraph(line.strip())
        else:
            doc.add_paragraph("❌ No text could be extracted via OCR.")
        
        # Save or return
        if output_docx:
            doc.save(output_docx)
            print(f"✅ Word document saved: {output_docx}")
            return output_docx
        
        # Return as bytes if no output path given
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        print(f"❌ PDF to Word OCR Error: {e}")
        raise

def image_to_text(image_path):
    """Extract text from image using OCR"""
    try:
        img = Image.open(image_path)
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Perform OCR
        custom_config = r'--oem 3 --psm 6'
        text = pytesseract.image_to_string(img, config=custom_config)
        
        print(f"✅ Image OCR completed: {len(text)} characters extracted")
        return text
        
    except Exception as e:
        print(f"❌ Image OCR Error: {e}")
        return ""

def image_to_word(image_path, output_docx=None):
    """Convert image to Word document using OCR"""
    try:
        text = image_to_text(image_path)
        
        doc = Document()
        if text.strip():
            doc.add_paragraph(text)
        else:
            doc.add_paragraph("❌ No text could be extracted from the image.")
        
        if output_docx:
            doc.save(output_docx)
            print(f"✅ Image to Word saved: {output_docx}")
            return output_docx
        
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        print(f"❌ Image to Word Error: {e}")
        raise

def extract_text_from_file(file_path):
    """
    Universal text extraction with OCR fallback
    Returns extracted text or empty string
    """
    try:
        ext = os.path.splitext(file_path.lower())[1]
        
        if ext == '.pdf':
            # First check if it's a scanned PDF
            if is_scanned_pdf(file_path):
                print("🔍 Scanned PDF detected, using OCR...")
                return pdf_to_text_with_ocr(file_path, max_pages=50)
            else:
                # Try normal text extraction
                try:
                    from PyPDF2 import PdfReader
                    with open(file_path, 'rb') as f:
                        reader = PdfReader(f)
                        text = ""
                        for i, page in enumerate(reader.pages[:50]):
                            page_text = page.extract_text()
                            if page_text:
                                text += f"--- Page {i+1} ---\n{page_text}\n\n"
                        return text
                except:
                    # Fallback to OCR
                    return pdf_to_text_with_ocr(file_path, max_pages=50)
        
        elif ext in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}:
            return image_to_text(file_path)
        
        elif ext in {'.docx', '.doc'}:
            try:
                doc = Document(file_path)
                text = ""
                for para in doc.paragraphs:
                    if para.text.strip():
                        text += para.text + "\n"
                return text
            except Exception as e:
                print(f"Word extraction error: {e}")
                return ""
        
        elif ext == '.txt':
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            except:
                return ""
        
        else:
            print(f"⚠️  Unsupported file type: {ext}")
            return ""
            
    except Exception as e:
        print(f"❌ Text extraction error: {e}")
        return ""