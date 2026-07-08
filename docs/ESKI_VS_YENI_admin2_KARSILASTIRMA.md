# Eski (deploy) vs Yeni (agent-açık) — admin2 gerçek sorularıyla beceri karşılaştırması

**Tarih:** 2026-06-29 · **Kullanıcı:** admin2 (edinburgh korpusu) · **Soru kaynağı:** admin2'nin
deploy sunucusundaki (18.185.38.217) gerçek sohbet geçmişi (25 sohbet, 56 soru → 14 küratör).

- **ESKİ** = deploy `da53acc`; cevaplar admin2'nin kayıtlı geçmişinden.
- **YENİ** = local feature branch `8e204b8`, **ReAct agent AÇIK**, retrieval = **lokal Qdrant `coair`
  collection (156.200 vektör = tam edinburgh, deploy ile aynı kaynak)**, embedding = fastembed bge-768.

---

## ⚠️ Önce dürüstlük: bu karşılaştırma kısmen confound'lu

Yeni sürümü local'de çalıştırdım. Retrieval'i deploy ile eşitlemek için lokal Qdrant'ı `coair`
collection'ına bağladım (adil dense retrieval). Ancak iki şey local'de **eksik** ve bu, 14 sorudan
7'sini "beceri" değil "kurulum" yüzünden bozdu:

1. **SQL veri tabloları local'de admin2 için register değil** → DATA'ya yönlenen 5 soru
   ("No data tables available... Reindex Data Tables") ile başarısız. Deploy'da bu tablolar (ADS PDF'lerinden
   çıkarılmış parquet'ler) vardı.
2. **Timeline grafiği (light_graph) local'de demo verisi (61 node)** → TIMELINE'a yönlenen 2 soru
   ("no chronological events"). Edinburgh timeline grafiği local'de yüklü değil.

Dolayısıyla **adil kıyas yalnızca saf document-RAG dilimi** (aynı `coair` vektörleri üzerinde).

---

## Beceri-bazlı bulgular

### A) Halüsinasyon tuzakları (yanlış-öncül) — KİLİT BECERİ
Her iki sürüm de **güçlü**: yanlış öncülü reddedip uydurmuyor, groundlu çürütüyor.
- "two years ahead", "Bilfinger Berger fine", "2003 Trams Act", "fatality stats": **eski ≈ yeni**, ikisi de doğru reddetti.
- **"£545m final outturn, correct?"** → document'a yönlendiğinde **YENİ belirgin daha iyi**: yanlış öncülü
  gerçek citation'larla çürüttü — *"£545m, Phase 1a'nın ANTICIPATED maliyetiydi (ADS00058.pdf p.32, ADS00057.pdf p.29)"*.
  Eski sadece *"not definitively confirmed... null values"* demişti. ✅
- Not: aynı soru başka bir koşuda DATA'ya yönlendi (routing non-deterministik) → local'de tabloya gidip başarısız.

### B) Factual grounding (document-RAG)
- **"three interventions..."**: eski ≈ yeni, ikisi de groundlu/iyi.
- **"what is ADS00004"**: **HER İKİSİ DE ıskaladı** ("not present") — ADS00004 korpusta olmasına rağmen.
  Bu, paylaşılan bir **named-doc retrieval açığı** (yeni de düzeltmiyor).
