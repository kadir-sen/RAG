# Jargon Sistemi İnceleme Raporu

**İnceleme tarihi:** 31 Temmuz 2026  
**Kapsam:** Repodaki inşaat jargonu, kısaltmalar, kavram grupları, sorgu
genişletme mekanizması, öğrenme/yönetim akışları ve mevcut sınırlamalar.

## 1. Yönetici özeti

Jargon bölümü, kullanıcının yazdığı kısa veya projeye özgü ifadeleri arama ve
SQL üretimi için daha anlamlı terimlerle zenginleştiren merkezi bir sözlük
sistemidir. Örneğin `EOT` ifadesi belge aramasında `Extension of Time` olarak
anlamsallaştırılır; SQL üretiminde ise `EOT (Extension of Time)` biçiminde modele
verilir. Böylece yalnızca kısaltmayı veya yalnızca açık yazımı içeren belgelerin
ve tablo sütunlarının bulunma ihtimali yükselir.

Mevcut kodda:

- **98 yerleşik kısaltma** vardır:
  - 10 genel iş/ticaret terimi,
  - 64 genel inşaat, sözleşme, kalite, proje kontrolü ve mühendislik terimi,
  - 24 TABH/Dubai projesine özgü veya o korpus için eklenmiş terim.
- **9 alan kavram grubu** vardır: `delay`, `claim`, `approval`, `variation`,
  `payment`, `termination`, `progress`, `quality`, `fire_alarm`.
- Yerleşik terimler `config/jargon_terms.json` içinde `terim -> açıklama`
  biçiminde tutulur.
- Özel terimler `data/jargon/jargon_custom.json` içinde kalıcı tutulur.
- İnceleme anında özel terim dosyası boş olduğu için **özel terim sayısı 0**'dır.
- Excel sözlükleri yüklenebilir; belge zenginleştirmesi ve kullanıcı
  düzeltmeleri üzerinden yeni terimler otomatik öğrenilebilir.
- Jargon, belge RAG aramasında, tablo/SQL sorgularında, şema bağlamında, sorgu
  planlamasında, notice çıkarımında ve eski Streamlit arama ekranında kullanılır.

Silinen eski mimari raporda sayı yaklaşık 130 ve özel sözlük yolu
`storage/jargon/...` olarak anlatılmıştı. Güncel kaynak kodun doğruladığı doğru
değer **98**, doğru kalıcılık yolu ise
`data/jargon/jargon_custom.json` dosyasıdır.

## 2. Jargon sisteminin amacı

Sistem üç ayrı ihtiyacı karşılar:

1. **Kısaltmayı anlamlandırma**
   - `SOW` → `Scope of Work`
   - `BOQ` → `Bill of Quantities`
   - `EOT` → `Extension of Time`
2. **Aynı kavramın farklı yazımlarını birlikte arama**
   - `delay` sorgusunu `NOD`, `notice of delay`, `EOT`, `late completion`,
     `schedule delay` gibi ilişkili terimlerle destekleme.
3. **Tablo şemasını LLM'e açıklama**
   - `EOT_Status` gibi bir sütunun içindeki kısaltmayı açma,
   - SQL üreten modele gerçek sütun adını ve anlamını birlikte verme.

Bu işlem özellikle recall'ı, yani ilgili içeriği kaçırmama oranını güçlendirir.
Ancak `AC`, `CM`, `CO`, `RE`, `DM` gibi bağlama göre başka anlamlara gelebilecek
kısa terimlerde yanlış genişletme precision'ı düşürebilir. Bu nedenle router'ın
ana sınıflandırması özgün sorgu üzerinde yapılır; genişletilmiş sorgu esas olarak
retrieval, SQL ve sınıflandırma güvenlik ağı katmanlarında kullanılır.

## 3. Veri modeli ve kaynaklar

### 3.1 Yerleşik sözlük

