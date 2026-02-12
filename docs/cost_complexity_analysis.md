# Maliyet ve Karmasiklik Analizi Raporu
## Hybrid RAG Chatbot - Construction Domain

---

## 1. MIMARI KARMASIKLIK PROBLEMLERI

### 1.1 LLM API Cagri Zincirleri (Call Chain Explosion)

Sistemde **8 benzersiz LLM cagri noktasi** tespit edildi:

| Dosya | Satir | Fonksiyon | Kosullu mu? | Prompt Boyutu |
|-------|-------|-----------|-------------|---------------|
| router.py | 218 | classify_query() | EVET (heuristic fallback) | 500-800 char |
| router.py | 280 | _handle_hybrid_query() | HAYIR (hybrid path) | 1000-2000 char |
| data_analyzer_sql.py | 501 | _generate_sql() | HAYIR (data path) | 1500-3000 char |
| data_analyzer_sql.py | 524 | _generate_summary() | HAYIR (data path) | 800-1500 char |
| query_planner.py | 177 | plan() | EVET (sadece complex) | 1500-3000 char |
| query_planner.py | 506 | _execute_combine_step() | HAYIR (combine step) | 2000-4000 char |
| light_graph.py | 864 | smart_timeline_answer() | HAYIR (timeline path) | 2000-4000 char |
| notice_extractor.py | 725 | _refine_with_llm() | EVET (opt-in) | 1000-1500 char |

**Sorgu basi LLM cagri sayisi:**

```
Basit DATA sorgusu:     2 LLM cagri  (SQL uretim + ozet)
Basit DOCUMENT sorgusu: 0 LLM cagri  (RAG pipeline yapar, ayri LLM yok)
Basit TIMELINE sorgusu: 1 LLM cagri  (smart_timeline_answer)
HYBRID sorgu:           4 LLM cagri  (siniflandirma + doc + data + sentez)
COMPLEX 2-adim:         4-6 LLM cagri (plan + step SQL'ler + combine)
COMPLEX 3-adim:         6-8 LLM cagri (plan + step SQL'ler + combine)
```

**PROBLEM:** Karmasik bir sorgu icin **8 seri LLM cagrisi** yapilabilir. Her biri 1-3 saniye surerse, tek bir sorgu **8-24 saniye** surebilir.

### 1.2 Singleton Bagimliliklari ve Circular Import Riski

```
router.py
  -> document_rag (eager)
  -> data_analyzer_sql (eager)
  -> hybrid_executor (lazy)
     -> query_planner (lazy)
        -> data_analyzer_sql (lazy - ayni singleton)
        -> document_rag (lazy - ayni singleton)
        -> light_graph (lazy)
     -> jargon_manager (lazy)
```

**RISKLER:**
- Tek bir singleton bozulursa (ornegin DuckDB baglantisi koparsa), tum zincir etkiler
- Lazy loading siklus testi yapilmamis - runtime'da circular import riski
- Singleton state paylasimi: `data_analyzer_sql` hem dogrudan router'dan hem planner'dan kullaniliyor

### 1.3 Hata Yayilimi (Error Propagation)

```
Router -> HybridExecutor -> Planner -> Executor
                                         |
                              Step 0: SQL (basarili)
                              Step 1: SQL (HATA!)
                              Step 2: Combine (hata ile devam eder)
```

**PROBLEM:** `PlanExecutor.execute()` step hatalarini yakaliyor ama zinciri DURDURMAK yerine `"Error: ..."` string'i ile devam ediyor (query_planner.py:389-393). Combine step'i hatali step sonuclarini sentezlemeye calisir.

### 1.4 Prompt Injection Riski

Kullanici sorgulari dogrudan SQL ve plan prompt'larina enjekte ediliyor:
- `data_analyzer_sql.py:497`: `question=expanded_question` direkt prompt'a
- `query_planner.py:171`: `query=expanded` direkt PLAN_PROMPT'a
- `light_graph.py:853`: `query` direkt LLM prompt'una

SQL validation var (SELECT only) ama LLM prompt manipulation riski devam ediyor.

---

## 2. MALIYET ANALIZI

### 2.1 Birim Maliyetler (Gemini Flash)

| Islem | Token Maliyeti | Tahmini Cagri Maliyeti |
|-------|---------------|------------------------|
| Gemini Flash Input | $0.075 / 1M token | - |
| Gemini Flash Output | $0.30 / 1M token | - |
| text-embedding-004 | ~$0.00002 / embedding | - |
| Pinecone (Free Tier) | $0 | 100K vektore kadar |
| Tesseract OCR | $0 (lokal) | CPU zamani ~2-10s/sayfa |
| DuckDB | $0 (lokal, in-memory) | - |

