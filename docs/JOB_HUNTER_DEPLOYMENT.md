# job_hunter (Head Hunter) — Aynı Sunucuya Farklı Porta Deploy

Bu doküman, **COAir** (`mvp-api`, bu repo) uygulamasının çalıştığı AWS Lightsail
sunucusuna, **job_hunter / "Head Hunter"** uygulamasını **farklı bir portta**
yan yana (side-by-side) deploy etme adımlarını anlatır.

job_hunter şu an Docker'lı değil; aşağıda hem **Docker** (önerilen) hem de
**native systemd + nginx** yöntemi var.

---

## 1. Sunucu künyesi (mevcut durum)

| Alan | Değer |
|---|---|
| Sağlayıcı | AWS Lightsail |
| Instance | `mvp-api` |
| Bölge | eu-central-1 (Frankfurt) |
| OS | Ubuntu (Lightsail base) |
| Plan | **2 GB RAM / 2 vCPU / 60 GB SSD** |
| Public IPv4 | `63.184.32.196` |
| SSH user | `ubuntu` |
| SSH key | `~/Downloads/LightsailDefaultKey-eu-central-1.pem` (chmod 400) |
| Mevcut app dizini | `/opt/mvp-api` (COAir — dokunma) |
| Yeni app dizini | `/opt/job-hunter` |

```bash
SSH_KEY=~/Downloads/LightsailDefaultKey-eu-central-1.pem
chmod 400 "$SSH_KEY"
ssh -i "$SSH_KEY" ubuntu@63.184.32.196
```

---

## 2. job_hunter mimarisi (neyi deploy ediyoruz)

| Parça | Detay |
|---|---|
| Backend | FastAPI — `uvicorn app.api.main:app`, **port 8000** (container içi) |
| Frontend | Vite + React + TS (`web/`) → `npm run build` → `web/dist` statik |
| Frontend proxy | `/api/*` → `127.0.0.1:8000` (bkz. `web/vite.config.ts`) |
| Kalıcı veri | Dosya tabanlı: `data/` ve `Job_Archive/` (DB yok) |
| Dış servisler | LLM API (OpenAI/Gemini/Anthropic) + Google OAuth |

Endpoint'ler `/api/*` altında (`/api/cv/upload`, `/api/match/...`,
`/api/roadmap`, `/api/payment/...` vb.).

> **Scraping uyarısı:** `requirements.txt` `playwright` içerir; bu yalnızca
> ilan toplama scriptleri içindir (`scripts/ingest_jobs.py`, `link_sourcer.py`).
> Serve edilen API bu scriptleri request anında çağırmaz. Scraping'i **sunucuda
> değil, local'de** çalıştırıp sonucu (`data/`, `Job_Archive/`) sunucuya senkronla.
> Sunucuda Chromium kurmaya gerek yok — 2 GB RAM'i boş yere yer.

---

## 3. ⚠️ Kaynak uyarısı (2 GB RAM)

Sunucu sadece 2 GB RAM ve COAir zaten orada çalışıyor (+ 2 GB swap).
job_hunter'ın serve katmanı pingulacore kadar ağır değil (Chromium kurmuyorsak),
ama yine de:

- COAir + job_hunter Python/uvicorn süreçleri taban RAM'i yükseltir.
- LLM çağrıları dış API'ye gider (local RAM az), ama embedding `mock` değilse
  yerel model yüklenirse RAM artar — **`EMBEDDING_PROVIDER=mock` veya dış API**
  kullanın, yerel model yüklemeyin.
- Vite/npm build sunucuda yapılırsa OOM riski var → **imajı local'de build edip
  gönderin** (Bölüm 6, Yöntem A önerisi) ya da swap'ı 4 GB'a çıkarın (Ek-A).

Production yük bekliyorsanız doğru hamle ayrı/daha büyük instance'tır
(Lightsail 4 GB ~ $24/ay).

---

## 4. Portlar — mevcut durum ve plan

