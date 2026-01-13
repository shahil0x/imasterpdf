FROM python:3.13-slim

WORKDIR /app

# System dependencies required for Pillow, reportlab, pdfminer
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

# Upgrade build tools
RUN python -m pip install --upgrade pip setuptools wheel

# Install Pillow first (critical for Python 3.13)
RUN pip install --no-cache-dir --prefer-binary Pillow==10.2.0

# Install remaining dependencies
RUN pip install --no-cache-dir \
    Flask==3.0.0 \
    Werkzeug==3.0.1 \
    gunicorn==21.2.0 \
    PyPDF2==3.0.1 \
    python-docx==0.8.11 \
    reportlab==4.0.9 \
    pdfminer.six==20221105

COPY . .

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000"]