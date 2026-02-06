FROM python:3.12-slim

# Prevent Python from writing .pyc files & enable logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for OCR, Pillow, ReportLab, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Basic build tools
    build-essential \
    # Pillow dependencies
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff6 \
    libharfbuzz-dev \
    libfribidi-dev \
    # GUI dependencies (for some PDF/image processing)
    libxcb1 \
    libx11-6 \
    tk \
    tcl \
    # Tesseract OCR
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-all \
    # Poppler for pdf2image (PDF to image conversion)
    poppler-utils \
    # Additional OCR languages (optional - add more as needed)
    tesseract-ocr-fra \
    tesseract-ocr-spa \
    tesseract-ocr-deu \
    tesseract-ocr-ita \
    tesseract-ocr-por \
    tesseract-ocr-rus \
    tesseract-ocr-chi-sim \
    tesseract-ocr-chi-tra \
    tesseract-ocr-jpn \
    tesseract-ocr-kor \
    tesseract-ocr-ara \
    # Clean up apt cache
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Set Tesseract data path
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/4.00/tessdata

# Copy requirements first (better Docker cache)
COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Create directories for uploads and outputs
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Copy application code
COPY . .

# Set proper permissions for temp directories
RUN chmod 777 /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:10000/health', timeout=2)" || exit 1

# Expose port
EXPOSE 10000

# Start app with Gunicorn with optimized settings
CMD ["gunicorn", "app:app", \
    "--bind", "0.0.0.0:10000", \
    "--workers", "4", \
    "--threads", "4", \
    "--worker-class", "gthread", \
    "--worker-tmp-dir", "/dev/shm", \
    "--timeout", "300", \
    "--keep-alive", "5", \
    "--log-level", "info", \
    "--access-logfile", "-", \
    "--error-logfile", "-"]