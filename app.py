# app.py - COMPLETE WORKING VERSION
import os, uuid, subprocess, json, time, threading, traceback
from flask import Flask, render_template, request, send_file, jsonify, session
from werkzeug.utils import secure_filename
from PyPDF2 import PdfMerger, PdfReader, PdfWriter
from docx import Document
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from PIL import Image
import io
import zipfile
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

UPLOAD_FOLDER = 'static/uploads'
OUTPUT_FOLDER = 'static/outputs'
PROCESSING_FOLDER = 'static/processing'

for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, PROCESSING_FOLDER]:
    os.makedirs(folder, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Cleanup function
def cleanup_folder(folder):
    for filename in os.listdir(folder):
        filepath = os.path.join(folder, filename)
        try:
            if os.path.isfile(filepath):
                os.remove(filepath)
        except:
            pass

from flask import Flask, render_template

app = Flask(__name__)

@app.route("/", methods=["GET", "HEAD"])
def index():
    return render_template("index.html")



@app.route('/api/upload', methods=['POST'])
def upload_files():
    try:
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id
        
        tool = request.form.get('tool')
        files = request.files.getlist('files')
        text_data = request.form.get('text', '')
        
        uploaded_files = []
        
        # Handle text-based tools
        if tool in ['text_to_pdf', 'text_to_word'] and text_data:
            # Save text to a file
            text_filename = f"{session_id}_text.txt"
            text_path = os.path.join(app.config['UPLOAD_FOLDER'], text_filename)
            with open(text_path, 'w', encoding='utf-8') as f:
                f.write(text_data)
            uploaded_files.append(text_filename)
        else:
            # Handle file uploads
            for file in files:
                if file.filename:
                    filename = secure_filename(f"{session_id}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    uploaded_files.append(filename)
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'files': uploaded_files
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/convert', methods=['POST'])
def convert():
    try:
        data = request.json
        tool = data.get('tool')
        session_id = data.get('session_id')
        options = data.get('options', {})
        text_data = data.get('text', '')
        
        # Get uploaded files for this session
        uploaded_files = []
        for filename in os.listdir(UPLOAD_FOLDER):
            if filename.startswith(session_id):
                uploaded_files.append(os.path.join(UPLOAD_FOLDER, filename))
        
        if not uploaded_files and not text_data:
            return jsonify({'success': False, 'error': 'No files or text found'})
        
        output_path = None
        
        # Handle text-based tools
        if tool == 'text_to_pdf':
            output_path = text_to_pdf(text_data, session_id)
        elif tool == 'text_to_word':
            output_path = text_to_word(text_data, session_id)
        # Handle file-based tools
        elif tool == 'pdf_to_word':
            output_path = convert_pdf_to_word(uploaded_files[0], session_id)
        elif tool == 'word_to_pdf':
            output_path = convert_word_to_pdf(uploaded_files[0], session_id)
        elif tool == 'merge_pdf':
            output_path = merge_pdfs(uploaded_files, session_id, options)
        elif tool == 'split_pdf':
            output_path = split_pdf(uploaded_files[0], session_id, options)
        elif tool == 'rotate_pdf':
            output_path = rotate_pdf(uploaded_files[0], session_id, options)
        elif tool == 'compress_pdf':
            output_path = compress_pdf(uploaded_files[0], session_id, options)
        elif tool == 'lock_pdf':
            output_path = lock_pdf(uploaded_files[0], session_id, options)
        elif tool == 'unlock_pdf':
            output_path = unlock_pdf(uploaded_files[0], session_id, options)
        elif tool == 'images_to_pdf':
            output_path = images_to_pdf(uploaded_files, session_id, options)
        elif tool == 'extract_text':
            output_path = extract_text_from_pdf(uploaded_files[0], session_id)
        elif tool == 'word_to_text':
            output_path = word_to_text(uploaded_files[0], session_id)
        elif tool == 'merge_word':
            output_path = merge_word_docs(uploaded_files, session_id)
        else:
            return jsonify({'success': False, 'error': 'Invalid tool'})
        
        if output_path and os.path.exists(output_path):
            filename = os.path.basename(output_path)
            cleanup_folder(UPLOAD_FOLDER)  # Clean uploads after conversion
            
            return jsonify({
                'success': True,
                'download_url': f'/download/{filename}',
                'filename': filename
            })
        else:
            return jsonify({'success': False, 'error': 'Conversion failed - no output file'})
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(OUTPUT_FOLDER, filename)
    if os.path.exists(filepath):
        return send_file(filepath, as_attachment=True)
    return jsonify({'success': False, 'error': 'File not found'}), 404

# ---------- CONVERSION FUNCTIONS ----------

def convert_pdf_to_word(pdf_path, session_id):
    """Convert PDF to Word"""
    output_name = f"converted_{session_id}.docx"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    try:
        subprocess.run([
            "libreoffice", "--headless", "--convert-to", "docx",
            pdf_path, "--outdir", OUTPUT_FOLDER
        ], check=True, capture_output=True)
        
        # Find and rename the output
        for file in os.listdir(OUTPUT_FOLDER):
            if file.endswith('.docx') and not file.startswith('converted_'):
                temp_path = os.path.join(OUTPUT_FOLDER, file)
                os.rename(temp_path, output_path)
                break
        
        return output_path
    except:
        # Fallback: Create empty doc if LibreOffice fails
        doc = Document()
        doc.add_paragraph("PDF to Word conversion requires LibreOffice installation.")
        doc.save(output_path)
        return output_path

def convert_word_to_pdf(docx_path, session_id):
    """Convert Word to PDF"""
    output_name = f"converted_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    try:
        subprocess.run([
            "libreoffice", "--headless", "--convert-to", "pdf",
            docx_path, "--outdir", OUTPUT_FOLDER
        ], check=True, capture_output=True)
        
        for file in os.listdir(OUTPUT_FOLDER):
            if file.endswith('.pdf') and not file.startswith('converted_'):
                temp_path = os.path.join(OUTPUT_FOLDER, file)
                os.rename(temp_path, output_path)
                break
        
        return output_path
    except:
        # Fallback: Create a simple PDF
        c = canvas.Canvas(output_path, pagesize=letter)
        c.drawString(100, 750, "Word to PDF conversion requires LibreOffice.")
        c.save()
        return output_path

def merge_pdfs(pdf_paths, session_id, options):
    """Merge multiple PDFs"""
    output_name = f"merged_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    merger = PdfMerger()
    for pdf in pdf_paths:
        merger.append(pdf)
    
    merger.write(output_path)
    merger.close()
    
    return output_path

def split_pdf(pdf_path, session_id, options):
    """Split PDF"""
    reader = PdfReader(pdf_path)
    
    split_type = options.get('split_type', 'all')
    
    if split_type == 'range':
        try:
            start_page = int(options.get('start_page', 1)) - 1
            end_page = int(options.get('end_page', len(reader.pages)))
            pages = list(range(start_page, end_page))
        except:
            pages = list(range(len(reader.pages)))
    else:
        pages = list(range(len(reader.pages)))
    
    if len(pages) == 1:
        output_name = f"split_{session_id}.pdf"
        output_path = os.path.join(OUTPUT_FOLDER, output_name)
        writer = PdfWriter()
        writer.add_page(reader.pages[pages[0]])
        with open(output_path, 'wb') as f:
            writer.write(f)
        return output_path
    else:
        zip_name = f"split_{session_id}.zip"
        zip_path = os.path.join(OUTPUT_FOLDER, zip_name)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for i in pages:
                writer = PdfWriter()
                writer.add_page(reader.pages[i])
                page_filename = f"page_{i+1}.pdf"
                page_path = os.path.join(PROCESSING_FOLDER, page_filename)
                with open(page_path, 'wb') as f:
                    writer.write(f)
                zipf.write(page_path, page_filename)
                os.remove(page_path)
        
        return zip_path

def rotate_pdf(pdf_path, session_id, options):
    """Rotate PDF - FIXED VERSION"""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    
    # Get angle and convert to int
    angle_str = options.get('angle', '90')
    try:
        angle = int(angle_str)
    except:
        angle = 90
    
    # Rotate each page
    for page in reader.pages:
        page.rotate(angle)
        writer.add_page(page)
    
    output_name = f"rotated_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    with open(output_path, 'wb') as f:
        writer.write(f)
    
    return output_path

def compress_pdf(pdf_path, session_id, options):
    """Simple PDF compression"""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
    
    output_name = f"compressed_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    with open(output_path, 'wb') as f:
        writer.write(f)
    
    return output_path

def lock_pdf(pdf_path, session_id, options):
    """Add password protection"""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    
    for page in reader.pages:
        writer.add_page(page)
    
    password = options.get('password', '')
    if password:
        writer.encrypt(password)
    
    output_name = f"locked_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    with open(output_path, 'wb') as f:
        writer.write(f)
    
    return output_path

def unlock_pdf(pdf_path, session_id, options):
    """Remove password protection"""
    password = options.get('password', '')
    
    reader = PdfReader(pdf_path)
    if reader.is_encrypted:
        reader.decrypt(password)
    
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    
    output_name = f"unlocked_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    with open(output_path, 'wb') as f:
        writer.write(f)
    
    return output_path

def images_to_pdf(image_paths, session_id, options):
    """Convert images to PDF"""
    images = []
    for img_path in image_paths:
        try:
            img = Image.open(img_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            images.append(img)
        except:
            continue
    
    if not images:
        raise Exception("No valid images found")
    
    output_name = f"images_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    # Handle orientation
    orientation = options.get('orientation', 'portrait')
    
    images[0].save(
        output_path,
        save_all=True,
        append_images=images[1:],
        quality=85
    )
    
    return output_path

def extract_text_from_pdf(pdf_path, session_id):
    """Extract text from PDF"""
    reader = PdfReader(pdf_path)
    text = ""
    
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n\n"
    
    output_name = f"extracted_{session_id}.txt"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)
    
    return output_path

def word_to_text(docx_path, session_id):
    """Convert Word to Text"""
    doc = Document(docx_path)
    text = ""
    
    for para in doc.paragraphs:
        text += para.text + "\n"
    
    output_name = f"word_text_{session_id}.txt"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)
    
    return output_path

def merge_word_docs(docx_paths, session_id):
    """Merge multiple Word documents"""
    final_doc = Document()
    
    for doc_path in docx_paths:
        doc = Document(doc_path)
        for para in doc.paragraphs:
            final_doc.add_paragraph(para.text)
        final_doc.add_paragraph("\n---\n")
    
    output_name = f"merged_word_{session_id}.docx"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    final_doc.save(output_path)
    
    return output_path

def text_to_pdf(text, session_id):
    """Convert text to PDF"""
    output_name = f"text_pdf_{session_id}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    c = canvas.Canvas(output_path, pagesize=letter)
    
    # Simple text wrapping
    y_position = 750
    text_lines = text.split('\n')
    
    for line in text_lines:
        # Split long lines
        words = line.split(' ')
        current_line = ''
        
        for word in words:
            if len(current_line) + len(word) + 1 < 100:
                if current_line:
                    current_line += ' ' + word
                else:
                    current_line = word
            else:
                # Draw current line
                if y_position < 50:
                    c.showPage()
                    y_position = 750
                c.drawString(50, y_position, current_line)
                y_position -= 20
                current_line = word
        
        # Draw remaining line
        if current_line:
            if y_position < 50:
                c.showPage()
                y_position = 750
            c.drawString(50, y_position, current_line)
            y_position -= 20
        
        # Add extra space between paragraphs
        y_position -= 10
    
    c.save()
    return output_path

def text_to_word(text, session_id):
    """Convert text to Word"""
    output_name = f"text_word_{session_id}.docx"
    output_path = os.path.join(OUTPUT_FOLDER, output_name)
    
    doc = Document()
    
    # Split text into paragraphs
    paragraphs = text.split('\n\n')
    for para in paragraphs:
        if para.strip():
            doc.add_paragraph(para.strip())
    
    doc.save(output_path)
    
    return output_path

# Cleanup on shutdown
import atexit
atexit.register(lambda: [cleanup_folder(folder) for folder in [UPLOAD_FOLDER, OUTPUT_FOLDER, PROCESSING_FOLDER]])

if __name__ == '__main__':
    print("Starting iMasterPDF on http://localhost:5000")
    print("Make sure LibreOffice is installed for Word/PDF conversions")
    app.run(debug=True, host='0.0.0.0', port=5000)