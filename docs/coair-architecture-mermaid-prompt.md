# COAir Mimari İnfografik Prompt'u (Mermaid)

> Bu dosyadaki **prompt'u** bir LLM'e (Claude / GPT) yapıştır → COAir mimarisinin 7 katmanlı
> Mermaid diyagram setini Türkçe etiketlerle üretir. Çıktıyı https://mermaid.live veya VS Code
> Mermaid önizlemesinde render et.

---

# GÖREV: COAir Mimari İnfografiği — Mermaid Diyagram Seti Üret

Sen kıdemli bir yazılım mimarisi diyagramcısısın. Aşağıda mimarisi **tam olarak** verilen
**COAir** (inşaat projeleri için hibrit RAG chatbot) uygulamasını, **Mermaid diyagram koduyla**,
**adım adım, çok katmanlı bir infografik seti** olarak üreteceksin. Diyagram etiketleri
**Türkçe**, teknik terimler (RAG, embedding, DuckDB, Pinecone, schema, LLM, SQL...) korunur.

## ÇIKTI KURALLARI
1. Her diyagramı ayrı bir ` ```mermaid ... ``` ` bloğunda ver; her bloğun üstüne `##` ile Türkçe başlık koy.
2. Aşağıdaki **7 diyagramı** sırasıyla, eksiksiz üret.
3. **Ortak renk sınıfları** (her diyagramda `classDef` ile tanımla ve uygula):
   - `classDef ui fill:#16321f,stroke:#34d399,color:#d1fae5;` → Frontend / UI yüzeyi
   - `classDef api fill:#0c2740,stroke:#38bdf8,color:#e0f2fe;` → API endpoint (FastAPI)
   - `classDef det fill:#1f2430,stroke:#9aa4b2,color:#e5e7eb;` → Deterministik (regex/keyword/kural, LLM yok)
   - `classDef llm fill:#3a2410,stroke:#f59e0b,color:#fde68a;` → Tek LLM çağrısı
   - `classDef agent fill:#3a1020,stroke:#fb7185,color:#fecdd3;` → Çok adımlı AGENT (döngü/plan)
   - `classDef store fill:#10243a,stroke:#60a5fa,color:#dbeafe;` → Veri deposu (Pinecone/DuckDB/Parquet/LightGraph/Registry)
4. Düğüm şekilleri: işlem `[...]`, karar `{...}`, veri deposu `[(...)]`, agent `((...))`, dış girdi `>...]`.
5. Okların üstüne **ne taşındığını** yaz (ör. `-->|embedding|`, `-->|top_k chunk|`, `-->|SQL|`, `-->|satırlar|`, `-->|citations|`, `-->|notice metadata|`).
6. Her diyagrama küçük bir **Lejant** subgraph'ı ekle (renk sınıflarını açıklayan).
7. Mermaid sözdizimi geçerli olsun: node id'leri ASCII (ör. `RAG`, `SQLAgent`), Türkçe karakterli etiketleri tırnakla (`["Şema eşleştirme"]`). Özel karakterleri (`()`, `:`) etiket içinde kullanırken tırnak kullan.

## DOĞRULANMIŞ MİMARİ (ground truth — diyagramlar buna birebir uymalı)

### Teknoloji yığını ve veri depoları
- **Frontend:** React + TypeScript (Vite). **Backend:** FastAPI (`backend/`). **Motor:** `src/`.
- **Vektör deposu:** Pinecone (index `hybrid-rag`), embedding `gemini-embedding-001` (768 boyut, cosine). Chunk'lama: LlamaIndex SentenceSplitter (CHUNK_SIZE=1024, CHUNK_OVERLAP=200).
- **Tablo deposu:** Parquet dosyaları + **DuckDB** (in-memory; SQL sorguları için).
- **İlişki/zaman çizelgesi grafiği:** **LightGraph** (in-memory DuckDB + JSON `notices` tablosu) — yazışma/notice metadata'sı.
- **Kayıt defteri:** DocumentRegistry (`storage/document_registry.json`), DocumentClusterer (kümeleme), Catalog (`storage/parquet/catalog.json`).
- **Varsayılan LLM:** Gemini 2.5 Flash (ucuz/hızlı). Dual-provider kapalı (ENABLE_DUAL_PROVIDER=false). MAX_LLM_CALLS_PER_QUERY=4.