### 2.2 Dokuman Basina Maliyet (10 sayfalik PDF)

| Bilesan | API Cagri | Tahmini Maliyet | Not |
|---------|-----------|-----------------|-----|
| OCR (Tesseract) | 0 | ~$0 | Lokal islem |
| Embedding (indeksleme) | 30-40 | $0.0006-0.0008 | ~3-4 chunk/sayfa |
| Pinecone storage | - | $0 (free tier) | - |
| Notice cikarimi (regex) | 0 | $0 | Tamamen lokal |
| Notice cikarimi (LLM) | 1 | $0.0001-0.0005 | Opsiyonel |
| **Toplam/dokuman** | **31-41** | **~$0.001** | LLM haric |

### 2.3 Sorgu Basina Maliyet

| Sorgu Tipi | LLM Cagri | Embedding | Tahmini Maliyet | Sure |
|------------|-----------|-----------|-----------------|------|
| Basit DATA | 2 | 1 | $0.0003 | 3-5s |
| Basit DOCUMENT | 0 | 1 | $0.00002 | 2-3s |
| TIMELINE | 1 | 0 | $0.0002 | 2-4s |
| HYBRID | 4 | 1 | $0.0008 | 6-10s |
| COMPLEX 3-adim | 6-8 | 1 | $0.001-0.002 | 10-20s |

### 2.4 Aylik Maliyet Tahmini

| Senaryo | Dokuman | Sorgu/gun | Aylik Maliyet |
|---------|---------|-----------|---------------|
| **Dusuk kullanim** | 100 dok | 10 sorgu | ~$0.25 |
| **Orta kullanim** | 500 dok | 50 sorgu | ~$1.50 |
| **Yuksek kullanim** | 2000 dok | 200 sorgu | ~$8.00 |
| **Enterprise** | 10000 dok | 1000 sorgu | ~$45.00 |

> **Not:** Gemini Flash zaten en ucuz seceneklerden. Ana maliyet suresici LLM cagrilari degil, karmasik sorgulardaki seri cagri SAYISI.

---

## 3. NOTICE EXTRACTION: REGEX vs LLM ANALIZI

### 3.1 Regex ile Cikarilan Alanlar (Mevcut Durum)

| Alan | Pattern Sayisi | Tahmini Dogruluk | Confidence |
|------|---------------|------------------|------------|
| Tarih | 6 regex pattern | %90 (standart formatlar) | 0.9 |
| Gonderen | 3 regex pattern | %60-70 | 0.85 |
| Alici | 4 regex pattern | %60-70 | 0.85 |
| Konu | 3 regex pattern | %80 | 0.85 |
| Referans No | 6 regex pattern | %80 (false positive var) | 0.8 |
| Aksiyonlar | 12 keyword grubu | %70 | 0.7 |
| Tarih siniri | 3 regex pattern | %60 | 0.75 |
| CC listesi | 1 regex pattern | %85 | - |
| Proje adi | 3 regex pattern | %65 | - |
| Sozlesme ref | 2 regex pattern | %75 | - |
| Yon (direction) | Keyword skorlama | %80 | - |
| Dokuman tipi | Keyword skorlama | %75 | - |

### 3.2 Regex Basarisiz Oldugu Durumlar

| Basarisizlik Tipi | Ornek | Neden |
|-------------------|-------|-------|
| **Etiket olmayan gonderen** | "John Smith\nProject Lead" | "From:" etiketi yok |
| **Cok satirli degerler** | "From: John Smith,\nProject Manager" | Pattern \n'de durur |
| **OCR hatalari** | "Dae: 15-01-2024" (typo) | Exact match basarisiz |
| **Baglam duyarsizligi** | "Do NOT submit" -> action='submit' | Negasyon anlasilmiyor |
| **Goreceli tarihler** | "within 30 days of receipt" | Baz tarih bilinmiyor |
| **Karisik dil** | %50 Ingilizce, %50 Turkce | Dil tespiti karisir |
| **Standart disi format** | "Sender is John Smith" | "From:" kalibinda degil |

### 3.3 LLM Eklentisinin Katkisi (use_llm=True)

**Sadece 4 alan icin rafine:**
- Tarih: ISO format dogrulama
- Gonderen: Isim normalizasyonu
- Alici: Isim normalizasyonu
- Konu: Metin normalizasyonu

**LLM EKLEMEZ:**
- Aksiyon tespiti (regex olarak kaliyor)
- Tarih siniri hesaplama
- Referans numarasi dogrulama
- Dokuman tipi tespiti

### 3.4 Tavsiye: Katmanli Yaklasim

