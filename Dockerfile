# Use Python 3.12 slim as base
FROM python:3.12-slim

# Prevent Python from writing .pyc files & enable logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Install system dependencies in a single layer to reduce image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Build essentials
    build-essential \
    # Tesseract OCR with multiple languages
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-ara \
    tesseract-ocr-rus \
    tesseract-ocr-chi-sim \
    tesseract-ocr-hin \
    tesseract-ocr-por \
    tesseract-ocr-ita \
    # Poppler for PDF to image conversion
    poppler-utils \
    # Image libraries
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    # Fonts for PDF generation
    fonts-dejavu \
    fonts-liberation \
    # Clean up in same layer to reduce image size
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies with optimizations
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories with proper permissions
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs \
    && chmod 755 /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Create a non-root user to run the application
RUN useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')"

# Expose port
EXPOSE 10000

# Start app with Gunicorn with optimized settings
CMD ["gunicorn", "app:app", \
    "--bind", "0.0.0.0:10000", \
    "--workers", "4", \
    "--threads", "2", \
    "--timeout", "120", \
    "--worker-class", "sync", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--log-level", "info", \
    "--preload"]