### Desteklenen formatlar ve ingestion yolları (3 kol)
Uzantıya göre `file_router.route_file` 3 kola ayırır:
- **DOKÜMAN kolu** — `.pdf`, `.docx`, `.txt`:
  - Parse (PDF sayfa-sayfa), gerekiyorsa **OCR** (Tesseract, mod=auto: taranmış/az-metinli sayfalarda).
  - Chunk → **embedding** → **Pinecone**'a yaz. Her chunk'a metadata: `doc_id, file_name, page_number, total_pages, extraction_method (native|ocr), ocr_*`.
  - Ayrıca **notice metadata** çıkarımı (regex-öncelikli; date/sender/recipient/subject/doc_type/ref_numbers/actions/summary).
- **VERİ kolu** — `.xlsx`, `.xls`, `.csv`:
  - **FormatConverter** sayfaları hedef **schema**'lara eşler (LLM'siz): `storage/schemas/*.json` → `equipment_log`, `ipc_sample`, `manpower_production`.
  - **Parquet**'e yaz → **DuckDB** kataloğuna kaydet. Tablo metadata'sı: `columns, dtypes, row_count, target_schema, semantic_tags, header_metadata, description, summary, insight, column_jargon`.
  - Schema eşleşmezse ham tablo çıkarımı (excel_table_extractor) fallback.
- **E-POSTA kolu** — `.eml`, `.msg`:
  - EmailParser ile gövde + başlıklar; gövde Pinecone'a (DOKÜMAN gibi) indekslenir; sender/recipient header'dan notice metadata'sına işlenir; **ek dosyalar (attachments) özyinelemeli** olarak `route_file`'a geri verilir.
- **Notice metadata** → JSON olarak saklanır + **LightGraph** düğüm/kenarlarına (ref-number/reply/topic ilişkileri) + DuckDB `notices` tablosuna senkronlanır.

### İngestion metadata'sının query-time kullanımı (ne işe yarar)
- **Chunk metadata** (page_number/total_pages/doc_id): RAG cevabında **citation/anchor** (`page_N`) üretimi ve viewer'da doğru sayfayı açma.
- **Notice metadata** (LightGraph): TIMELINE/THREAD/correspondence sorguları; ayrıca DOCUMENT handler'ında **metadata ön-filtre** (`light_graph.search_by_topic` → metadata_sources) ve cevaptaki **related_docs**.
- **Tablo catalog metadata** (target_schema, semantic_tags, column_jargon): tablo **seçimi**, **SQL üretim hint'leri** ve sütun adı eşleme.
- **Cluster** atamaları: UI'da doküman gruplama.

### Sorgu anı akışı (query-time)
1. **Chat API** (`POST /api/chat`: message, conversation_id, doc_ids, email_ids, mode) → **Orchestrator**: geçmiş mesajları ekler; **correspondence modunda seçili e-postaların TAM gövdesini** mesaja enjekte eder (doc_ids=email_ids yapar).
2. **Router** (`route_and_execute`). **Erken bypass'lar:**
   - **Greeting** (deterministik exact-match) → sabit karşılama (LLM yok).
   - **mode=correspondence + email_ids** → sınıflandırmayı ATLA, doğrudan **DOCUMENT** dispatch (cevap enjekte edilen e-postalardan).
   - **Karmaşık sorgu** (" then ", "compare", "month-over-month"...) → **HybridExecutor**.