Ana sözlük `config/jargon_terms.json` dosyasında `terim -> açıklama` çiftleri
olarak tutulur. `src/jargon_manager.py` bu dosyayı başlatma sırasında okuyup
doğrulayarak `BUILTIN_JARGON` sözlüğüne yükler. Yerleşik terimler yönetim API'si
üzerinden değiştirilemez veya silinemez.

### 3.2 Kavram grupları

`DOMAIN_CONCEPT_GROUPS`, tek bir sözcüğü aynı iş alanındaki eş anlamlı ve ilişkili
terimlere bağlar. Bu katman kısaltma açılımından farklıdır. Örneğin `delay`,
yalnızca bir açılım değil, gecikmeye ilişkin bir arama terimleri ailesidir.

### 3.3 Özel terimler

Çalışma zamanında eklenen terimler:

```text
data/jargon/jargon_custom.json
```

dosyasında aşağıdaki yapıda saklanır:

```json
{
  "terms": [
    {
      "abbreviation": "ABC",
      "full_form": "Example Full Form",
      "concept_group": "quality"
    }
  ]
}
```

Mevcut dosya `{"terms": []}` durumundadır.

### 3.4 Excel jargon sözlükleri

İki sütunlu Excel dosyaları yüklenebilir:

| Sütun 1 | Sütun 2 |
|---|---|
| Abbreviation / Abbr / Term / Acronym | Meaning / Definition / Full / Description |

İlk beş satır içinde başlık tespiti yapılır. Dosya adına göre otomatik ingest
algılaması `jargon`, `abbreviation`, `kisaltma` veya `glossary` sözcüklerini
kabul eder. Singleton başlangıcındaki otomatik dosya taraması ise yalnızca
dosya adında `jargon` veya `abbreviation` bulunan `.xlsx` dosyalarını arar.

## 4. Yerleşik jargon envanteri

### 4.1 Genel iş ve ticaret terimleri — 10 adet

| Kısaltma | Repodaki anlamı |
|---|---|
| SOW | Scope of Work |
| SLA | Service Level Agreement |
| NDA | Non-Disclosure Agreement |
| KPI | Key Performance Indicator |
| MTD | Month to Date |
| QTD | Quarter to Date |
| YTD | Year to Date |
| PO | Purchase Order |
| PR | Purchase Requisition |
| T&C | Terms and Conditions |

### 4.2 İnşaat, sözleşme ve proje kontrolü terimleri — 64 adet

| Kısaltma | Repodaki anlamı |
|---|---|
| BOQ | Bill of Quantities |
| BOM | Bill of Materials |
| RFI | Request for Information |
| RFP | Request for Proposal |
| RFQ | Request for Quotation |
| EOT | Extension of Time |
| LD | Liquidated Damages |
| LAD | Liquidated and Ascertained Damages |
| VO | Variation Order |
| CO | Change Order |
| WBS | Work Breakdown Structure |
| OBS | Organization Breakdown Structure |
| ITP | Inspection and Test Plan |
| QA | Quality Assurance |
| QC | Quality Control |
| HSE | Health Safety and Environment |
| EHS | Environment Health and Safety |
| QHSE | Quality Health Safety and Environment |
| MEP | Mechanical Electrical and Plumbing |
| HVAC | Heating Ventilation and Air Conditioning |
| P&ID | Piping and Instrumentation Diagram |
| GA | General Arrangement |
| DWG | Drawing |
| SPEC | Specification |
| TBD | To Be Determined |
| TBA | To Be Announced |
| TBC | To Be Confirmed |
| N/A | Not Applicable |
| WIP | Work in Progress |
| PMO | Project Management Office |
| PM | Project Manager |
| CM | Construction Manager |
| RE | Resident Engineer |
| QS | Quantity Surveyor |
| IFC | Issued for Construction |
| IFR | Issued for Review |
| IFA | Issued for Approval |
| AFC | Approved for Construction |
| FIDIC | Federation Internationale Des Ingenieurs-Conseils |
| JV | Joint Venture |
| LOI | Letter of Intent |
| LOA | Letter of Acceptance |
| MOM | Minutes of Meeting |
| NCR | Non-Conformance Report |
| NCN | Non-Conformance Notice |
| RCA | Root Cause Analysis |
| CAPA | Corrective and Preventive Action |
| EPC | Engineering Procurement and Construction |
| EPCC | Engineering Procurement Construction and Commissioning |
| FEED | Front End Engineering Design |
| BIM | Building Information Modeling |
| CAD | Computer Aided Design |
| CPI | Cost Performance Index |
| SPI | Schedule Performance Index |
| EV | Earned Value |
| PV | Planned Value |
| AC | Actual Cost |
| EAC | Estimate at Completion |
| ETC | Estimate to Complete |
| BAC | Budget at Completion |
| VAC | Variance at Completion |
| FAT | Factory Acceptance Test |
| SAT | Site Acceptance Test |
| O&M | Operation and Maintenance |

