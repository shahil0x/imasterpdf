import os
import io
import pytesseract
from pdf2image import convert_from_path
from docx import Document
from PIL import Image
from pdfminer.high_level import extract_text

# =============================================================================
# TESSERACT AUTO CONFIG
# =============================================================================

def setup_tesseract():
    paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        "/opt/homebrew/bin/tesseract",
        os.environ.get("TESSERACT_CMD", "")
    ]

    for path in paths:
        if path and os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            print(f"✅ Tesseract found: {path}")
            return

    print("⚠️ Tesseract not found in PATH")

setup_tesseract()

# =============================================================================
# SCANNED PDF DETECTION (IMPORTANT)
# =============================================================================

def is_scanned_pdf(pdf_path, text_threshold=30):
    """
    Returns True if PDF is image-based (needs OCR)
    """
    try:
        text = extract_text(pdf_path)
        return len(text.strip()) < text_threshold
    except Exception:
        return True

# =============================================================================
# OCR CORE FUNCTIONS
# =============================================================================

def pdf_to_text_with_ocr(pdf_path, max_pages=50):
    images = convert_from_path(pdf_path, dpi=300)
    images = images[:max_pages]

    full_text = ""

    for i, img in enumerate(images):
        if img.mode != "RGB":
            img = img.convert("RGB")

        text = pytesseract.image_to_string(
            img,
            config="--oem 3 --psm 6"
        )

        full_text += f"\n--- Page {i+1} ---\n{text}\n"

    return full_text.strip()


def pdf_to_word_with_ocr(pdf_path, output_docx=None):
    text = pdf_to_text_with_ocr(pdf_path)

    doc = Document()

    if text.strip():
        for line in text.split("\n"):
            if line.strip():
                doc.add_paragraph(line)
    else:
        doc.add_paragraph("No text could be extracted using OCR.")

    if output_docx:
        doc.save(output_docx)
        return output_docx

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer


def image_to_text(image_path):
    img = Image.open(image_path)

    if img.mode != "RGB":
        img = img.convert("RGB")

    return pytesseract.image_to_string(
        img,
        config="--oem 3 --psm 6"
    )


def image_to_word(image_path, output_docx=None):
    text = image_to_text(image_path)

    doc = Document()
    doc.add_paragraph(text if text.strip() else "No text detected.")

    if output_docx:
        doc.save(output_docx)
        return output_docx

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return buffer

# =============================================================================
# UNIVERSAL EXTRACTOR
# =============================================================================

def extract_text_from_file(file_path):
    ext = os.path.splitext(file_path.lower())[1]

    if ext == ".pdf":
        if is_scanned_pdf(file_path):
            print("🔍 Scanned PDF → OCR")
            return pdf_to_text_with_ocr(file_path)
        else:
            return extract_text(file_path)

    if ext in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}:
        return image_to_text(file_path)

    if ext == ".txt":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if ext in {".docx", ".doc"}:
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

    return ""
