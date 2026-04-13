#!/bin/bash
# ============================================================
#  RAG Chatbot - Google Cloud Run Deploy Script (macOS)
# ============================================================

set -e

# ── Settings ──────────────────────────────────────────────
PROJECT_ID="gen-lang-client-0623898146"
SERVICE_NAME="rag-chatbot"
REGION="europe-west1"
GCLOUD="$(which gcloud 2>/dev/null || echo /opt/homebrew/bin/gcloud)"

echo ""
echo "============================================"
echo "  RAG Chatbot - Cloud Run Deploy (macOS)"
echo "============================================"
echo ""

# ── 1. Check gcloud ──────────────────────────────────────
if [ ! -f "$GCLOUD" ]; then
    echo "[!] gcloud CLI bulunamadi: $GCLOUD"
    echo "    Kurulum: curl https://sdk.cloud.google.com | bash"
    exit 1
fi
echo "[OK] gcloud CLI bulundu: $($GCLOUD --version 2>&1 | head -1)"

# ── 2. Auth check / login ────────────────────────────────
ACCOUNT=$($GCLOUD auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null || true)
if [ -z "$ACCOUNT" ]; then
    echo "[*] Google hesabina giris yapiliyor..."
    $GCLOUD auth login
else
    echo "[OK] Aktif hesap: $ACCOUNT"
fi

# ── 3. Set project ───────────────────────────────────────
echo ""
echo "[*] Proje ayarlaniyor: $PROJECT_ID"
$GCLOUD config set project "$PROJECT_ID" --quiet
echo "[OK] Aktif proje: $PROJECT_ID"

# ── 4. Enable APIs ───────────────────────────────────────
echo ""
echo "[*] API'ler etkinlestiriliyor..."
$GCLOUD services enable cloudbuild.googleapis.com --quiet
$GCLOUD services enable run.googleapis.com --quiet
$GCLOUD services enable artifactregistry.googleapis.com --quiet
echo "[OK] API'ler hazir."

# ── 5. Read .env vars ────────────────────────────────────
echo ""
echo "[*] API key'ler .env dosyasindan okunuyor..."
ENV_VARS=""
while IFS='=' read -r key value; do
    # Skip comments and empty lines
    [[ "$key" =~ ^#.*$ || -z "$key" || -z "$value" ]] && continue
    if [ -z "$ENV_VARS" ]; then
        ENV_VARS="${key}=${value}"
    else
        ENV_VARS="${ENV_VARS},${key}=${value}"
    fi
done < .env

if [ -z "$ENV_VARS" ]; then
    echo "[!] HATA: .env dosyasi bos veya bulunamadi!"
    exit 1
fi
echo "[OK] API key'ler okundu."

# ── 6. Build frontend ────────────────────────────────────
echo ""
echo "[*] Frontend build ediliyor..."
if command -v npm &>/dev/null; then
    cd frontend && npm run build && cd ..
    echo "[OK] Frontend build tamam."
else
    echo "[!] Node.js bulunamadi, frontend build atlaniyor."
    echo "    Dockerfile icinde build edilecek."
fi

# ── 7. Deploy to Cloud Run ───────────────────────────────
echo ""
echo "[*] Cloud Run'a deploy ediliyor..."
echo "    Bu islem ilk seferde 5-10 dakika surebilir."
echo ""

$GCLOUD run deploy "$SERVICE_NAME" \
    --source=. \
    --region="$REGION" \
    --platform=managed \
    --allow-unauthenticated \
    --memory=2Gi \
    --cpu=2 \
    --timeout=300 \
    --max-instances=3 \
    --set-env-vars="${ENV_VARS},GCS_BUCKET_NAME=rag-chatbot-tables,APP_MODE=api" \
    --quiet

if [ $? -ne 0 ]; then
    echo ""
    echo "[!] Deploy basarisiz oldu. Hatalari kontrol edin."
    exit 1
fi

# ── 8. Get URL ────────────────────────────────────────────
echo ""
echo "============================================"
echo "  DEPLOY BASARILI!"
echo "============================================"
echo ""

SERVICE_URL=$($GCLOUD run services describe "$SERVICE_NAME" --region="$REGION" --format="value(status.url)" 2>/dev/null)
echo "[URL]: $SERVICE_URL"
echo ""
echo "============================================"
echo ""