```
Katman 1: Regex (her zaman calisir)           -> Maliyet: $0, Sure: <0.5s
Katman 2: Confidence check                    -> Dusuk confidence alanlari isaretle
Katman 3: LLM refinement (sadece dusuk conf)  -> Maliyet: $0.0002, Sure: 1-2s
```

**Mevcut durum:** LLM ya hic kullanilmiyor ya da HER alan icin cagrilyor.
**Oneri:** Sadece confidence < 0.8 olan alanlar icin LLM cagrisi yapmak maliyeti %60-70 azaltir.

---

## 4. A/B TEST YAPISI ONERISI

### 4.1 Test Edilecek Degiskenler

#### Test A: Notice Extraction Stratejisi
```
Variant A1: Regex-only (mevcut default)
Variant A2: Regex + LLM (tum alanlar)
Variant A3: Regex + Selective LLM (dusuk confidence)
Variant A4: Regex + JargonManager zenginlestirme

Metrik: F1-score (precision + recall) on ground truth notices
```

#### Test B: Query Routing Stratejisi
```
Variant B1: Heuristic-only siniflandirma (LLM cagrisiz)
Variant B2: Heuristic + LLM fallback (mevcut)
Variant B3: Her zaman LLM siniflandirma
Variant B4: Embedding similarity siniflandirma

Metrik: Routing accuracy, latency, cost per query
```

#### Test C: SQL Uretim Kalitesi
```
Variant C1: Tek adim SQL (mevcut basit path)
Variant C2: Cok adimli SQL zinciri (planner)
Variant C3: Self-correction (SQL hata -> yeniden uret)
Variant C4: Few-shot SQL (ornek sorgular ile)

Metrik: SQL dogruluk orani, execution success rate
```

#### Test D: Embedding & Chunking Stratejisi
```
Variant D1: Chunk=1024, Overlap=200 (mevcut)
Variant D2: Chunk=512, Overlap=100 (daha granular)
Variant D3: Chunk=2048, Overlap=400 (daha az parca)
Variant D4: Semantic chunking (paragraf bazli)

Metrik: Retrieval relevance (MRR@5), embedding maliyeti
```

#### Test E: Timeline Answer Stratejisi
```
Variant E1: Pattern matching (eski yontem)
Variant E2: LLM sentez (smart_timeline_answer)
Variant E3: Hybrid (pattern match + LLM ozet)

Metrik: Answer quality (LLM-as-judge), latency, cost
```

### 4.2 A/B Test Framework Tasarimi

```python
# Onerilen yapi: src/ab_testing.py

@dataclass
class ABTestConfig:
    test_name: str
    variant: str
    enabled: bool = True

@dataclass
class ABTestResult:
    test_name: str
    variant: str
    query: str
    latency_ms: float
    llm_calls: int
    cost_estimate: float
    quality_score: Optional[float]  # LLM-as-judge veya human rating
    success: bool

class ABTestManager:
    """
    Sorgu bazinda A/B test yonetimi.
    Her sorgu icin aktif variant'i secer,
    sonuclari loglar, karsilastirma raporu olusturur.
    """

    def select_variant(self, test_name: str) -> str:
        """Rastgele veya round-robin variant sec."""

    def record_result(self, result: ABTestResult):
        """Sonucu JSON/Parquet'e kaydet."""

    def generate_report(self, test_name: str) -> Dict:
        """Variant bazinda karsilastirma raporu."""
```

### 4.3 Ground Truth Olusturma

Sample Questions.xlsx'den:
- **Kategori A:** 15 Document RAG sorusu
- **Kategori B:** 15 Table Agent sorusu
- **Kategori C:** 10 Hybrid sorusu
- **Kategori D:** 10 Edge/Failure sorusu

Her soru icin:
1. Beklenen cevap (human annotated)
2. Beklenen query_type (DOCUMENT/DATA/TIMELINE/HYBRID)
3. Beklenen SQL (varsa)
4. Beklenen kaynak dokumanlar

---

## 5. OPTIMIZASYON ONERILERI (Oncelik Sirasina Gore)

### 5.1 YUKSEK ETKI - Hemen Uygulanabilir

#### O1: LLM Cagri Cacheleme
```
Mevcut:  Her sorgu -> yeni LLM cagrisi
Oneri:   Query hash -> Redis/dosya cache (TTL: 1 saat)
Tasarruf: Tekrar eden sorgularda %100
Karmasiklik: Dusuk (dekorator ile)
```

#### O2: Siniflandirmada LLM'i Atla
```
Mevcut:  Heuristic basarisiz -> LLM cagrisi (router.py:218)
Oneri:   Heuristic threshold dusur (3->2 match)
         + embedding similarity ile siniflandirma (LLM'siz)
Tasarruf: Sorgu basina 1 LLM cagrisi
Karmasiklik: Orta
```