### 4.3 TABH/Dubai korpusuna özgü terimler — 24 adet

| Kısaltma | Repodaki anlamı |
|---|---|
| TABH | The Address Boulevard Hotel |
| DPR | Daily Progress Report |
| NOC | No Objection Certificate |
| NOD | Notice of Delay |
| NOP | Notice of Progress |
| CCTV | Closed Circuit Television |
| UPS | Uninterruptible Power Supply |
| LTR | Letter |
| DEWA | Dubai Electricity and Water Authority |
| DM | Dubai Municipality |
| JAFZA | Jebel Ali Free Zone Authority |
| AED | United Arab Emirates Dirham |
| UAE | United Arab Emirates |
| GCC | Gulf Cooperation Council |
| LEED | Leadership in Energy and Environmental Design |
| MDC | Main Distribution Center |
| CMAR | Construction Management at Risk |
| TIR | Technical Inspection Report |
| DPS | Dubai Properties |
| MVP | Material Verification Procedure |
| BMM | Building Maintenance and Management |
| TCI | TCI Engineering |
| SIRA | Systematic Integrated Risk Assessment |
| FASTA | Fire Alarm System Testing and Approval |

Bu tablo kodda bulunan anlamları aynen raporlar; terimlerin sektörel veya belirli
bir kurum/proje içindeki doğruluğunu ayrıca onaylamaz. Özellikle proje-özel
`SIRA`, `FASTA`, `MDC`, `DPS`, `BMM` ve `TCI` açılımları korpus sahibi tarafından
doğrulanmalıdır.

## 5. Alan kavram grupları

| Grup | Sorguya eklenebilen terimler |
|---|---|
| delay | delay, NOD, notice of delay, postponement, extension of time, EOT, delayed, late completion, schedule delay, time extension |
| claim | claim, notice of claim, compensation, loss and expense, damages, liquidated damages, LD, LAD, entitlement |
| approval | approval, approve, consent, no objection, NOC, acceptance, LOA, approved |
| variation | variation, change order, VO, modification, amendment, revised scope, scope change |
| payment | payment, IPC, interim payment, invoice, valuation, certification, progress payment |
| termination | termination, terminate, cancellation, suspension, suspend, breach of contract |
| progress | progress, DPR, daily progress, milestone, schedule, programme, completion |
| quality | quality, NCR, NCN, non-conformance, defect, deficiency, inspection, QA, QC |
| fire_alarm | fire alarm, FASTA, Fire Alarm System Testing and Approval, fire alarm system, fire alarm testing, fire alarm approval, SIRA, DPS, NOC, life safety |

Buradaki `IPC`, `payment` grubunda bir arama terimi olarak bulunmasına rağmen
98 öğelik ana kısaltma sözlüğünde yer almaz. Bu nedenle `expand("IPC")` açık
anlam döndürmez. Repoda başka bir yerde `IPC (Interim Progress Certificate)`
ifadesi kullanılmaktadır. Sektörel kullanım ve proje dokümanları esas alınarak
`IPC` için tek ve doğru açılım belirlenmeden ana sözlüğe eklenmemelidir.

## 6. Sorgu güçlendirme nasıl çalışır?

### 6.1 Doğrudan açılım

