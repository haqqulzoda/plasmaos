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

# 2. Copy application code
COPY . .

# 3. Expose port
EXPOSE 8000

# 4. Run the server
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
