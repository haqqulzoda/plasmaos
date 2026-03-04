# ============================================
# Plasma AI — Backend Dockerfile
# Base: Playwright image (includes browsers)
# ============================================
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# 1. Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir uvicorn gunicorn

# 2. Ensure Playwright browsers match the installed Python package
RUN playwright install chromium

# 3. Copy application code
COPY . .

# 4. Expose port
EXPOSE 8000

# 5. Run the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]


RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    tesseract-ocr-rus \
    tesseract-ocr-uzb \
    poppler-utils \
    unrar \
    && rm -rf /var/lib/apt/lists/*