#### O3: SQL Summary'i Kaldir veya Ertelendir
```
Mevcut:  Her SQL sorgusu -> SQL uret + calistir + OZET LLM cagrisi
Oneri:   Ozet LLM'i sadece kullanici isterse (lazy summary)
         veya SQL sonucu < 5 satir ise format ile goster
Tasarruf: DATA sorgularinda 1 LLM cagrisi (%50 azalma)
Karmasiklik: Dusuk
```

### 5.2 ORTA ETKI - Sprint Planlama

#### O4: Batch Embedding
```
Mevcut:  Her sayfa ayri embedding cagrisi
Oneri:   Batch API kullan (Gemini batch embedding destekliyor)
Tasarruf: Indeksleme suresinde %40-60 azalma
Karmasiklik: Orta
```

#### O5: Selective LLM Notice Extraction
```
Mevcut:  use_llm=False (regex only) veya True (hepsi LLM)
Oneri:   Confidence < 0.8 olan alanlar icin LLM cagir
Tasarruf: Notice basina LLM cagrisi %60-70 azalma
Karmasiklik: Orta (confidence threshold tuning gerekir)
```

#### O6: Planner Bypass Heuristics'i Gelistir
```
Mevcut:  _is_obviously_simple() basit keyword kontrol
Oneri:   Daha kapsamli heuristic + ornek matching
         "group by" iceren sorguyu tek SQL ile cozebilir
Tasarruf: Karmasik algilan basit sorgularda 2-4 LLM cagrisi
Karmasiklik: Orta
```

### 5.3 DUSUK ETKI - Backlog

#### O7: OCR Cift Tarama Eliminasyonu
```
Mevcut:  image_to_data() + image_to_string() = 2 tarama/sayfa
Oneri:   Tek image_to_data(output_type=DICT) cagrisi
Tasarruf: OCR suresinde %30-40 azalma (lokal CPU)
Karmasiklik: Dusuk
```

#### O8: Image Coverage Hesaplama Tekrari
```
Mevcut:  ocr_detector.py VE ocr_pipeline.py ayri hesaplama
Oneri:   Tek hesaplama, sonuc paylasimi
Tasarruf: PDF analiz suresinde %15-20 azalma
Karmasiklik: Dusuk
```

#### O9: Query Result Cache
```
Mevcut:  Her sorgu yeni embedding + LLM
Oneri:   Son N sorgu sonucunu cache'le
Tasarruf: Tekrar eden sorgularda %100
Karmasiklik: Dusuk-Orta
```

---

## 6. RISK MATRISI

| Risk | Olasilik | Etki | Azaltma |
|------|---------|------|---------|
| LLM API kesintisi | Orta | Yuksek | Fallback mekanizmalari mevcut ama test edilmemis |
| Pinecone free tier limiti | Dusuk | Yuksek | 100K vektor limiti; buyuk projelerde asabilir |
| DuckDB memory overflow | Dusuk | Orta | Cok buyuk CSV'lerde in-memory DB dolabilir |
| SQL injection via LLM | Dusuk | Yuksek | validate_sql() SELECT-only kontrol var |
| Prompt injection | Orta | Orta | Kullanici inputu dogrudan prompt'a gidiyor |
| Circular import | Dusuk | Yuksek | Lazy loading ile azaltilmis ama test eksik |
| OCR kalite dususu | Orta | Orta | Dusuk DPI veya karisik formatlarda basarisiz |
| Jargon dictionary eksikligi | Orta | Dusuk | 71 terim yeterli mi? Domain-specific terimleri eksik olabilir |

---

## 7. SONUC VE ONCELIK SIRASI

### Hemen Yapin (1-2 gun):
1. **O3: SQL Summary lazy yapma** -> DATA sorgularinda %50 LLM tasarrufu
2. **O1: Basit query cache** -> Tekrar eden sorgularda sifir maliyet

### Sprint 1 (1 hafta):
3. **O2: Embedding-based siniflandirma** -> Router'da LLM cagrisi eliminasyonu
4. **O5: Selective LLM notice** -> Notice extraction maliyeti %70 azalma
5. **A/B test framework** -> Kararlari veri ile destekleme

### Sprint 2 (2 hafta):
6. **O6: Planner heuristic iyilestirme** -> Karmasik sorgu false positive azaltma
7. **O4: Batch embedding** -> Indeksleme suresini %50 azaltma
8. **Ground truth dataset** -> 50 soru + beklenen cevap

### Backlog:
9. O7, O8, O9 -> Dusuk oncelikli performans iyilestirmeleri

---

*Rapor tarihi: 2026-02-06*
*Analiz kapsamı: src/ altindaki 12 modul, 15 test*
*Model: Gemini Flash (gemini-flash-latest)*