`expand(abbreviation)` tek bir kısaltmanın anlamını döndürür:

```text
EOT -> Extension of Time
BOQ -> Bill of Quantities
```

Arama yapmaz; yalnızca sözlük lookup işlemidir.

### 6.2 Parantezli sorgu genişletme

`expand_query(query)`, büyük harfle yazılmış bilinen kısaltmayı ve anlamını
birlikte tutar:

```text
Girdi : Show EOT status in the BOQ
Çıktı : Show EOT (Extension of Time) status in the
        BOQ (Bill of Quantities)
```

Bu biçim SQL üretimi, sorgu planlama ve hibrit yürütmede kullanılır. Hem kısa
hem açık form model bağlamında kaldığı için tablo adı, sütun adı ve kullanıcı
niyeti arasındaki eşleştirme güçlenir.

### 6.3 RAG için semantik değiştirme

`replace_query_terms_with_meanings(query)`, kısaltmayı parantezle çoğaltmak
yerine açık anlamıyla değiştirir:

```text
Girdi : Which documents are related to FASTA?
Çıktı : Which documents are related to
        Fire Alarm System Testing and Approval?
```

Bu yöntem belge embedding'inin `FASTA` gibi proje-özel kısa bir token yerine
anlamsal ifadeyi temsil etmesini sağlar. Eşleştirme büyük/küçük harfe duyarsızdır;
`fasta` da aynı şekilde açılabilir.

### 6.4 Kavram genişletme

Sorguda bir grup anahtarı geçiyorsa ilişkili terimler eklenir:

```text
Girdi : What are the delay events?
Ek bağlam:
NOD, notice of delay, postponement, extension of time, EOT,
late completion, schedule delay, time extension, ...
```

Belge RAG akışı sorguda zaten bulunmayan terimlerden en fazla altısını ekler.
Bu, belgenin “delay” yerine yalnızca “EOT” veya “notice of delay” yazdığı
durumlarda erişimi güçlendirir.

### 6.5 Ters yönlü normalizasyon

`compress_query(query)` açık anlamı kanonik kısaltmaya çevirebilir:

```text
Extension of Time approved -> EOT approved
```

Kısaltma ve açık anlam zaten birlikteyse ikinci kez sıkıştırma yapılmaz.
`normalize_query_bidirectional()` genişletme ve sıkıştırmayı birlikte uygular.

### 6.6 Sütun jargonu

`normalize_column_name()` şu iki durumu destekler:

```text
EOT        -> Extension of Time
EOT_Status -> Extension of Time - Status
```

Bulunan anlamlar tablo kataloğundaki `column_jargon` alanına yazılır ve:

- şema panelinde kullanıcıya gösterilebilir,
- router/şema bağlamına eklenir,
- SQL üreten LLM'e “Column abbreviation reference” olarak verilir,
- LLM'in olmayan bir sütun adı uydurması yerine gerçek sütun adını kullanmasına
  yardımcı olur.

## 7. Uçtan uca kullanım akışı

```text
Kullanıcı sorgusu
  |
  +--> Router
  |      Ana LLM/regex sınıflandırma: özgün sorgu
  |      Safety-net şema/embedding: gerektiğinde genişletilmiş sorgu
  |
  +--> DOCUMENT / RAG
  |      Kısaltma -> açık anlam
  |      Alan kavramı -> en fazla 6 ilişkili terim
  |      Dense + lexical retrieval -> rerank -> cevap
  |
  +--> DATA / SQL
  |      Kısaltma + açık anlam
  |      Sütun jargon açıklamaları
  |      LLM SQL üretimi -> doğrulama -> DuckDB
  |
  +--> HYBRID / PLAN
         Genişletilmiş sorguyla planlama
         Belge ve tablo sonuçlarını birlikte sentezleme
```

### Router

Ana LLM sınıflandırması özgün sorguyu kullanır. Bunun sebebi yanlış veya belirsiz
bir kısaltma açılımının sorguyu yanlış handler'a yönlendirmesini önlemektir.
LLM sınıflandırması kullanılamazsa şema-semantiği ve embedding safety-net
katmanları genişletilmiş sorgudan yararlanır.

