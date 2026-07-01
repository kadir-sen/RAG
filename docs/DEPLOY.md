# Otomatik Deploy (CI/CD)

`main`'e her merge, uygulamayı AWS Lightsail sunucusuna otomatik deploy eder.
Pipeline: [.github/workflows/deploy.yml](../.github/workflows/deploy.yml)

## Akış

```
main'e merge / push
   │
   ├─ 1) Fast tests            (kırmızıysa DURUR — deploy olmaz)
   ├─ 2) Docker image build    → GHCR'a push (ghcr.io/kadir-sen/rag:<sha> + :latest)
   └─ 3) SSH ile Lightsail'e   → yeni image'ı pull + docker compose up -d + health check
```

- **Pull request** açıldığında sadece **testler** koşar (build/deploy yok) — bozuk kod merge'den önce yakalanır.
- **Manuel** çalıştırma: GitHub → **Actions** → bu workflow → **Run workflow**.
- Sunucudaki `.env.production`, `storage/`, `data/`, `qdrant_storage/` **hiç dokunulmaz**. Secret'lar CI loglarına girmez.

## Bir kereye mahsus kurulum

### 1. GitHub Secrets (Settings → Secrets and variables → Actions → New repository secret)

| Secret | Zorunlu | Açıklama |
|---|---|---|
| `LIGHTSAIL_HOST` | ✅ | Sunucu IP veya hostname (ör. `18.184.x.x`) |
| `LIGHTSAIL_USER` | ✅ | SSH kullanıcısı (ör. `ubuntu` / `admin` / `bitnami`) |
| `LIGHTSAIL_SSH_KEY` | ✅ | SSH **private key**'in tamamı (PEM içeriği, `-----BEGIN ... END-----` dahil) |
| `LIGHTSAIL_SSH_PORT` | ➖ | SSH portu — verilmezse `22` |
| `LIGHTSAIL_APP_DIR` | ➖ | Uygulama klasörü — verilmezse `/opt/mvp-api` |

> `GITHUB_TOKEN` otomatik gelir — eklemene gerek yok. Sunucu, GHCR'daki (private) image'ı her deploy'da bu geçici token ile çeker; sunucuda elle `docker login` yapmana gerek yok.

### 2. Sunucu ön koşulları (zaten mevcut kurulumda büyük ölçüde var)

- `LIGHTSAIL_APP_DIR` (varsayılan `/opt/mvp-api`) mevcut ve içinde `.env.production` + `storage/` + `data/` + `qdrant_storage/` var.
- SSH kullanıcısı **docker çalıştırabiliyor** — ya `docker` grubunda, ya da **şifresiz sudo** yetkisi var. (Workflow otomatik algılar: daemon'a doğrudan erişemezse `sudo` kullanır.)
- Host nginx zaten `127.0.0.1:8000` (api) önünde proxy yapıyor — bu değişmez.
- `qdrant` servisi aynı compose içinde ayakta (değişmedi).

### 3. GHCR image erişimi

Image, repo altında **private** bir GHCR paketi olarak yayınlanır. Sunucu her deploy'da workflow'un `GITHUB_TOKEN`'ıyla giriş yapıp çeker.
Eğer organizasyon/paket ayarları `GITHUB_TOKEN` ile pull'u engellerse iki seçenek:
- Paketi **public** yap (Package → Package settings → Change visibility), **veya**
- `read:packages` yetkili bir PAT oluşturup sunucuya bir kez `docker login ghcr.io` yap.

## Deploy'u tetikleme

```bash
# Normal akış: feature dalını main'e merge et → pipeline kendiliğinden çalışır.
git checkout main && git merge feature/... && git push origin main
```

## Rollback (bir önceki sürüme dönme)

```bash
# Sunucuda (APP_DIR içinde) — <onceki_sha> ile eski image'a dön:
echo "API_IMAGE=ghcr.io/kadir-sen/rag:<onceki_sha>" | sudo tee .env
sudo docker compose -f docker-compose.prod.yml pull api
sudo docker compose -f docker-compose.prod.yml up -d
```
veya GitHub → Actions → eski başarılı çalıştırma → **Re-run jobs**.

## (Opsiyonel) Manuel onay kapısı

Workflow `production` environment'ını kullanır. GitHub → Settings → Environments → `production` altında
**Required reviewers** eklersen, her deploy senin onayınla başlar (build biter, deploy onay bekler).
