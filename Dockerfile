FROM python:3.12-slim

# Prevent Python from writing .pyc files & enable logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/5.3.0/tessdata

WORKDIR /app

# System dependencies for OCR, PDF, and image processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff6 \
    libharfbuzz-dev \
    libfribidi-dev \
    libxcb1 \
    libx11-6 \
    tk \
    tcl \
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
    poppler-utils \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better Docker cache)
COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Expose port
EXPOSE 10000

# Start app with Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "4", "--threads", "2", "--timeout", "300", "--worker-class", "sync"]