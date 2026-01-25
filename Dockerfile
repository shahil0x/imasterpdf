FROM python:3.12-slim

# Prevent Python from writing .pyc files & enable logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

WORKDIR /app

# Minimal system dependencies optimized for Render
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libjpeg-dev \
    zlib1g-dev \
    libfreetype6-dev \
    liblcms2-dev \
    libtiff-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (better Docker cache)
COPY requirements.txt .

RUN pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user for security (Render compatible)
RUN useradd -m -u 1000 -s /bin/bash appuser \
    && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Create temp directories with proper permissions
RUN mkdir -p /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs \
    && chmod 755 /tmp/imasterpdf_uploads /tmp/imasterpdf_outputs

# Create start script that handles $PORT (Render compatible)
RUN echo '#!/bin/bash' > /app/start.sh && \
    echo 'PORT=${PORT:-10000}' >> /app/start.sh && \
    echo 'echo "🚀 Starting iMasterPDF on port: \$PORT"' >> /app/start.sh && \
    echo 'echo "📁 Upload directory: /tmp/imasterpdf_uploads"' >> /app/start.sh && \
    echo 'echo "📁 Output directory: /tmp/imasterpdf_outputs"' >> /app/start.sh && \
    echo 'exec gunicorn app:app --bind 0.0.0.0:\$PORT --workers 2 --threads 2 --timeout 120 --access-logfile - --error-logfile - --log-level info' >> /app/start.sh && \
    chmod +x /app/start.sh

# Expose port
EXPOSE 10000

# Health check (Render compatible)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import os, sys; import urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT', '10000') + '/health', timeout=5)"

# Use the start script
CMD ["/app/start.sh"]