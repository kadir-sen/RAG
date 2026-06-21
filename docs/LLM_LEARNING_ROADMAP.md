# COAir — LLM-tarafı güçlendirme + öğrenen yapı yol haritası

**İlke (kullanıcı kısıtları):** Deterministik kısayol EKLEME — LLM kullanılmaya devam.
Sistem **kullandıkça öğrensin** (otomatik, feedback'e mahkûm değil). **Token verimli**
olsun (gereksiz/tekrar çağrı yok). Registry/LLM-free işler kapsam dışı.

Temel alınan kod (mevcut durum):
- Routing LLM-first ([src/router.py] `classify_query`→`_classify_llm_rich`), execution
  rota başına **sabit DAG** (agentic döngü yok).
- Öğrenme: [src/flywheel.py] — sadece 👍 feedback + **manuel/zamanlı tetik**.
- Memory: konuşma bağlamı geçici ([backend/services/chat_orchestrator.py]); kalıcı öğrenme yok.
- Token: cache ([src/llm_client.py] `_cache_get` prompt-hash), `MAX_LLM_CALLS_PER_QUERY`, thinking-budget.
- Eval semptomları: Q1 cevaplanabilir soruyu savuşturdu, Q3 named-doc kırık, Q2 muğlak — halüsinasyon YOK (alan-dışı reddi çalışıyor).

Hedef mimari: **LLM-first + agentic (verify→re-plan) + episodic öğrenen memory + semantik cache**.

---

## Faz 0 — Etkileşim izi (öğrenmenin veri tabanı) · küçük, önce

Öğrenme için her sorgunun yapılandırılmış izi gerekli. [src/telemetry.py] (`QueryTrace`)
zaten LLM çağrılarını kaydediyor; bunu **etkileşim kaydına** genişlet.

- **Yeni `src/interaction_log.py`**: sorgu başına 1 kayıt → `query, query_vec, route,
  tools_used, source_files, sql, answer, verify_verdict, feedback, user, ts`.
  Depolama: DuckDB (`storage/interactions.db`) — chunk_store/event_timeline pattern'i.
- [chat_orchestrator.py] `process()` sonunda yaz (best-effort, non-fatal).
- **Token maliyeti: $0** (LLM yok; embedding zaten fastembed/yerel).

**Çıktı:** sistemin kendi geçmişi — Faz 1/5'in yakıtı.

---

## Faz 1 — Episodic öğrenen memory (MERKEZ) · "self-learning few-shot"

Sistem kullandıkça akıllansın: geçmiş **başarılı** etkileşimleri vektörle indeksle, yeni
soruda benzerlerini few-shot olarak prompt'lara enjekte et.

- **Yeni `src/episodic_memory.py`**: interaction_log üzerine vektör arama
  (`query_vec` ile cosine). `recall(query, k, user)` → en benzer K başarılı örnek
  (route + işe yarayan SQL/named-doc + kısa cevap). Başarı sinyali: 👍 VEYA Faz-2 verify=EVET.
- **Enjeksiyon noktaları (mevcut prompt'lara few-shot):**
  - Routing: [router.py] `_classify_llm_rich` zaten "learned routing examples" enjekte ediyor
    (satır ~1089) → kaynağı flywheel-jsonl yerine **episodic recall**'a çevir (otomatik, zengin).
  - SQL: [data_analyzer_sql.py] `_generate_sql` → benzer **başarılı SQL**'leri few-shot ekle.
  - Synthesis: benzer iyi cevapların stilini/atfını örnekle.
- **Katmanlar:** per-user (kişiselleşme) + global (ortak bilgi).
- **Token verimli:** recall yerel/ücretsiz (fastembed); few-shot ılımlı token ekler ama
  **retry/savuşturmayı azaltır** → net tasarruf. Recall sonuçları cache'lenir.

**Düzeltir:** Q1 savuşturma (benzer cevaplanmış örnek görür), zamanla routing/SQL kalitesi.
**Flywheel evrimi:** feedback-only+manuel → **otomatik + retrieval-augmented + per-user**.

---

## Faz 2 — Agentic doğrulama + tek-adım re-plan · sabit-DAG'ı agentic yapar

Cevaptan sonra ucuz bir öz-denetim; eksikse bir kez daha tool çağır.

- **Yeni `src/answer_verifier.py`**: 1 ucuz çağrı (flash-lite, thinking=0):
  *"Bu cevap soruyu tam karşıladı mı? EVET / EKSİK(+hangi kaynak/tool) / KONU-DIŞI"*.
- [router.py] `route_and_execute` sonuna bağla:
  - **EKSİK** → önerilen tool'u **bir kez** çağır + yeniden sentezle (re-plan; bütçe içinde).
  - **KONU-DIŞI** → temiz ret (halüsinasyon savunmasını pekiştirir).
  - **EVET** → episodic memory'e "başarılı" sinyali (Faz 1'i besler).
- **Token verimli — koşullu tetik:** yalnız cevap boş/çok kısa/düşük-confidence VEYA
  verifier şüphede ise çalışır; normal güçlü cevaplarda atlanır. `MAX_LLM_CALLS` içinde.

**Düzeltir:** boş-retrieval, eksik cevap; Q1/Q3'te ikinci şans.

---

## Faz 3 — Brittle heuristik → LLM/retrieval (deterministik DEĞİL)

Kırılgan kural-tabanlı yerleri LLM/retrieval ile değiştir (registry'e bağlı değil).

- **Named-doc çözümleme:** [router.py] `_resolve_filename_hints` (rapidfuzz/substring) →
  "WED00000143" / "Audit Scotland mektubu" ifadesini **lexical+vektör korpus araması** +
  belirsizse LLM disambiguation ile çöz. Registry gerektirmez → **Q3 düzelir**.
- **Tablo seçimi / multi-step tespiti:** keyword/regex yerine **cache'li LLM** seçici.
- Hepsi LLM/retrieval; yeni deterministik kural yok.

---

## Faz 4 — Token verimliliği katmanı

- **Semantik cache:** birebir prompt-hash yerine **soru-embedding benzerliği** ile cevabı
  yeniden kullan ([llm_client.py] cache'in üstüne) → parafraze sorular tek çağrıyla.
  Embedding ücretsiz (fastembed).
- **Model kademesi:** routing/verify → ucuz (flash-lite); SQL/synthesis → flash + thinking.
  (config'te fiyat tablosu hazır; çağrı başına model seçimi.)
- **Follow-up kısa-devre:** aynı thread'de niyet değişmediyse yeniden routing yapma
  (konuşma bağlamından LLM "intent_changed?" tek bit — veya cache).
- **Bütçe-farkında gating:** Faz-2 verify/re-plan sadece değerse tetiklenir.

---

## Faz 5 — Sürekli öğrenme döngüsü (loop'u kapat)

- **Otomatik flywheel:** her etkileşim + feedback sonrası episodic memory + auto-jargon
  (ingest'te madenlenen `new_terms`) + routing örnekleri **manuel tetik olmadan** güncellenir.
- **Konsolidasyon:** episodic memory büyüyünce periyodik cluster + damıtma — kararlı
  desenleri system-prompt/jargon'a yedir, ham logu buda (sınırsız büyümeyi önle).
- **Per-user tercih:** zamanla kullanıcının rota/jargon/SQL tercihleri öğrenilir.

---

## Sıra ve gerekçe
0 (iz) → 1 (episodic memory = merkez) → 2 (agentic verify) → 3 (LLM resolution) →
4 (token verimliliği) → 5 (sürekli döngü). Her faz **bağımsız değerli** ve token-farkında.
Faz 1 diğerlerinin temeli (öğrenme substratı).

## Dokunulacak / yeni dosyalar
- Yeni: `src/interaction_log.py`, `src/episodic_memory.py`, `src/answer_verifier.py`.
- Değişen: [src/router.py] (recall enjeksiyonu, verify/re-plan bağlama, named-doc resolver),
  [src/data_analyzer_sql.py] (SQL few-shot), [src/llm_client.py] (semantik cache + model kademesi),
  [src/flywheel.py] (otomatik + episodic'e devir), [backend/services/chat_orchestrator.py] (iz yazımı).

## Doğrulama (ölçülebilir)
- [scripts/eval_questions.py]'i her fazdan önce/sonra çalıştır:
  - Q1 artık cevap veriyor mu (savuşturma yok)? Q3 named-doc çözülüyor mu?
  - **Halüsinasyon regresyonu yok** (Q5 alan-dışı reddi korunmalı, Q6 sayı uydurmamalı).
- Token/sorgu (telemetry) düşüyor mu (semantik cache + gating) — ortalama LLM çağrısı/sorgu.
- Öğrenme: aynı soru tekrarında recall few-shot devrede mi; benzer-soru kalitesi artıyor mu.

## Kısıt uyumu
LLM-first korunur (yeni deterministik kural yok; brittle olanlar LLM/retrieval'a taşınır) ·
öğrenen yapı = episodic memory + otomatik flywheel · token verimli = semantik cache +
koşullu agentic tetik + model kademesi + ücretsiz yerel embedding ile recall.