### Belge RAG

`DocumentRAG.query()` önce kısaltmayı açık anlama çevirir, ardından ilgili alan
kavramlarını ekler. Özgün soru lexical ve rerank sinyallerinde de korunur. Bu
tasarım, hem kısa token eşleşmesini hem semantik anlam eşleşmesini kullanır.

### SQL ve tablo sorguları

`DataAnalyzerSQL._generate_sql()`:

1. gerçek tablo sütunlarını ve veri tiplerini hazırlar,
2. sütun jargon açıklamasını üretir,
3. soruyu parantezli biçimde genişletir,
4. bu bağlamı SQL üretim promptuna verir.

### Şema bağlamı

`SchemaContextBuilder`, sorguda geçen jargon terimlerini bulup `router`,
`compact` ve `full` prompt bloklarına uygun yoğunlukta ekler. Şema niyeti
analizi, kısaltmaları açık anlamlarıyla değerlendirir.

### Notice çıkarımı

Belge içinden çıkarılan notice kayıtlarında bulunan jargon terimleri de
`jargon_found` olarak tutulur. Bu alan belge meta verisini ve ilişki kurmayı
zenginleştirir.

## 8. Terimlerin sisteme giriş yolları

### 8.1 Kodla gelen yerleşik terimler

Uygulama başlarken 98 yerleşik terim belleğe alınır.

### 8.2 Diskteki özel terimler

Singleton ilk oluşturulduğunda:

1. yerleşik terimler `config/jargon_terms.json` dosyasından yüklenir,
2. bilinen konumlardaki Excel sözlükleri taranır,
3. `data/jargon/jargon_custom.json` yüklenir.

### 8.3 Excel yükleme

Dosya adı uygun bir anahtar kelime içeriyorsa iki sütunlu sözlük okunur.
Excel'den gelen terimler çalışma zamanı sözlüğüne eklenir, ancak özel terim JSON
dosyasına otomatik yazılmaz; yeniden başlatmada Excel yeniden taranarak yüklenir.

### 8.4 Belge ingest'i sırasında otomatik öğrenme

LLM belge zenginleştirmesi `new_terms` alanında:

```json
{"term": "ABC", "definition": "Example Building Certificate"}
```

üretebilir. `file_router.py` bu terimleri `add_custom_term()` üzerinden sözlüğe
ve özel JSON dosyasına ekler.

### 8.5 Kullanıcı düzeltmelerinden öğrenme

Flywheel şu biçimlerdeki düzeltmeleri ayrıştırır:

```text
ABC = Example Building Certificate
ABC means Example Building Certificate
ABC stands for Example Building Certificate
ABC: Example Building Certificate
ABC demek Example Building Certificate
ABC açılımı Example Building Certificate
```

Yakalanan terim 2-8 harf aralığında olmalıdır. Yerleşik terimler bu yolla
ezilemez.

## 9. Yönetim API'si

Tüm endpoint'ler admin yetkisiyle sunulur:

| Metot | Endpoint | İşlev |
|---|---|---|
| GET | `/api/admin/jargon` | Yerleşik terim sayısı, ilk 25 yerleşik örnek ve tüm özel terimleri döndürür |
| POST | `/api/admin/jargon` | Özel terim ekler veya aynı özel terimi günceller |
| DELETE | `/api/admin/jargon/{abbreviation}` | Özel terimi siler; yerleşik terimleri korur |
| POST | `/api/admin/jargon/reload` | Özel terimleri JSON dosyasından yeniden yükler |

POST gövdesi:

```json
{
  "abbreviation": "ABC",
  "full_form": "Example Building Certificate",
  "concept_group": "quality"
}
```

`concept_group` verilirse kısaltma ve açık anlam o grubun terim listesine de
eklenir.

## 10. Güçlü yönler

