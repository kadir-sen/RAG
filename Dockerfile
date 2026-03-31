FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including Tesseract OCR and Node.js
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-tur \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Set Tesseract environment variable
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build frontend
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --production=false
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Copy application code
COPY src/ ./src/
COPY backend/ ./backend/
COPY app.py .
COPY debug_app.py .
COPY entrypoint.sh .
COPY .streamlit/ ./.streamlit/
COPY scripts/ ./scripts/
COPY formatlar/ ./formatlar/

# Make entrypoint executable
RUN chmod +x entrypoint.sh

# Create runtime directories
RUN mkdir -p data/documents data/tables data/emails storage cache logs/telemetry logs/ab .cache/ocr storage/parquet storage/converters storage/conversations storage/review_sessions

# Copy target schemas (needed for converter pipeline)
COPY storage/schemas/ ./storage/schemas/

# Cloud Run injects PORT env variable (default 8080)
ENV PORT=8080
ENV APP_MODE=api
EXPOSE 8080

# Use entrypoint script to select app based on APP_MODE
CMD ["./entrypoint.sh"]