3. **classify_query** — belirsizlikte LLM, aksi halde deterministik (sırasıyla):
   - Tier 0: regex (thread/draft; "which documents related to..." → DOCUMENT).
   - **Belirsizlik kapısı** `_signals_conflict`: veri sinyali + doküman-niyeti ifadesi birlikteyse → **LLM sınıflandırıcı**.
   - schema-semantic (schema skoru), Tier 1: keyword skorlama + schema_boost, Tier 2: embedding benzerliği (anchor metinler), mode default.
   - Tier 3: **LLM sınıflandırıcı** (Gemini Flash, max_tokens=16, cache'li) — son çare.
4. **QueryType'a göre dispatch** (7 tür) → handler/agent.

### Handler'lar / Agent'lar (her birinin LLM çağrı sayısı + kullandığı kaynak)
- **DOCUMENT → Document RAG** (1 LLM çağrısı): jargon genişlet → **filename hint** (isimli-doküman hızlı yolu) → LightGraph metadata ön-filtre → **Pinecone** retrieve (top_k 10/15) → **LlamaIndex sentez (Gemini)** → kaynak yeniden-sıralama (isimli doküman +0.30, PDF +0.05) → citations.
- **DATA → SQL Agent** (`DataAnalyzerSQL`, 1–4 LLM çağrısı) — *çok adımlı agent döngüsü*: tablo seç → **deterministik SQL shortcut** (regex→SQL şablonu, LLM'siz) varsa onu kullan, yoksa **SQL üret (LLM)** → **DuckDB çalıştır** → hata olursa **1 kez retry (LLM)** → sonuç büyükse **özet (LLM)** → SQLArtifact (generated_sql, row_count, preview_rows).
- **TIMELINE → LightGraph** (0–1 LLM): notice metadata üzerinde DuckDB sorguları (sayım, gönderen/alıcı, taraflar arası yazışma, kronoloji); bulunursa RAG ile içerik zenginleştirme.
- **THREAD → ThreadBuilder** (0 LLM): taraflar arası mesaj dizisi.
- **DRAFT → draft_reply** (1 LLM): resmi yanıt taslağı.
- **FILE_LIST → Registry/Catalog** (0 LLM): dosya listeleme/arama.
- **HYBRID → QueryPlanner + PlanExecutor** (3–8+ LLM) — *gerçek çok adımlı agent*: **plan üret (LLM, JSON adımlar, MAX_PLAN_STEPS=5)** → adımları çalıştır (SQL / DOCUMENT / TIMELINE, depends_on DAG) → **COMBINE (LLM sentez)**.
- Tüm sonuçlar **response_builder** ile `ChatResponse`'a map'lenir.

### Schema & Jargon'un kullanıldığı noktalar
- **schema_context**: `analyze_schema_intent` (routing kararında) + `get_schema_prompt_block` (router prompt'u, SQL üretimi, sentez, planlama).
- **jargon_manager**: `expand_query` (retrieval/SQL için — **sınıflandırmada DEĞİL**, yanlış genişletme route'u saptırmasın), `build_column_context` (SQL sütun bağlamı), `normalize_column_name` (ingestion'da sütun→anlam).

### 3 UI Yüzeyi ve gönderdiği istek (frontend → backend)
- **Ana ekran / Welcome (chat modu):** açılışta `GET /api/library/summary` (KPI'lar: dosya/tablo/email sayıları) + mod seçici kartlar (MODE.01 Correspondence, MODE.02 Document Analysis). Mesaj gönderince: `POST /chat {message, conversation_id, mode:"chat"}` (doc_ids/email_ids YOK). Dönüş intent: `answer` (markdown + satır-içi citation) / `doc_list` / `sql_result`.
- **Document Analysis modu:** kullanıcı bir konu girer; frontend onu sarmalar → mesaj: *"Show me all documents related to \"X\", chronologically."*; `POST /chat {message, mode:"document_analysis"}` (doc_ids/email_ids YOK). Dönüşte `related_docs` varsa **DocumentAnalysisTable** (kronolojik, tıklanabilir) render edilir.
- **Correspondence modu:** kullanıcı sidebar'da e-postaları **checkbox** ile seçer (`selectedEmailIds`); hızlı aksiyonlar (Summarize / Draft a reply / Find key actions) seçili e-postaların **özet gövdelerini bir "bundle" olarak mesaja ekler**; `POST /chat {message(+bundle), conversation_id, mode:"correspondence", email_ids, doc_ids=email_ids}`. Orchestrator tam e-posta gövdelerini enjekte eder → router **DOCUMENT bypass**. Dönüş intent: `email_trace` → **EmailTraceResponse** (dikey zaman çizelgesi kartları).
- **Doküman görüntüleyici (sağ panel):** citation/related-doc/tablo satırına tıklayınca `GET /docs/{id}/content` → tip `pdf` (base64 sayfa görseli + metin) / `table` (ExcelPreview) / `text`. Dosya-tipi rozetleri: PDF/XLS/EML/DOC/CSV.

---

## İSTENEN 7 DİYAGRAM (sırasıyla üret)

**Diyagram 1 — Katmanlı Genel Mimari.** `flowchart TB`. Üstten alta 6 subgraph (katman):
(1) İstemci/UI [3 yüzey], (2) API (FastAPI endpoint'leri: /chat, /library, /docs, /upload),
(3) Orchestrator, (4) Router & Sınıflandırma, (5) Handler/Agent katmanı (7 kutu), (6) Veri
Katmanı [Pinecone, DuckDB, Parquet, LightGraph, Registry/Catalog]. Katmanlar arası ana okları
çiz. Renk sınıflarını uygula.

**Diyagram 2 — Doküman Yükleme & İndeksleme Pipeline.** `flowchart LR`. `POST /upload` → kaydet →
arka plan index → `route_file` karar düğümü → **3 kol** (DOKÜMAN / VERİ / E-POSTA) ve her kolun
adımları (OCR? → chunk → embed → Pinecone | schema eşleştir → Parquet → DuckDB | parse +
attachments + notice). Metadata üretim düğümlerini (chunk metadata, notice metadata→LightGraph,
table catalog) ve **hangi deposuna gittiğini** göster. Okların üstünde taşınan metadata türü.

**Diyagram 3 — Sorgu Anı Dallanması (ana akış).** `flowchart TB`. Kullanıcı mesajı → Orchestrator
(geçmiş + correspondence'ta e-posta enjeksiyonu) → **3 erken bypass karar düğümü** (greeting /
correspondence+email_ids / complex) → `classify_query` içinde tier zinciri (regex → **belirsizlik
kapısı→LLM** → schema-semantic → heuristic → embedding → mode default → **LLM classifier**) →
**QueryType karar düğümü** → 7 handler/agent kutusu (her kutuda LLM çağrı sayısını ve veri
kaynağını etikete yaz) → response_builder → intent çıktıları. Deterministik kutular gri, tek-LLM
turuncu, agent'lar (DATA, HYBRID) kırmızı.

**Diyagram 4 — DATA: SQL Agent İç Döngüsü.** `flowchart TB`. tablo seç → `{deterministik shortcut var mı?}`
→ (evet: şablon SQL, LLM'siz) / (hayır: **SQL üret (LLM)**) → **DuckDB çalıştır** → `{hata?}` →
(evet: **retry (LLM)** → tekrar çalıştır) → `{sonuç büyük mü?}` → (evet: **özet (LLM)**) → SQLArtifact.
Döngü/karar yapısını net göster; LLM düğümleri turuncu, DuckDB store mavi, genel kutu agent rengi.

**Diyagram 5 — HYBRID: Çok Adımlı Planlayıcı Agent.** `flowchart TB`. **QueryPlanner (LLM plan, JSON
adımlar)** → PlanExecutor → paralel/sıralı adımlar (SQL adımı→SQL Agent, DOCUMENT adımı→RAG,
TIMELINE adımı→LightGraph; `depends_on` bağımlılıkları) → **COMBINE (LLM sentez)** → cevap.
Adımların alt-agent'lara delege olduğunu okla göster.

**Diyagram 6 — 3 UI Yüzeyi → Backend İstekleri.** `sequenceDiagram`. 3 katılımcı grubu için
(Kullanıcı, Frontend(mod), Backend) üç senaryo: (a) Ana ekran/chat, (b) Document Analysis,
(c) Correspondence. Her senaryoda giden **POST /chat payload'unu** (mode + email_ids/doc_ids +
mesaj şekli) ve dönen **intent + render bileşenini** (answer/doc_list / DocumentAnalysisTable /
email_trace) mesaj olarak göster. Correspondence'ta e-posta bundle enjeksiyonu ve DOCUMENT
bypass'ı belirt.

**Diyagram 7 — Schema/Jargon & Metadata'nın Query-Time Tüketimi.** `flowchart LR`. Solda kaynaklar
(schema_context, jargon_manager, chunk metadata, notice/LightGraph, table catalog); sağda tüketim
noktaları (routing kararı, SQL üretimi, RAG sentezi/citation, planlama, TIMELINE/THREAD, tablo
seçimi). Hangi kaynağın hangi noktada kullanıldığını oklarla bağla; ok etiketinde "ne sağladığı"
(ör. "sütun→anlam", "schema hint", "page anchor", "ilişki grafiği").

## SON
7 diyagramı da üret. Hiçbir bileşeni atlama; yukarıdaki ground truth'taki tüm düğümler en az bir
diyagramda yer almalı. Diyagramların hemen ardından 5–8 satırlık kısa bir **Türkçe okuma kılavuzu**
(renk lejantı + "önce Diyagram 1'e bak, sonra 2→3..." sırası) ekle.