- Belge araması ile SQL üretimi için farklı genişletme stratejileri kullanır.
- Sınıflandırmayı özgün sorguda tutarak yanlış route riskini azaltır.
- Yerleşik terimleri özel terimlerden korur.
- Özel terimleri süreç yeniden başlatmalarına dayanıklı biçimde saklar.
- Kısaltma, açık anlam ve kavram ailesini aynı sistemde birleştirir.
- Tablo sütunlarını anlamlandırarak LLM'in şema kullanımını iyileştirir.
- Yeni müşteri/proje sözlüğünü belge ingest'i ve kullanıcı düzeltmeleriyle
  büyütebilir.
- Temel davranışlar `tests/test_schema_jargon_pipeline.py`,
  `tests/test_notice_graph.py`, `tests/test_integration.py` ve
  `tests/test_flywheel.py` içinde test edilir.

## 11. Bulgular, riskler ve iyileştirme önerileri

### Yüksek öncelik

1. **`IPC` ana sözlükte eksik ve anlamı tutarsız olabilir.** Kavram grubunda
   bulunur; başka kodda “Interim Progress Certificate” denir. Proje sözleşme
   terminolojisi esas alınarak anlam netleştirilmeli ve sonra sözlüğe eklenmelidir.
2. **Bağlamsal anlam ayrımı yoktur.** `AC` hem “Actual Cost” hem iklimlendirme,
   `CM`, `CO`, `RE`, `DM` gibi terimler de farklı bağlamlarda farklı anlamlar
   taşıyabilir. Proje/korpus bazlı sözlük veya güven puanlı disambiguation
   eklenmelidir.
3. **Otomatik öğrenilen terimlerde kaynak ve onay bilgisi yoktur.** LLM'in yanlış
   açılımı doğrudan kalıcı sözlüğe girebilir. `source_document`, `evidence`,
   `confidence`, `status: pending/approved` alanları eklenmelidir.
4. **Türkçe kavram genişletmesi yoktur.** `gecikme`, `hak talebi`, `ödeme`,
   `varyasyon/değişiklik`, `fesih`, `ilerleme`, `kalite`, `yangın alarmı`
   ifadeleri mevcut İngilizce grup anahtarlarını tetiklemez. Türkçe eş anlamlar
   gruplara dahil edilmelidir.

### Orta öncelik

5. **`expand_query()` yalnızca büyük harfli kısaltmaları algılar.** RAG
   değiştirmesi büyük/küçük harfe duyarsızdır; SQL ve planlama tarafındaki
   parantezli genişletme ise `eot`, `boq` gibi küçük harfli girişleri kaçırır.
6. **Başlangıç taraması ile ingest dosya adı kuralları farklıdır.** Ingest
   `kisaltma` ve `glossary` adlarını kabul eder; başlangıç taraması etmez. Tek
   ortak dosya-adı kuralı kullanılmalıdır.
7. **Kavram genişletme yalnızca grup anahtarını arar.** Örneğin `late completion`
   bir `delay` grup üyesi olsa da tek başına grubu tetiklemez. Grup üyelerinden
   gruba geri eşleme eklenmelidir.
8. **RAG'e eklenecek altı terimin sırası deterministik değildir.**
   `set -> list` dönüşümü nedeniyle süreçler arasında farklı alt kümeler
   seçilebilir. Öncelikli ve sıralı terim listesi kullanılmalıdır.
9. **Admin liste endpoint'i yerleşik terimlerin yalnızca ilk 25'ini döndürür.**
   Tam yönetim/audit için sayfalama veya tüm listeyi döndüren ayrı endpoint
   yararlı olur.

### Düşük öncelik ve bakım notları

10. `src/jargon_manager.py` üst açıklamasında hâlâ
    `storage/jargon_custom.json` yazarken gerçek yol `data/jargon/...` olarak
    tanımlanmıştır; dokümantasyon birleştirilmelidir.
11. `JARGON_CACHE_FILE` sabiti tanımlıdır fakat mevcut akışta kullanılmaz.
12. Özel bir terim silindiğinde daha önce eklendiği kavram grubundan terimlerin
    temizlenmesi görünür biçimde yapılmaz; aynı süreçte eski grup üyeleri
    bellekte kalabilir.
