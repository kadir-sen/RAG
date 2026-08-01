# Server'a geçiş — Qdrant + yerel embedding deploy (adım adım)

Server zaten var (Lightsail Frankfurt, `63.184.32.196`, app şu an Pinecone'la çalışıyor).
Yapacağımız: aynı server'a **Qdrant + yerel bge embedding** ile yeniden deploy + yerelde
ürettiğimiz **156.200 vektörü** taşımak. Mevcut genel runbook: [LIGHTSAIL_DEPLOYMENT.md](LIGHTSAIL_DEPLOYMENT.md).

Önkoşullar (kontrol edildi ✓): SSH key `~/Downloads/LightsailDefaultKey-eu-central-1.pem`,
`.env.production` mevcut (eski Pinecone — güncellenecek).

---

## RAM: 2 GB'ta kalıyoruz → fastembed (torch yok)

Karar: **2 GB**. Bunun için sorgu embedding'i **fastembed (ONNX bge-base)** ile yapılıyor —
torch yüklenmiyor. Ölçülen app process peak ~**861 MB** (torch ~1.3-1.5 GB'a karşı). Ayrı
container'daki Qdrant (int8 ~400 MB) + OS ile birlikte 2 GB + 2 GB swap'a sığar.
`.env.production`'da `EMBEDDING_PROVIDER=fastembed` (aşağıda). Sentence-transformers/torch
imaja girmez → imaj da küçülür. Retrieval uyumu kanıtlandı (st-bge ile birebir sonuçlar).

---

## Adım 1 — `.env.production`'ı güncelle (yerelde, secret'a dokunmadan)

Mevcut dosyada `GOOGLE_API_KEY` zaten var; sadece şu satırları **ekle/değiştir** (Pinecone'u yorumla):
```ini
VECTOR_STORE_BACKEND=qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
QDRANT_COLLECTION=coair
EMBEDDING_PROVIDER=fastembed
LOCAL_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
# PINECONE_API_KEY=...        # artık gerekmiyor
# PINECONE_INDEX_NAME=...
```
`chmod 600 .env.production` (zaten öyle). **Asla commit etme.**

## Adım 2 — App'i deploy et (Mac'ten)

```bash
cd /Users/kadirsen/Desktop/projects/ML_project_V2
./scripts/deploy_lightsail.sh                 # PDF'siz: image + compose + .env + lexical store
```
- Yeni imaj torch + bge gömülü → **daha büyük (~3-4 GB), build + transfer daha yavaş** (gzip ~1.5 GB). İlk seferde dakikalar sürer.
- `docker-compose.prod.yml`'deki `qdrant` servisi server'da başlar.
- **PDF'ler (17 GB) gönderilmez.** "Orijinal PDF'i aç" özelliğini server'da da istiyorsan: `./scripts/deploy_lightsail.sh --with-data` (ama 17 GB transfer — yavaş; istemiyorsan düz komutu kullan, vektörler sorgu için yeter).
- Lexical chunk_store (`storage/chunks/`) `--with-data` ile gider; sadece düz deploy yaptıysan Adım 3'te storage'ı ayrıca rsync'le.

## Adım 3 — 156k vektörü taşı (script bunu yapmıyor — manuel)

Qdrant'ın on-disk verisini **tutarlı kopyalamak için her iki tarafı da durdur**, sonra rsync:
```bash
SSH_KEY=~/Downloads/LightsailDefaultKey-eu-central-1.pem
SRV=ubuntu@63.184.32.196

# 1) server qdrant'ı durdur (volume'e temiz yazalım)
ssh -i "$SSH_KEY" $SRV "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml stop qdrant"
# 2) YEREL qdrant'ı durdur (on-disk DB tutarlı olsun)
docker stop mvp-qdrant-local
# 3) vektörleri + lexical store'u gönder
rsync -rlvz -e "ssh -i $SSH_KEY" qdrant_storage/ $SRV:/opt/mvp-api/qdrant_storage/
rsync -rlvz -e "ssh -i $SSH_KEY" storage/        $SRV:/opt/mvp-api/storage/
# 4) ikisini de geri kaldır
docker start mvp-qdrant-local
ssh -i "$SSH_KEY" $SRV "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml up -d"
```
> Alternatif (durdurmadan): Qdrant snapshot — bkz. [QDRANT_MIGRATION.md](QDRANT_MIGRATION.md) Yol B.

## Adım 4 — Doğrula

```bash
curl -i http://63.184.32.196/api/health                 # 200 {"status":"ok"}
# Qdrant içeride (public değil) — server üzerinden say:
ssh -i "$SSH_KEY" $SRV "curl -s localhost:6333/collections/coair | python3 -c 'import sys,json;print(json.load(sys.stdin)[\"result\"][\"points_count\"])'"
# → 156200 görmeli
```
UI'da bir sorgu çalıştır → cevap + kaynaklar gelmeli (hybrid retrieval aktif, lexical store taşındı).

## Adım 5 — (Sonra) Öğrenme katmanlarını doldur — server'da Gemini çalışır

Edinburgh embeddings-only ingest edildi; event-timeline/jargon için **enrichment server'da koşmalı**
(Gemini Py3.11'de çalışır). Bunun için doc başına `_enrich_document_llm`'i çağıran küçük bir batch
script'i gerekiyor (henüz yok — **sıradaki iş**). Üretildikten sonra:
```bash
# server'da:
PYTHONPATH=. python scripts/build_event_timeline.py --project "Edinburgh Tram Inquiry"
```

---

## Notlar
- `.env.production` ve `*.pem` `.gitignore`'da; asla commit edilmez.
- Qdrant (6333) public açılmaz — sadece host:80 → container:8000.
- OOM olursa: `ssh ... "sudo docker logs --tail 100 mvp-api"`; çözüm genelde 4 GB upgrade.
- Bahsettiğin `client_secret_*.json` (job_hunter) bir Google OAuth gizli anahtarı — deploy ile ilgisi yok, paylaşma/commit'leme.
