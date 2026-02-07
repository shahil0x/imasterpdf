import os
import io
import tempfile
import pytesseract
from pdf2image import convert_from_path
from docx import Document
from PIL import Image
from pdfminer.high_level import extract_text
from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter

# =============================================================================
# TESSERACT CONFIG (SIMPLIFIED)
# =============================================================================
# Direct path setting - works on Windows
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
print("✅ Tesseract configured")

# =============================================================================
# SCANNED PDF DETECTION (IMPROVED)
# =============================================================================

def is_scanned_pdf(pdf_path, text_threshold=50):
    """
    Check if PDF is scanned/image-based (returns True if needs OCR)
    Uses both PyPDF2 and pdfminer for better detection
    """
    try:
        # Method 1: Try PyPDF2 first
        with open(pdf_path, 'rb') as file:
            reader = PdfReader(file)
            text = ""
            for i, page in enumerate(reader.pages[:2]):  # Check first 2 pages
                page_text = page.extract_text() or ""
                text += page_text
                if len(text.strip()) > text_threshold:
                    return False  # Has enough text, not scanned
        
        # Method 2: Fallback to pdfminer
        if len(text.strip()) < text_threshold:
            pdfminer_text = extract_text(pdf_path, maxpages=1)
            return not pdfminer_text or len(pdfminer_text.strip()) < text_threshold
        
        return len(text.strip()) < text_threshold
    except Exception as e:
        print(f"PDF scan check error: {e}")
        return True  # If extraction fails, assume scanned

def is_image_based_document(file_path):
    """Check if file is an image that needs OCR"""
    image_extensions = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
    file_ext = os.path.splitext(file_path.lower())[1]
    
    # If it's an image file, it needs OCR
    if file_ext in image_extensions:
        return True
    
    # For DOCX, check if it contains images but no text
    if file_ext in {'.docx', '.doc'}:
        try:
            doc = Document(file_path)
            text_paragraphs = sum(1 for para in doc.paragraphs if para.text.strip())
            return text_paragraphs < 3  # Few text paragraphs = image-based
        except:
            return False
    
    return False

# =============================================================================
# OCR TO SEARCHABLE PDF (NEW FUNCTION)
# =============================================================================

def ocr_pdf_to_searchable_pdf(input_pdf_path, output_pdf_path=None):
    """
    Convert scanned PDF to searchable PDF (text hidden behind images)
    Returns: output file path
    """
    try:
        print(f"🔄 Creating searchable PDF from: {os.path.basename(input_pdf_path)}")
        
        # Create temp output if not provided
        if not output_pdf_path:
            output_pdf_path = tempfile.mktemp(suffix="_searchable.pdf")
        
        # Convert PDF to images
        images = convert_from_path(input_pdf_path, dpi=300)
        
        # Create new PDF with OCR text
        c = canvas.Canvas(output_pdf_path, pagesize=letter)
        width, height = letter
        
        for i, img in enumerate(images):
            print(f"Processing page {i+1}/{len(images)}...")
            
            # Save image to temp file
            temp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            img.save(temp_img.name, "JPEG", quality=85)
            
            # Perform OCR on the image
            text = pytesseract.image_to_string(img, config="--oem 3 --psm 6")
            
            # Draw image as background
            c.drawImage(temp_img.name, 0, 0, width=width, height=height)
            
            # Add invisible text layer (searchable but not visible)
            c.setFont("Helvetica", 1)
            c.setFillColorRGB(1, 1, 1, alpha=0.01)
            
            # Add OCR text
            if text.strip():
                text_obj = c.beginText(10, -1000)  # Position off-page
                text_obj.textLines(text.split('\n'))
                c.drawText(text_obj)
            
            c.showPage()
            
            # Clean up temp image
            os.remove(temp_img.name)
        
        c.save()
        print(f"✅ Searchable PDF created: {output_pdf_path}")
        return output_pdf_path
        
    except Exception as e:
        print(f"❌ Error creating searchable PDF: {e}")
        raise

# =============================================================================
# OCR CORE FUNCTIONS
# =============================================================================

def pdf_to_text_with_ocr(pdf_path, max_pages=50):
    """Convert scanned PDF to text using OCR"""
    try:
        print(f"Starting OCR for PDF: {os.path.basename(pdf_path)}")
        
        images = convert_from_path(pdf_path, dpi=300)
        images = images[:max_pages]
        full_text = ""
        total_pages = len(images)
        
        for i, img in enumerate(images):
            print(f"Processing page {i+1}/{total_pages}...")
            
            if img.mode != "RGB":
                img = img.convert("RGB")
            
            text = pytesseract.image_to_string(img, config="--oem 3 --psm 6")
            
            if text.strip():
                full_text += f"--- Page {i+1} ---\n{text}\n\n"
            else:
                full_text += f"--- Page {i+1} ---\n[No text detected]\n\n"
        
        print(f"✅ OCR completed. Extracted {len(full_text)} characters.")
        return full_text.strip()
        
    except Exception as e:
        print(f"❌ OCR Error: {e}")
        raise Exception(f"OCR processing failed: {str(e)}")

def pdf_to_word_with_ocr(pdf_path, output_docx=None):
    """Convert scanned PDF to Word document using OCR"""
    try:
        text = pdf_to_text_with_ocr(pdf_path)
        
        doc = Document()
        if text.strip():
            for line in text.split('\n'):
                if line.strip():
                    doc.add_paragraph(line.strip())
        else:
            doc.add_paragraph("❌ No text could be extracted via OCR.")
        
        if output_docx:
            doc.save(output_docx)
            print(f"✅ Word document saved: {output_docx}")
            return output_docx
        
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
        
        if img.mode != "RGB":
            img = img.convert("RGB")
        
        text = pytesseract.image_to_string(img, config="--oem 3 --psm 6")
        
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

# =============================================================================
# UNIVERSAL EXTRACTOR
# =============================================================================

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
                    return extract_text(file_path)
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
            print(f"⚠️ Unsupported file type: {ext}")
            return ""
            
    except Exception as e:
        print(f"❌ Text extraction error: {e}")
        return ""