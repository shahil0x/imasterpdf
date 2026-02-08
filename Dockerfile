FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TESSERACT_CMD=/usr/bin/tesseract

WORKDIR /app

# Install system dependencies in separate RUN commands for better caching
RUN apt-get update && apt-get install -y --no-install-recommends \
    # For Tesseract OCR
    tesseract-ocr \
    tesseract-ocr-eng \
    # For PDF processing
    poppler-utils \
    # For image processing
    libjpeg-dev \
    zlib1g-dev \
    libpng-dev \
    # Clean up
    && rm -rf /var/lib/apt/lists/*

# Install additional packages in separate RUN command
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Additional Tesseract languages (install separately to avoid conflicts)
    tesseract-ocr-deu \
    tesseract-ocr-fra \
    tesseract-ocr-spa \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# Install fonts and other dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-dejavu \
    fontconfig \
    libtiff-dev \
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Create directories for file uploads
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs \
    && chmod 777 /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Copy application code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 -s /bin/bash appuser \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /tmp/imasterpdf_uploads \
    && chown -R appuser:appuser /tmp/imasterpdf_outputs

USER appuser

EXPOSE 10000

# Run the application
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "2", "--threads", "4", "--timeout", "120"]