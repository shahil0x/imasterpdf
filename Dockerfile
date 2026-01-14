FROM python:3.12-slim

WORKDIR /app

# System dependencies for PDF / Image libraries
RUN apt-get update && apt-get install -y \
    build-essential \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libopenjp2-7-dev \
    libtiff5-dev \
    libharfbuzz-dev \
    libfribidi-dev \
    libxcb1-dev \
    libx11-dev \
    tk-dev \
    tcl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 🔥 CRITICAL GUNICORN FIX FOR PDF STREAMING
CMD [
  "gunicorn",
  "app:app",
  "--bind", "0.0.0.0:10000",
  "--workers", "2",
  "--worker-class", "gthread",
  "--threads", "4",
  "--timeout", "0",
  "--worker-tmp-dir", "/dev/shm",
  "--log-level", "info"
]