- **"Who signed the Infraco contract on behalf of TIE?"**: YENİ "behalf of TIE incomplete" dedi
  → soru kırpılmış. **Pre-existing bug** ([router.py:1510](src/router.py#L1510) `_extract_document_search_topic`'teki
  greedy `on` regex'i "X **on** behalf of Y" → "behalf of Y" yapıyor). **Benim commitlerimde değil**; eski kodda da var.
  Eski'nin doğru cevaplaması LLM toleransı/nondeterminizm. → **Düzeltilmeli** (paylaşılan bug).

### C) DATA / TIMELINE — local'de adil kıyaslanamadı (yukarıdaki confound)
Eski bu soruları (Newcraighall km, equipment-logs satır sayısı, original budget) deploy'daki tablolardan
cevaplamıştı. Önemli: eski **"equipment maintenance logs → 2.156 satır (ipc_sample)"** dedi — ama bu bir
**demo tablosu**; edinburgh kullanıcısı için **korpus sızıntısı / yanlış**. Yenide tablo olmadığı için bu
sızıntı oluşmadı, ama bu "adil bir kazanım" sayılmaz.

### D) ReAct AGENT — yeni sürümün GERÇEK yeni yeteneği (eski'de yok)
Küratör tekil sorular agent'ı tetiklemez (tasarımca — agent çok-adımlı için). **Compound 2 soruda** agent devreye girdi:
- **"…cost overrun nedenleri, ve sonra anlaşmazlıktaki ana taraflar"** (88s, **17 citation**): agent **5 iterasyonlu
  adaptif döngü** koştu, her adımda muhakeme edip eksiği belirledi (*"witness statements geldi ama resmi inquiry
  sonuçları değil — gerçek raporu aramalıyım"*), 25+ gerçek edinburgh dokümanı okudu, groundlu (ve dürüst:
  *"final conclusions yok, ama witness statements şu perspektifleri sunuyor"*) cevap üretti.
- **"Audit Scotland maliyetler + governance sorumluluğu"** (46s, **30 citation**): iteratif daraltma, Feb 2011
  Audit Scotland raporunu buldu, groundlu cevap.

Bu, eski'nin **sabit tek-geçişli** yaklaşımının yapamadığı **kendini-düzelten iteratif kanıt toplama**
(17-30 citation vs eski ~8-14). Tüm adımlar canlı aktivite feed'inde akıyor.

---

## Karar (dürüst)

**"Yeni versiyon eskiden topyekûn daha mı becerikli?" → Net "evet" diyemem; nüanslı:**

1. **Tekil document-RAG Q&A'da** yeni, eski'nin güçlü grounding/anti-halüsinasyonuna **eşit** (eski iyi bir
   baseline), bir vakada (£545m) **daha iyi**. Çekirdek aynı (router/retrieval/synthesis), bu yüzden topyekûn
   sıçrama beklenmezdi — beklendiği gibi.
2. **Gerçek yeni yetenek = ReAct agent**: çok-adımlı/compound sorularda adaptif, kendini-düzelten,
   geniş-kanıtlı (17-30 citation) cevaplar. Eski'de bu yok. **Burada yeni açıkça daha yetenekli.**
3. **Görünen "yeni regresyonları" beceri kaybı DEĞİL:** DATA/TIMELINE local-kurulum açığı; Infraco
   paylaşılan pre-existing bug; ADS00004 paylaşılan named-doc açığı.
4. Ayrıca yeni: provider sağlamlığı (Gemini çalışıyor), canlı aktivite feed'i, retrieve-only/cache/tiering ile
   maliyet+latency — bunlar cevap *içeriğini* değil deneyimi/maliyeti iyileştirir.

**Kesin head-to-head için** yeni kodu **aynı tam-donanımlı veriyle** (register SQL tabloları + edinburgh timeline
grafiği) çalıştırmak gerekir — ideali yeni kodu staging'e deploy edip deploy-eski ile aynı veride kıyaslamak.

## Tespit edilen düzeltilebilir açıklar (çoğu paylaşılan/pre-existing)
- `_extract_document_search_topic` greedy `on` deseni → "X on behalf of Y" sorularını kırpıyor. (router.py:1510)
- ADS00004 gibi named-doc sorularında retrieval ıskası (her iki sürüm).
- Edinburgh **dense** lane local'de 0 dönüyor (`dense=0 lexical=30`); lexical taşıyor ama dense scope/payload
  metadata'sı incelenmeli.
- Maliyet/factual soruların DATA↔DOCUMENT routing'i non-deterministik.
