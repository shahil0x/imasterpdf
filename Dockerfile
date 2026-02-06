FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg-dev \
    zlib1g-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

COPY . .

EXPOSE 10000

# ✅✅✅ FIX THIS LINE - Use "app.app:app" since your app is in app/app.py ✅✅✅
CMD ["gunicorn", "app.app:app", "--bind", "0.0.0.0:10000", "--workers", "2", "--timeout", "120"]