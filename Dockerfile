FROM python:3.12-slim

# Prevent Python from writing .pyc files & enable logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies required for Pillow, ReportLab, etc.
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
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better Docker cache)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs \
    && chmod 755 /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Expose port (optional but recommended)
EXPOSE 10000

# Start app with Gunicorn
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "2", "--timeout", "120"]