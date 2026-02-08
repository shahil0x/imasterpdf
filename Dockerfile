FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TESSERACT_CMD=/usr/bin/tesseract

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # For Tesseract OCR
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-deu \
    tesseract-ocr-fra \
    tesseract-ocr-spa \
    tesseract-ocr-chi-sim \
    tesseract-ocr-chi-tra \
    # For PDF processing
    poppler-utils \
    # For image processing with Pillow
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    libtiff-dev \
    libwebp-dev \
    # For OpenCV (if needed)
    libgl1-mesa-glx \
    libglib2.0-0 \
    # For PDF generation (fonts)
    fonts-liberation \
    fonts-dejavu \
    ttf-mscorefonts-installer \
    fontconfig \
    # Clean up
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Create directories for file uploads
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs \
    && chmod 777 /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Copy application code
COPY . .

# Verify structure
RUN echo "=== Checking project structure ===" && \
    ls -la && \
    echo "=== Checking key files ===" && \
    [ -f "app.py" ] && echo "app.py exists" || echo "app.py NOT FOUND" && \
    [ -f "ocr.py" ] && echo "ocr.py exists" || echo "ocr.py NOT FOUND" && \
    [ -d "templates" ] && echo "templates folder exists" || echo "templates NOT FOUND" && \
    echo "=== Files in templates ===" && \
    ls -la templates/ 2>/dev/null || echo "No templates folder"

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 10000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:10000/health', timeout=2)" || exit 1

# Run the application
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-"]