# Multi-stage build for optimized image size
FROM python:3.11-slim AS builder

# Install system dependencies
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
# Final stage
FROM python:3.11-slim

# Install runtime system dependencies
# Tesseract OCR, Poppler for PDF to image conversion, and image libraries
RUN apt-get update && apt-get install -y \
    # OCR dependencies
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-spa \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-chi-sim \
    tesseract-ocr-ara \
    tesseract-ocr-rus \
    # PDF/image processing
    poppler-utils \
    libmagic-dev \
    libjpeg-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    # Fonts for PDF generation
    fonts-dejavu \
    fonts-liberation \
    fonts-noto \
    fonts-noto-cjk \
    # Cleanup
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser

WORKDIR /app

# Copy Python packages from builder stage
COPY --from=builder /root/.local /home/appuser/.local

# Copy application code
COPY --chown=appuser:appuser . .

# Ensure the user has access to the .local/bin directory
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONPATH=/home/appuser/.local/lib/python3.11/site-packages:$PYTHONPATH

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Create necessary directories with proper permissions
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs \
    && chown -R appuser:appuser /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs \
    && chmod 755 /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Expose port
EXPOSE 8000

# Run with Gunicorn for production
CMD ["gunicorn", \
    "--bind", "0.0.0.0:8000", \
    "--workers", "4", \
    "--threads", "4", \
    "--worker-class", "gevent", \
    "--timeout", "120", \
    "--access-logfile", "-", \
    "--error-logfile", "-", \
    "app:app"]