#!/bin/bash
# Entrypoint script for Cloud Run / Docker
# APP_MODE=api       runs FastAPI backend (new)
# APP_MODE=main      runs Streamlit chatbot (legacy)
# APP_MODE=debug     runs Streamlit debug service (legacy)

set -e

PORT="${PORT:-8080}"

if [ "$APP_MODE" = "api" ]; then
    echo "Starting FastAPI backend on port $PORT..."
    exec uvicorn backend.main:app \
        --host 0.0.0.0 \
        --port "$PORT" \
        --workers 1
elif [ "$APP_MODE" = "debug" ]; then
    echo "Starting Debug Observation Service on port $PORT..."
    exec streamlit run debug_app.py \
        --server.address=0.0.0.0 \
        --server.port="$PORT" \
        --server.headless=true \
        --server.maxUploadSize=500 \
        --browser.gatherUsageStats=false
else
    echo "Starting RAG Chatbot on port $PORT..."
    exec streamlit run app.py \
        --server.address=0.0.0.0 \
        --server.port="$PORT" \
        --server.headless=true \
        --server.maxUploadSize=500 \
        --server.maxMessageSize=500 \
        --browser.gatherUsageStats=false
fi