13. Excel yükleyicide aynı kısaltma için çakışma politikası ve kaynak önceliği
    açık değildir; son yüklenen değer önceki değeri sessizce ezer.
14. Jargon içerikleri İngilizce açık anlam taşır. Türkçe kullanıcı deneyimi için
    `meaning_en`, `meaning_tr`, `aliases`, `project_scope` gibi alanlara geçiş
    düşünülebilir.

## 12. Önerilen hedef veri yapısı

Uzun vadede basit `abbreviation -> meaning` sözlüğü yerine şu kayıt modeli daha
güvenli olur:

```json
{
  "abbreviation": "EOT",
  "meanings": {
    "en": "Extension of Time",
    "tr": "Süre Uzatımı"
  },
  "aliases": ["time extension", "extension of contract time", "süre uzatımı"],
  "concept_groups": ["delay", "claim"],
  "scope": {
    "domain": "construction",
    "project": null
  },
  "source": "builtin",
  "evidence": null,
  "confidence": 1.0,
  "status": "approved"
}
```

Bu yapı çok dillilik, proje bazlı anlam, çakışan kısaltmalar, denetlenebilir
otomatik öğrenme ve daha kontrollü sorgu genişletme sağlar.

## 13. Kaynak kod haritası

| Dosya | Jargonla ilgili görev |
|---|---|
| `config/jargon_terms.json` | Yerleşik `terim -> açıklama` jargon sözlüğü |
| `src/jargon_manager.py` | JSON sözlüğünü yükleme/doğrulama, açılım, sıkıştırma, kavram grupları, Excel/özel terim yükleme |
| `src/document_rag.py` | Belge araması için semantik değiştirme ve kavram genişletme |
| `src/router.py` | Özgün/genişletilmiş sorgunun route katmanlarında kullanımı |
| `src/schema_context.py` | Sorguya özel şema ve jargon prompt bağlamı |
| `src/data_analyzer_sql.py` | SQL promptuna genişletilmiş soru ve sütun jargonu verme |
| `src/query_planner.py` | Karmaşık sorguları jargonla genişleterek planlama |
| `src/hybrid_executor.py` | Belge + tablo hibrit sorgularında genişletme |
| `src/table_ingestion.py` | Jargon Excel dosyalarını algılama ve yükleme |
| `src/excel_table_extractor.py` | Tablo sütunlarının jargon anlamlarını çıkarma |
| `src/pdf_table_extractor.py` | PDF tablo sütunlarının jargon anlamlarını çıkarma |
| `src/file_router.py` | Belgeden yeni jargon öğrenme ve sütun meta verisini zenginleştirme |
| `src/flywheel.py` | Kullanıcı düzeltmelerinden jargon öğrenme |
| `src/notice_extractor.py` | Belge içinde geçen jargonları notice meta verisine ekleme |
| `backend/api/admin_jargon.py` | Admin CRUD ve reload endpoint'leri |
| `backend/services/document_service.py` | Viewer şema paneline sütun anlamlarını taşıma |
| `app.py` | Eski Streamlit belge analizinde jargon farkındalıklı arama |

## 14. Sonuç

Repodaki jargon sistemi, inşaat belgelerinde sık kullanılan kısaltmalar ile
proje-özel ifadeleri kullanıcı sorgularına bağlayarak daha güçlü belge ve tablo
aramaları yapılmasını sağlar. Sistem yalnızca bir terimler listesi değildir;
retrieval, SQL, şema, ingest ve öğrenme katmanlarına yayılan ortak bir anlamsal
normalizasyon servisidir.

Mevcut hali işlevseldir ve temel testlerle korunmaktadır. En önemli geliştirme
alanları `IPC` tutarlılığı, Türkçe kavramlar, bağlamsal anlam ayrımı ve otomatik
öğrenilen terimlerin insan onayından geçirilmesidir.
