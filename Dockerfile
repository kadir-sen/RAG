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

# Copy requirements first for caching. No torch — server query embedding uses
# fastembed (ONNX), keeping the image small and RAM low enough for a 2 GB box.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Pre-bake the fastembed bge model into the image so query-time embedding works
# offline (no first-request download). Keep in sync with LOCAL_EMBEDDING_MODEL.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-base-en-v1.5')"

# Build frontend
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci --production=false
COPY frontend/ ./frontend/
RUN cd frontend && npm run build

# Copy application code
COPY src/ ./src/
COPY backend/ ./backend/
# The jargon manager loads this version-controlled glossary during module
# import, before the API can answer its health check. Keep the copy explicit so
# future files under config/ (which may be deployment-specific) are not baked
# into the image accidentally.
COPY config/jargon_terms.json ./config/jargon_terms.json
RUN python -c "import json; p='config/jargon_terms.json'; d=json.load(open(p, encoding='utf-8')); assert isinstance(d, dict) and len(d) == 2703"
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

# Authored content that ships with the app. Deliberately NOT under data/ or
# storage/: docker-compose.prod.yml bind-mounts both of those from the host,
# which masks whatever the image put there. Files here are visible at runtime
# because nothing mounts over /app/content.
COPY content/ ./content/

# Cloud Run injects PORT env variable (default 8080)
ENV PORT=8080
ENV APP_MODE=api
EXPOSE 8080

# Use entrypoint script to select app based on APP_MODE
CMD ["./entrypoint.sh"]