### 4a. Lightsail firewall'da şu an açık portlar

Lightsail konsolu → instance `mvp-api` → Networking → IPv4 Firewall:

| Port | Protokol | Kullanım | Açık mı? |
|---|---|---|---|
| 22 | TCP | SSH | ✅ Açık |
| 80 | TCP | HTTP (COAir) | ✅ Açık |
| 443 | TCP | HTTPS (TLS eklendiğinde) | ✅ Açık |
| 6333 / 6334 | TCP | Qdrant | ❌ Kapalı (kullanılmıyor) |
| 8000 | TCP | Ham API | ❌ Kapalı (yalnızca 80 üzerinden) |

### 4b. Host (sunucu içi) port kullanımı

COAir compose'u (`docker-compose.prod.yml`) container'ı **loopback**'e bağlıyor:

```yaml
ports:
  - "127.0.0.1:8000:8000"   # sadece localhost
```

> **Doğrulanacak:** Public 80'i ya **host nginx** ya da **docker-proxy**
> dinliyor (repo içinde iki farklı anlatım mevcut). Gerçeği Bölüm 5'teki
> komutlarla teyit edin; yönlendirme yöntemini bu belirler.

### 4c. job_hunter için seçilen portlar

| Servis | Public port | Host bağlama | Not |
|---|---|---|---|
| COAir (mevcut) | 80 | `127.0.0.1:8000` | değişmez |
| **job_hunter UI (yeni)** | **8081** | host 8081 → ui:80 | Lightsail'de 8081 açılacak |
| job_hunter API | — | container içi 8000 | **host'a publish ETME** |

