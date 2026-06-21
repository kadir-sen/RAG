# COAir — Yerel embedding + Qdrant + öğrenen katmanlar · HANDOFF / RESUME

> Bu dosya, session kapansa bile işe kaldığı yerden devam edebilmek için yazıldı.
> Onaylı plan: `~/.claude/plans/17-06-2026-21-00-02-ozan-altun-cheerful-hamming.md`
> İlgili dokümanlar: [QDRANT_MIGRATION.md](QDRANT_MIGRATION.md), `data/edinburgh_tram/README.md`

Son güncelleme: 2026-06-20.

---

## 1. NEREDE KALDIK (anlık durum)

| Şey | Durum |
|-----|-------|
| Edinburgh Tram PDF korpusu | ✅ **7.289 / 7.289** inik (~17 GB) → `data/edinburgh_tram/pdfs/` |
| Manifest / index | ✅ `data/edinburgh_tram/manifest.csv` + `.json` (7.289 satır) |
| Yerel embedding (bge-base) + Qdrant backend | ✅ kod hazır + smoke/validation geçti |
| Risk düzeltmeleri + migration runbook | ✅ |
| Paralel embed altyapısı | ✅ `scripts/parallel_embed.py` (4 worker, resumable) |
| **Tam ingestion (lokal Qdrant)** | ✅ **BİTTİ** — 7.289/7.289 belge, **156.200 vektör**, 0 başarısız. Scoped payload da uygulandı (~%99 damgalı). Retrieval (semantik + scoped + named-doc) doğrulandı. |
| **Faz 1: scoped metadata payload** | ✅ `scripts/enrich_payload.py` + `_vector_query(payload_filters=...)` — canlı test edildi |
| **Faz 1: birleşik enrichment** | ✅ `file_router._enrich_document_llm` tek çağrıda summary+topics+doc_type+events+new_terms → `storage/enrichment/{doc_id}.json` (Gemini gerektirir → server'da; mock test geçti) |
| **Sistem denetimi** (token/halüsinasyon/knowledge) | ✅ yapıldı — bulgu: embeddings-only ingest yüzünden Edinburgh'da knowledge/öğrenme katmanları boştu |
| **Faz 2: lexical backfill** | ✅ `scripts/backfill_chunkstore.py` — Qdrant'tan chunk_store'a (135.451 chunk) → **hybrid retrieval (dense+BM25+RRF) geri açıldı**, test edildi |
| **Faz 2: event-timeline** | ✅ `src/event_timeline.py` (DuckDB events store: delay/disruption/**excuse**/decision/milestone, kronolojik SQL) + `scripts/build_event_timeline.py` (enrichment'tan besler). Mock test geçti; gerçek veri için server'da enrichment gerek. |
| Faz 2/3 kalan (öğrenen jargon, RAPTOR, router wiring, server enrichment) | ⬜ yapılmadı |

**Önemli:** Ingestion `--skip-existing` mantığıyla resumable. Tekrar başlatınca Qdrant'ta zaten olan belgeleri atlar, kaldığı yerden sürer. Veri kaybı yok.

---

## 2. AKŞAM DEVAM ETMEK İÇİN — TEK KOMUT

### Önkoşul: Qdrant ayakta mı?
```bash
docker ps --filter name=mvp-qdrant-local           # "Up ..." görmeli
# Yoksa (Mac yeniden başladıysa) aynı volume ile tekrar kaldır — veri diskte durur:
cd /Users/kadirsen/Desktop/projects/ML_project_V2
docker start mvp-qdrant-local 2>/dev/null || \
docker run -d --name mvp-qdrant-local -p 6333:6333 \
  -v "$PWD/qdrant_storage:/qdrant/storage" qdrant/qdrant:v1.15.4
curl -s http://localhost:6333/collections/coair | python -m json.tool | grep points_count
```

### Ingestion'ı kaldığı yerden sürdür (resume)
```bash
cd /Users/kadirsen/Desktop/projects/ML_project_V2
INGEST_EXTRACT_TABLES=false INGEST_EXTRACT_NOTICES=false \
VECTOR_STORE_BACKEND=qdrant QDRANT_URL=http://localhost:6333 QDRANT_COLLECTION=coair \
EMBEDDING_PROVIDER=local EMBEDDING_DEVICE=cpu GOOGLE_API_KEY=dummy \
PYTHONPATH=. .venv/bin/python -u scripts/parallel_embed.py \
  --source-dir data/edinburgh_tram/pdfs --workers 4 > /tmp/pe_full.log 2>&1 &
```
- Zaten gömülü belgeleri **otomatik atlar** (her dosyada Qdrant'ta var-mı kontrolü).
- İlerleme: `curl -s localhost:6333/collections/coair | python -m json.tool | grep points_count`
- Beklenen kalan süre: değişken (CEC e-postaları hızlı, büyük taranmış belgeler yavaş) → ~5-9 saat.

### İlerlemeyi izleme
```bash
tail -f /tmp/pe_full.log | grep --line-buffered "Added |"     # tamamlanan belgeler
watch -n 30 'curl -s localhost:6333/collections/coair | python -c "import sys,json;print(json.load(sys.stdin)[\"result\"][\"points_count\"])"'
```

---

## 3. SIFIRDAN HER ŞEY NASIL ÇALIŞIR (referans)

### 3a. PDF'leri indir (gerekirse)
```bash
PYTHONPATH=. .venv/bin/python scripts/download_edinburgh_tram.py
```
- Edinburgh Tram Inquiry FacetWP API + `curl_cffi` (site WAF tarayıcı-TLS istiyor).
- Resumable, `url_map.json` cache'li. Çıktı `data/edinburgh_tram/` (git-ignored).

### 3b. Embedding/ingestion (yerel, ücretsiz)
- Embedding: **bge-base-en-v1.5 (768d)**, `EMBEDDING_PROVIDER=local` (M4'te CPU/MPS, ücretsiz).
- Vektör store: **Qdrant** (on-disk + int8 quantization, 2 GB kutuya sığar).
- İki ingestion yolu:
  - **Paralel (hızlı, embeddings-only):** `scripts/parallel_embed.py` — chunk_store/registry/graph YAZMAZ (process-safe). Faz 2 bunları ayrı batch'te kurar.
  - **Tam pipeline (tek-proc):** `scripts/reingest_local_data.py --source-dir ... [--skip-existing] [--no-cluster]` — route_file (notice/graph/table dahil; yavaş).

### 3c. Sorgu / retrieval doğrulama (örnek)
```bash
VECTOR_STORE_BACKEND=qdrant QDRANT_URL=http://localhost:6333 QDRANT_COLLECTION=coair \
EMBEDDING_PROVIDER=local GOOGLE_API_KEY=dummy PYTHONPATH=. .venv/bin/python - <<'PY'
from src.document_rag import DocumentRAG
from llama_index.core import Settings
rag = DocumentRAG(); rag.load_index()
qv = Settings.embed_model.get_query_embedding("construction delays and extensions of time")
for r in rag._vector_query(qv, top_k=5):
    print(round(r['score'],3), r['metadata'].get('file_name'), r['text'][:70])
PY
```

---

## 4. NE DEĞİŞTİ (kod) — commit edilmemiş

**Yeni dosyalar:**
- `scripts/download_edinburgh_tram.py` — korpus indirici (FacetWP + curl_cffi).
- `scripts/parallel_embed.py` — paralel resumable embedding pass.
- `docs/QDRANT_MIGRATION.md` — yerel→server taşıma runbook (tünel + snapshot).
- `docs/COAIR_QDRANT_HANDOFF.md` — bu dosya.

**Değişen dosyalar:**
- `src/config.py` — `EMBEDDING_PROVIDER/LOCAL_EMBEDDING_MODEL/EMBEDDING_DEVICE`, `INGEST_EXTRACT_TABLES`, `INGEST_EXTRACT_NOTICES`.
- `src/document_rag.py` — `_build_embed_model` (local/gemini + dim-guard), lazy-Gemini, Qdrant on-disk+int8, concurrency-safe collection create, backend-agnostic `_vector_query`/`fetch_doc_vectors`, `embed_file_to_vectors` (parallel-safe), named-doc fetch Qdrant'a portlandı, query-engine None-llm guard.
- `src/document_clusterer.py` — centroid fetch backend-agnostic (`rag.fetch_doc_vectors`).
- `src/file_router.py` — table & notice extraction `INGEST_EXTRACT_*` bayraklarıyla gate'lendi.
- `scripts/reingest_local_data.py` — `--source-dir`, `--limit`, `--no-cluster`, `--skip-existing`.
- `docker-compose.prod.yml` — `qdrant` servisi (iç-network, on-disk volume).
- `.env.production.example` — qdrant + local-embedding önerilen blok.
- `Dockerfile` — CPU-only torch + bge modelini imaja prebake.
- `requirements.txt` — `llama-index-embeddings-huggingface`, `sentence-transformers`, `curl_cffi`.

> **Commit önerisi:** Kendi dosyalarımla sınırlı (`git add -A` DEĞİL — repo'da bana ait olmayan untracked dosyalar var: `designer-pack*`, `.playwright-mcp/`, `docs/JOB_HUNTER_DEPLOYMENT.md`, `docs/coair-architecture-mermaid-prompt.md`). İki mantıksal commit: (1) korpus indirme aracı, (2) local-embedding + Qdrant backend + parallel ingest.

---

## 5. GOTCHA'LAR (yeni session bunları bilmeli)

1. **Python 3.14 + protobuf:** `.venv` Python 3.14. Eski `google.generativeai` + protobuf 4.x → `TypeError: Metaclasses with custom tp_new`. Çözüm zaten uygulandı: `protobuf>=7` (7.35.1). **Prod Docker Python 3.11 → etkilenmez.** Yerelde Gemini LLM wrapper yine de kırık olabilir → enrichment best-effort atlanır (embedding'i etkilemez).
2. **`.venv`'e elle kurulan deklare-bağımlılıklar:** openpyxl, curl_cffi, sentence-transformers, llama-index-embeddings-huggingface, qdrant-client, llama-index-vector-stores-qdrant, llama-index-llms-gemini, pytesseract, pdfplumber, Pillow. (Hepsi requirements'ta var; `.venv` eksikti.) Ayrıca **tesseract** binary: `brew install tesseract`.
3. **OCR contention:** Paralel worker'larda tesseract'ı tek-thread'e sabitlemek şart (`OMP_THREAD_LIMIT=1` — parallel_embed.py içinde). Yoksa 26s/sayfa'ya çıkar. OCR sonuçları `.cache/ocr`'da cache'li → re-run hızlanır.
4. **Embedding tutarlılığı:** Vektörleri oluşturan model = sorguları gömecek model olmalı (bge-base 768d). Server'da da `EMBEDDING_PROVIDER=local` + aynı model. `document_rag._build_embed_model` açılışta dim'i kontrol eder.
5. **Qdrant verisi:** `qdrant_storage/` volume'ünde (git-ignored). Container silinse bile veri durur; aynı volume ile tekrar kaldır.

---

## 6. SIRADAKİ İŞ (ingestion bitince)

**Faz 1 kalanı:**
- Birleşik enrichment: `file_router._enrich_document_llm` tek LLM çağrısında `summary + topics + doc_type + events[] + new_terms[]` döndürsün.
- Scoped metadata payload: ingestion'da node payload'ına `project/parties/doc_type/date/reference`; retrieval'a opsiyonel Qdrant payload filtresi.

**Faz 1 çıktılarını çalıştırma:**
- Scoped payload (ingestion bittikten sonra, LLM-free):
  `QDRANT_URL=http://localhost:6333 QDRANT_COLLECTION=coair PYTHONPATH=. .venv/bin/python scripts/enrich_payload.py`
  → her vektöre `project/doc_type/date/reference/title` payload'ı + keyword index. Scoped sorgu: `rag._vector_query(qv, k, payload_filters={"doc_type":"Witness Statement"})`.
- Birleşik enrichment: ingestion route_file ile yapıldığında (Gemini çalışan ortam) otomatik; `storage/enrichment/*.json` üretir (events + new_terms Faz 2 girdisi).

**Faz 2/3 KALAN (öğrenen "RAG ötesi" katmanlar):**
1. **Server'da enrichment batch çalıştır** (Gemini orada çalışıyor) → `storage/enrichment/*.json` üretir (events + new_terms + doc_type). Sonra:
   - `PYTHONPATH=. python scripts/build_event_timeline.py --project "Edinburgh Tram Inquiry"` → events DuckDB'yi doldurur.
   - event-timeline'ı sorgu yoluna bağla ([query_planner.py](../../Desktop/projects/ML_project_V2/src/query_planner.py) `_execute_timeline_step` → `event_timeline.timeline(...)`).
2. **Otomatik jargon madenciliği** (enrichment `new_terms[]` → `jargon_manager.add_custom_term` + `flywheel`'i ingestion'a genişlet).
3. **RAPTOR cluster-özet katmanı** (`document_clusterer` üzerine; cluster özetleri Qdrant `tier=summary`).
4. **Agentic router** (point/scoped/global/timeline dispatch).

> NOT: Enrichment + jargon + RAPTOR özetleri Gemini gerektirir → yerel Py3.14'te kırık, **server'da (Py3.11) çalışır**. Lexical backfill ve event-timeline KODU hazır + test edildi.

**Server'a taşıma:** [QDRANT_MIGRATION.md](QDRANT_MIGRATION.md) — tünel (önerilen) veya snapshot.
