FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including Tesseract OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-tur \
    && rm -rf /var/lib/apt/lists/*

# Set Tesseract environment variable
ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY app.py .
COPY .streamlit/ ./.streamlit/
COPY scripts/ ./scripts/
COPY formatlar/ ./formatlar/

# Create runtime directories
RUN mkdir -p data/documents data/tables data/emails storage cache logs/telemetry logs/ab .cache/ocr storage/parquet storage/converters storage/conversations

# Copy target schemas (needed for converter pipeline)
COPY storage/schemas/ ./storage/schemas/

# Cloud Run injects PORT env variable (default 8080)
ENV PORT=8080
EXPOSE 8080

# Run Streamlit on Cloud Run's PORT
CMD streamlit run app.py \
    --server.address=0.0.0.0 \
    --server.port=$PORT \
    --server.headless=true \
    --server.maxUploadSize=500 \
    --server.maxMessageSize=500 \
    --browser.gatherUsageStats=false