Kritik nokta: **job_hunter API'si de içeride 8000 dinler**, ama her Docker
compose projesi kendi izole ağında olduğu için bu COAir'in `127.0.0.1:8000`'i
ile **çakışmaz** — yeter ki job_hunter API'sini host'a publish etmeyin.
Native (Docker'sız) kurulumda ise COAir loopback 8000'i tuttuğundan,
job_hunter backend'ini **8001**'e alın (Yöntem B).

---

## 5. Deploy öncesi: sunucunun gerçek durumunu teyit et

```bash
sudo docker ps                                   # çalışan container'lar
sudo ss -tulpn | grep -E ':80|:443|:8000|:8081'  # 80'i kim tutuyor, 8081 boş mu
systemctl is-active nginx 2>/dev/null || echo "host nginx YOK"
ls -l /etc/nginx/sites-available/ 2>/dev/null || echo "nginx config dizini yok"
free -h && df -h /                               # RAM/disk uygun mu
```

- **Host nginx var/aktifse** → Bölüm 6, **Yöntem C** (nginx reverse proxy,
  TLS'e hazır) en temizi.
- **Host nginx yoksa** → **Yöntem A** (Docker + port 8081 expose) en hızlısı.

---

## 6. Deploy yöntemleri

### Yöntem A — Docker (önerilen): api + ui iki container, host 8081

job_hunter'da Docker yok; iki Dockerfile + bir compose ekleyeceğiz.
**Reponun kökünde** (`~/Desktop/projects/job_hunter`) şu dosyaları oluşturun.

**`api.Dockerfile`** (FastAPI backend — Chromium kurmaz):

```dockerfile
FROM python:3.12-slim
WORKDIR /app

# Sistem bağımlılıkları (pdf/docx parse için minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# NOT: playwright wheel kurulur ama `playwright install` (Chromium) ÇALIŞTIRILMAZ.
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**`web/Dockerfile`** (React build → nginx statik + /api proxy):

```dockerfile
FROM node:20-alpine AS build
WORKDIR /web
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

**`web/nginx.conf`** (SPA fallback + `/api` → api container'a proxy):

```nginx
server {
    listen 80;
    server_name _;
    client_max_body_size 25m;          # CV upload için

    root /usr/share/nginx/html;
    index index.html;

    location /api/ {
        proxy_pass http://api:8000;     # compose servis adı "api"
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;        # roadmap üretimi uzun sürebilir
    }

    location / {
        try_files $uri $uri/ /index.html;   # SPA fallback
    }
}
```

**`docker-compose.prod.yml`** (repo kökünde):

```yaml
services:
  api:
    build:
      context: .
      dockerfile: api.Dockerfile
    container_name: job-hunter-api
    env_file:
      - .env.production
    volumes:
      - ./data:/app/data                 # kalıcı: işlenmiş veriler
      - ./Job_Archive:/app/Job_Archive   # kalıcı: ham ilanlar
      # Google OAuth client_secret dosyası (env'de GOOGLE_CLIENT_SECRET_FILE buna işaret etmeli)
      - ./client_secret.json:/app/client_secret.json:ro
    expose:
      - "8000"                           # host'a PUBLISH ETME — sadece iç ağ
    restart: unless-stopped

  ui:
    build:
      context: ./web
      dockerfile: Dockerfile
    container_name: job-hunter-ui
    ports:
      - "8081:80"                        # public: host 8081 -> container 80
    depends_on:
      - api
    restart: unless-stopped
```

**Build stratejisi (2 GB RAM):** Vite + pip build'i sunucuda yapmak OOM
riskidir. İki seçenek:

- **(önerilen) Local'de build → imajı gönder** (COAir'in yaptığı gibi):
  ```bash
  # local Mac (job_hunter kökü), linux/amd64 cross-build
  docker buildx build --platform linux/amd64 --load -t job-hunter-api:latest -f api.Dockerfile .
  docker buildx build --platform linux/amd64 --load -t job-hunter-ui:latest  ./web
  docker save job-hunter-api:latest job-hunter-ui:latest | gzip | \
    ssh -i "$SSH_KEY" ubuntu@63.184.32.196 'gunzip | sudo docker load'
  ```
  Bu durumda compose'daki `build:` yerine `image: job-hunter-api:latest` /
  `image: job-hunter-ui:latest` kullanın.

- **(alternatif) Sunucuda build:** önce swap'ı 4 GB yapın (Ek-A), sonra
  `sudo docker compose -f docker-compose.prod.yml build`.

**Kaynak + env + compose'u sunucuya gönder** (local Mac, job_hunter kökünden):

```bash
SSH_KEY=~/Downloads/LightsailDefaultKey-eu-central-1.pem
ssh -i "$SSH_KEY" ubuntu@63.184.32.196 \
  "mkdir -p /opt/job-hunter/data /opt/job-hunter/Job_Archive"

rsync -az --delete \
  -e "ssh -i $SSH_KEY -o IdentitiesOnly=yes" \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude 'web/node_modules' --exclude 'web/dist' \
  --exclude '.env' --exclude '.env.*' \
  ./ ubuntu@63.184.32.196:/opt/job-hunter/

# prod compose + gerçek secrets ayrı gönder
scp -i "$SSH_KEY" docker-compose.prod.yml ubuntu@63.184.32.196:/opt/job-hunter/
scp -i "$SSH_KEY" .env.production         ubuntu@63.184.32.196:/opt/job-hunter/.env.production
scp -i "$SSH_KEY" client_secret_*.json    ubuntu@63.184.32.196:/opt/job-hunter/client_secret.json
ssh -i "$SSH_KEY" ubuntu@63.184.32.196 "chmod 600 /opt/job-hunter/.env.production /opt/job-hunter/client_secret.json"

# (opsiyonel) local'de scrape edilmiş veriyi gönder
rsync -az -e "ssh -i $SSH_KEY" data/ Job_Archive/ ubuntu@63.184.32.196:/opt/job-hunter/ 2>/dev/null || true
```

`.env.production` içeriği (`.env.example`'dan üretilir):

```dotenv
LLM_PROVIDER=openai            # veya gemini / anthropic (mock = test)
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=
ANTHROPIC_API_KEY=
LOCAL_LLM_BASE_URL=
EMBEDDING_PROVIDER=mock        # yerel model YÜKLEME (RAM); mock ya da dış API
EMBEDDING_MODEL=mock-hash-tfidf
GOOGLE_CLIENT_ID=703245378695-...apps.googleusercontent.com
GOOGLE_CLIENT_SECRET_FILE=/app/client_secret.json
```

**Ayağa kaldır** (sunucuda):

```bash
cd /opt/job-hunter
sudo docker compose -f docker-compose.prod.yml up -d   # local build ettiyseniz --build gerekmez
sudo docker compose -f docker-compose.prod.yml ps
```

### Yöntem C — Host nginx reverse proxy (TLS'e hazır, host nginx varsa)

Yöntem A'daki Docker kurulumunu yapın ama `ui` portunu **public yerine
loopback**'e bağlayın:

```yaml
  ui:
    ports:
      - "127.0.0.1:8081:80"
```

Host nginx'e yeni server bloğu (`/etc/nginx/sites-available/job-hunter`):

```nginx
server {
    listen 80;
    server_name jobs.example.com;     # kendi subdomain'iniz
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/job-hunter /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
# DNS A kaydı jobs.example.com -> 63.184.32.196, sonra:
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d jobs.example.com
```

Bu yöntemde **Lightsail'de yeni port açmaya gerek yok** — trafik 80/443'ten gelir.

### Yöntem B — Docker'sız (native systemd + nginx)

Docker istemiyorsanız:

```bash
# Sunucuda
sudo apt-get install -y python3-venv nginx
cd /opt/job-hunter
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt          # playwright install ÇALIŞTIRMA
deactivate

# Frontend build (local'de yapıp web/dist'i gönderin — sunucuda npm build OOM riski)
# local: cd web && npm ci && npm run build  ->  rsync web/dist -> /opt/job-hunter/web/dist
```

systemd servisi (`/etc/systemd/system/job-hunter.service`) — backend'i
**8001**'e koy (COAir 8000'i kullanıyor):

```ini
[Unit]
Description=job_hunter FastAPI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/job-hunter
EnvironmentFile=/opt/job-hunter/.env.production
ExecStart=/opt/job-hunter/.venv/bin/uvicorn app.api.main:app --host 127.0.0.1 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now job-hunter
```

nginx (`/etc/nginx/sites-available/job-hunter`) — statik dist + `/api` → 8001:

```nginx
server {
    listen 8081;                         # ya da server_name + 80 (Yöntem C gibi)
    root /opt/job-hunter/web/dist;
    index index.html;
    client_max_body_size 25m;

    location /api/ { proxy_pass http://127.0.0.1:8001; proxy_read_timeout 300s; }
    location /     { try_files $uri $uri/ /index.html; }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/job-hunter /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

8081 ile dinliyorsanız Lightsail'de 8081'i açın (Bölüm 7).

---

## 7. Lightsail firewall'da yeni portu aç (Yöntem A veya B'de 8081 expose ediliyorsa)

Lightsail konsolu → `mvp-api` → **Networking** → IPv4 Firewall → **Add rule**:

| Application | Protocol | Port | Source |
|---|---|---|---|
| Custom | TCP | 8081 | Anywhere (0.0.0.0/0) |

Güncellenmiş hedef tablo:

| Port | Kullanım | Açık? |
|---|---|---|
| 22 | SSH | ✅ |
| 80 | COAir HTTP | ✅ |
| 443 | HTTPS | ✅ |
| **8081** | **job_hunter UI (yeni)** | ✅ (eklenecek) |
| 8000 / 6333 / 6334 | iç servisler | ❌ (kapalı kalmalı) |

> Yöntem C'de (host nginx) bu adımı atlayın — yeni port gerekmez.

---

## 8. Google OAuth redirect URI (önemli)

job_hunter Google ile giriş kullanıyor. Google Cloud Console → Credentials →
OAuth 2.0 Client → **Authorized redirect URIs**'e yeni public adresi ekleyin:

- Yöntem A: `http://63.184.32.196:8081/...` (callback path'i `routes_auth.py`'den teyit edin)
- Yöntem C: `https://jobs.example.com/...`

Aksi halde giriş `redirect_uri_mismatch` hatası verir.

---

## 9. Doğrulama

```bash
# Yöntem A / B
curl -i http://63.184.32.196:8081/               # 200, SPA HTML
curl -i http://63.184.32.196:8081/api/jobs       # 200, JSON

# Yöntem C
curl -i https://jobs.example.com/api/jobs        # 200

# COAir regresyon kontrolü (etkilenmemeli)
curl -i http://63.184.32.196/api/health          # {"status":"ok"}
```

Sunucu tarafı:

```bash
sudo docker ps                  # job-hunter-api + job-hunter-ui Up, mvp-api Up
sudo docker stats --no-stream   # toplam RAM < ~1.8 GB
free -h                         # swap patlamamalı
sudo docker logs --tail 50 job-hunter-api   # uvicorn started, hata yok
```

---

## 10. İşletim

| İşlem | Komut (Docker) |
|---|---|
| Loglar | `ssh -i $SSH_KEY ubuntu@63.184.32.196 "sudo docker logs -f job-hunter-api"` |
| Restart | `... "cd /opt/job-hunter && sudo docker compose -f docker-compose.prod.yml restart"` |
| Stop | `... "cd /opt/job-hunter && sudo docker compose -f docker-compose.prod.yml stop"` |
| Güncelle | local build → `docker save \| ssh \| docker load` → `up -d` |
| Veri senkronu | local scrape → `rsync data/ Job_Archive/ ...:/opt/job-hunter/` |

> ⚠️ **Asla** `docker compose down -v` çalıştırmayın. `data/` ve `Job_Archive/`
> bind-mount olduğu için güvende ama alışkanlık edinmeyin.

İki uygulama tamamen izole: ayrı dizin (`/opt/mvp-api` vs `/opt/job-hunter`),
ayrı compose projesi, ayrı container/servis, ayrı ağ. Biri diğerini etkilemez.

---

## Ek-A: Swap'ı 4 GB'a çıkar (2 GB RAM için önerilir)

```bash
sudo swapoff /swapfile
sudo rm -f /swapfile
sudo fallocate -l 4G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=4096
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
grep '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h   # Swap: 4.0Gi
```

## Ek-B: Geri alma (rollback)

```bash
ssh -i "$SSH_KEY" ubuntu@63.184.32.196
cd /opt/job-hunter && sudo docker compose -f docker-compose.prod.yml down   # -v YOK
# Yöntem C/native ise nginx bloğunu kaldır:
sudo rm -f /etc/nginx/sites-enabled/job-hunter && sudo systemctl reload nginx
# native ise: sudo systemctl disable --now job-hunter
```

COAir hiç etkilenmez.

---

## Özet checklist

- [ ] Sunucu durumunu teyit et (Bölüm 5): RAM, nginx var mı, 8081 boş mu
- [ ] Swap'ı 4 GB'a çıkar (Ek-A)
- [ ] job_hunter'a `api.Dockerfile` + `web/Dockerfile` + `web/nginx.conf` + `docker-compose.prod.yml` ekle (Yöntem A)
- [ ] İmajı **local'de** build et → `docker save | ssh | docker load` (OOM'dan kaçın)
- [ ] `/opt/job-hunter` oluştur; kaynak + `.env.production` + `client_secret.json` gönder
- [ ] (varsa) local scrape edilmiş `data/` + `Job_Archive/` senkronla
- [ ] `compose up -d`
- [ ] Lightsail firewall'da 8081 aç (Yöntem A/B) — Yöntem C'de gerekmez
- [ ] Google OAuth redirect URI'ye yeni adresi ekle (Bölüm 8)
- [ ] Doğrula: job_hunter + COAir ikisi de sağlıklı (Bölüm 9)
- [ ] `docker stats` / `free -h` ile birkaç gün RAM izle
