# Multi-stage build for optimized image size
FROM python:3.12-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# ------------------------------------------------------------------------
# Final production image
FROM python:3.12-slim

# Metadata
LABEL maintainer="iMasterPDF"
LABEL version="2.0.0"
LABEL description="Ultra-fast PDF processing with OCR"

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

WORKDIR /app

# Install system dependencies
# Note: Keep these in one RUN to reduce layers and clean up immediately
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR dependencies
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-chi-sim \
    tesseract-ocr-ara \
    tesseract-ocr-rus \
    tesseract-ocr-por \
    tesseract-ocr-ita \
    tesseract-ocr-jpn \
    tesseract-ocr-kor \
    tesseract-ocr-hin \
    # PDF/image processing
    poppler-utils \
    libmagic-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    libgl1 \
    libglib2.0-0 \
    # Fonts for PDF generation
    fonts-dejavu \
    fonts-liberation \
    fonts-noto \
    fonts-noto-cjk \
    # Clean up
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /tmp/* /var/tmp/*

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser

# Copy Python packages from builder stage
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Ensure the user has access to the .local/bin directory
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/home/appuser/.local/lib/python3.12/site-packages:$PYTHONPATH

# Create necessary directories with proper permissions
RUN mkdir -p \
    /tmp/imasterpdf_uploads \
    /tmp/imasterpdf_outputs \
    /var/log/imasterpdf \
    && chown -R appuser:appuser \
    /tmp/imasterpdf_uploads \
    /tmp/imasterpdf_outputs \
    /var/log/imasterpdf \
    && chmod 755 \
    /tmp/imasterpdf_uploads \
    /tmp/imasterpdf_outputs

# Switch to non-root user
USER appuser

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:10000/health')"

# Expose port (matches your CMD below)
EXPOSE 10000

# Optimized Gunicorn configuration for your app.py
# Using sync workers since your app has its own ThreadPoolExecutor
CMD ["gunicorn", \
    "--bind", "0.0.0.0:10000", \
    "--workers", "4", \
    "--threads", "2", \
    "--timeout", "300", \
    "--keep-alive", "5", \
    "--max-requests", "1000", \
    "--max-requests-jitter", "50", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "--log-level", "info", \
    "--worker-class", "sync", \
    "app:app"]