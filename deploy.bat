@echo off
REM ============================================================
REM  RAG Chatbot - Google Cloud Run Deploy Script
REM ============================================================
REM  Kullanim: deploy.bat
REM
REM  Onkoşullar:
REM   1. Google Cloud SDK kurulu olmali (asagida kurulum var)
REM   2. .env dosyasindaki API key'ler hazir olmali
REM ============================================================

setlocal enabledelayedexpansion

REM ── Ayarlar ──────────────────────────────────────────────
set PROJECT_ID=gen-lang-client-0623898146
set SERVICE_NAME=rag-chatbot
set REGION=europe-west1

echo.
echo ============================================
echo   RAG Chatbot - Cloud Run Deploy
echo ============================================
echo.

REM ── 1. gcloud kurulu mu kontrol et ──────────────────────
where gcloud >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] gcloud CLI bulunamadi.
    echo.
    echo Kurulum icin asagidaki adimlari takip edin:
    echo   1. https://cloud.google.com/sdk/docs/install adresine gidin
    echo   2. "Windows" icin installer'i indirin
    echo   3. Kurun ve bu scripti tekrar calistirin
    echo.
    echo Ya da PowerShell ile hizli kurulum:
    echo   (New-Object Net.WebClient^).DownloadFile("https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe", "$env:temp\gcloud-installer.exe"^); Start-Process "$env:temp\gcloud-installer.exe"
    echo.
    pause
    exit /b 1
)

echo [OK] gcloud CLI bulundu.

REM ── 2. Login kontrol ────────────────────────────────────
echo.
echo [*] Google hesabi kontrol ediliyor...
gcloud auth list --filter=status:ACTIVE --format="value(account)" > nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Google hesabina giris yapiliyor...
    gcloud auth login
)

REM ── 3. Proje olustur veya sec ──────────────────────────
echo.
echo [*] Proje kontrol ediliyor: %PROJECT_ID%
gcloud projects describe %PROJECT_ID% >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Proje olusturuluyor: %PROJECT_ID%
    gcloud projects create %PROJECT_ID% --name="RAG Chatbot"
)

gcloud config set project %PROJECT_ID%
echo [OK] Aktif proje: %PROJECT_ID%

REM ── 4. Billing kontrol (300$ kredi icin gerekli) ────────
echo.
echo [!] ONEMLI: Billing'in aktif oldugundan emin olun.
echo     https://console.cloud.google.com/billing/linkedaccount?project=%PROJECT_ID%
echo     ($300 ucretsiz kredi otomatik baglanir)
echo.
pause

REM ── 5. Gerekli API'leri etkinlestir ────────────────────
echo.
echo [*] API'ler etkinlestiriliyor...
gcloud services enable cloudbuild.googleapis.com --quiet
gcloud services enable run.googleapis.com --quiet
gcloud services enable artifactregistry.googleapis.com --quiet

echo [OK] API'ler hazir.

REM ── 6. .env dosyasindan secret'lari oku ────────────────
echo.
echo [*] API key'ler .env dosyasindan okunuyor...

set ENV_VARS=

for /f "tokens=1,* delims==" %%a in (.env) do (
    set "line=%%a"
    if not "!line:~0,1!"=="#" (
        if not "%%b"=="" (
            if defined ENV_VARS (
                set "ENV_VARS=!ENV_VARS!,%%a=%%b"
            ) else (
                set "ENV_VARS=%%a=%%b"
            )
        )
    )
)

if not defined ENV_VARS (
    echo [!] HATA: .env dosyasi bos veya bulunamadi!
    pause
    exit /b 1
)

echo [OK] API key'ler okundu.

REM ── 7. Deploy Main App to Cloud Run ────────────────────
echo.
echo [*] Ana uygulama Cloud Run'a deploy ediliyor...
echo     Bu islem ilk seferde 5-10 dakika surebilir.
echo.

gcloud run deploy %SERVICE_NAME% ^
    --source=. ^
    --region=%REGION% ^
    --platform=managed ^
    --allow-unauthenticated ^
    --memory=2Gi ^
    --cpu=2 ^
    --timeout=300 ^
    --max-instances=3 ^
    --set-env-vars="%ENV_VARS%,GCS_BUCKET_NAME=rag-chatbot-tables,APP_MODE=api" ^
    --quiet

if %errorlevel% neq 0 (
    echo.
    echo [!] Ana uygulama deploy basarisiz oldu. Hatalari kontrol edin.
    pause
    exit /b 1
)

REM ── 8. Deploy Debug Service to Cloud Run ──────────────
echo.
echo [*] Debug servisi Cloud Run'a deploy ediliyor...
echo.

gcloud run deploy %SERVICE_NAME%-debug ^
    --source=. ^
    --region=%REGION% ^
    --platform=managed ^
    --allow-unauthenticated ^
    --memory=1Gi ^
    --cpu=1 ^
    --timeout=300 ^
    --max-instances=2 ^
    --set-env-vars="%ENV_VARS%,GCS_BUCKET_NAME=rag-chatbot-tables,APP_MODE=debug" ^
    --quiet

if %errorlevel% neq 0 (
    echo.
    echo [!] Debug servisi deploy basarisiz oldu (opsiyonel, devam ediliyor).
)

REM ── 9. URL'leri al ─────────────────────────────────────
echo.
echo ============================================
echo   DEPLOY BASARILI!
echo ============================================
echo.

echo [Ana Uygulama URL]:
gcloud run services describe %SERVICE_NAME% --region=%REGION% --format="value(status.url)"

echo.
echo [Debug Servisi URL]:
gcloud run services describe %SERVICE_NAME%-debug --region=%REGION% --format="value(status.url)" 2>nul
if %errorlevel% neq 0 (
    echo   Debug servisi deploy edilmemis.
)

echo.
echo Giris bilgileri (ana uygulama):
echo   admin / admin123
echo   user1 / user123
echo   user2 / user123
echo.
echo Debug servisi: Giris gerektirmez, sadece gozlem amacli.
echo ============================================
echo.
pause
