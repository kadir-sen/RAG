# Qdrant + local-embedding: local ingest → server, doğru taşıma

Kısa cevap: **evet, düzgün taşınır.** İki yol var; ikisinde de tek kritik kural aynı.

## ⚠️ Tek kritik kural — embedding tutarlılığı
Vektörleri OLUŞTURAN model ile, server'da SORGULARI gömecek model **aynı** olmalı.
Yerelde `bge-base-en-v1.5` ile ingest ettiysen, server da `EMBEDDING_PROVIDER=local`
+ `LOCAL_EMBEDDING_MODEL=BAAI/bge-base-en-v1.5` kullanmalı. Aksi halde sorgu vektörleri
farklı uzaya düşer ve retrieval sessizce çöp döndürür.
- Kod artık bunu açılışta **kontrol ediyor**: model boyutu `EMBEDDING_DIMENSION`'a
  uymazsa net hata verir (`document_rag.py::_build_embed_model`).
- `.env.production.example` bu bloğu doğru ayarla geliyor; Dockerfile modeli imaja
  **gömüyor** (server'da ilk-sorguda indirme yok).

---

## Yol A — Tünel (önerilen): yerelde göm, doğrudan server Qdrant'a yaz
Vektörler doğrudan server'a yazılır; sonradan "taşıma" adımı YOK.

```bash
# 1) Server'da Qdrant'ı ayağa kaldır (compose)
ssh <server> "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml up -d qdrant"

# 2) Qdrant'ı public açmadan yerele tünelle
ssh -L 6333:localhost:6333 <server>     # bu oturum açık kalsın

# 3) Yerelde ingest et → vektörler tünelden server Qdrant'a
QDRANT_URL=http://localhost:6333 \
VECTOR_STORE_BACKEND=qdrant \
QDRANT_COLLECTION=coair \
EMBEDDING_PROVIDER=local \
PYTHONPATH=. .venv/bin/python scripts/reingest_local_data.py
```
M4'te OCR+embedding hızlı/ücretsiz; `coair` collection on-disk+int8 olarak server'da
oluşur. Bitince server zaten dolu.

## Yol B — Snapshot (yerelde tam hazırla, sonra gönder)
Yerelde bir Qdrant'a göm, collection snapshot'ını al, server'a kopyala, restore et.

```bash
# 1) Yerel Qdrant
docker run -d --name qdrant-local -p 6333:6333 -v $PWD/qdrant_storage:/qdrant/storage qdrant/qdrant:v1.15.4

# 2) Yerelde ingest (QDRANT_URL=http://localhost:6333, ayarlar Yol A'daki gibi)

# 3) Snapshot al
curl -s -X POST http://localhost:6333/collections/coair/snapshots | python -m json.tool
#   → /qdrant_storage/snapshots/coair/<snapshot>.snapshot dosyası oluşur

# 4) Server'a kopyala + restore et
scp qdrant_storage/snapshots/coair/<snapshot>.snapshot <server>:/tmp/
ssh <server> 'curl -s -X PUT "http://localhost:6333/collections/coair/snapshots/recover" \
  -H "Content-Type: application/json" \
  -d "{\"location\":\"file:///tmp/<snapshot>.snapshot\"}"'
```
> Snapshot collection ayarlarını (on-disk+int8, boyut) da taşır — restore sonrası
> aynı konfigürasyonla gelir.

---

## Doğrulama (her iki yolda)
```bash
# server'da vektör sayısı
ssh <server> 'curl -s http://localhost:6333/collections/coair | python -m json.tool | grep points_count'
# API'de isimli-doc + normal sorgu boş dönmemeli (named-doc düzeltmesi)
```
Beklenen: `points_count` > 0; "X tarafından gönderilen belgeler" gibi scoped sorgu
doğru altkümeyi döndürür.
