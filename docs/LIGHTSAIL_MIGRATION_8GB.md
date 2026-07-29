# Lightsail 2 GB → 8 GB taşıma runbook'u

**Kısa cevap: evet, mümkün ve doğrudan yapılabilir.** Lightsail bir örneği yerinde
büyütmeye izin vermez; resmî yol **snapshot alıp o snapshot'tan daha büyük bir
örnek oluşturmaktır**. Bu, diskin AWS içinde birebir klonlanması demek — dokümanlar,
vektörler, veritabanları, nginx yapılandırması, SSH anahtarları, hepsi olduğu gibi
gelir. **Ağ üzerinden tek bir dosya kopyalanmaz.**

> SSH anahtarı artık elimde (`~/.ssh/lightsail-eu-central-1.pem`), bu yüzden
> aşağıdaki ölçümler tahmin değil, kutudan okundu. Ama **snapshot alma ve örnek
> oluşturma AWS konsolundan yapılır** ve bende AWS kimlik bilgisi yok — o iki
> adım sizin. Sunucu tarafındaki komutları ben çalıştırabilirim.

---

## Kutunun gerçek hâli (2026-07-29, SSH ile ölçüldü)

Taşımayı planlarken tahmin etmeyin — ölçüm şu:

```
Disk    : 58G toplam, 41G dolu (%71)
Bellek  : 1.9G toplam, 573M kullanılabilir, swap'ın 1.2G'si kullanımda
/opt/mvp-api : 21G   (data/edinburgh_pdfs tek başına 17G,
                      qdrant_storage 1.5G, storage 1.2G)
```

Bellek zaten dibe vurmuş durumda — 8 GB'a geçme gerekçeniz sayılarla doğrulanıyor.

**Ve bu kutuda COAir'den başka dört uygulama daha var:**

| Uygulama | Dizin | Konteynerler |
|---|---|---|
| COAir | `/opt/mvp-api` | `mvp-api`, `mvp-qdrant` |
| dental-clinic-app | `/opt/dental-clinic-app` | `dental-web`, `dental-api`, `dental-postgres` |
| job-hunter | `/opt/job-hunter` | `job-hunter-ui`, `job-hunter-api` |
| lovelog | `/opt/lovelog` | `lovelog-api`, `lovelog` (ikisi de *unhealthy* — taşımadan önce de öyleydi) |

Dört TLS sertifikası ve alan adı da burada:
`dental-clinic-app.duckdns.org`, `lovelog-sude.duckdns.org`,
`roadmap-remote.duckdns.org`, **`rolehunter.app`**.

Bu yüzden elle dizin kopyalamak yanlış: dört uygulamayı, nginx bloklarını ve
sertifikaları geride bırakırsınız. **Bütün-makine snapshot'ı tek doğru yol.**

---

## Adım 0 — IP: taşımanın tek gerçek karar noktası

Lightsail konsolu → örnek → **Networking**. Public IP'nin yanında "Static IP"
yazıyor mu?

| Durum | Sonuç |
|---|---|
| **Statik** | IP'yi eskiden ayırıp yeniye bağlarsınız. `18.185.38.217` korunur — GitHub secret'ı, dört alan adı, sertifikalar, yer imleri: hiçbiri değişmez. Taşıma 30 dakikalık bir iş olur. |
| **Dinamik** (varsayılan) | Yeni örnek **yeni bir IP** alır ve peşinden şunlar gelir ↓ |

IP değişirse elle düzeltilmesi gerekenler:

1. `LIGHTSAIL_HOST` GitHub secret'ı — yoksa deploy eski kutuya gitmeye devam eder
2. **Üç DuckDNS kaydı** — duckdns.org'da elle güncellenecek.
   Sunucuda **otomatik güncelleyici cron'u yok**, kontrol ettim.
3. **`rolehunter.app`** — A kaydı kayıt firmasında güncellenecek
4. COAir'in kendi adresi (alan adı yok, ham IP ile erişiliyor)

Sertifikalar alan adına bağlı olduğu için IP değişiminden etkilenmez; ama DNS
düzelene kadar Certbot yenilemesi başarısız olur.

**Öneri:** statik IP yoksa şimdi oluşturup mevcut örneğe bağlayın. Lightsail'de
mevcut dinamik IP statiğe *çevrilemez* — yani bir kez IP değişimi yaşayacaksınız.
Bunu taşımanın ortasında değil, şimdi sakin kafayla yaşamak çok daha ucuz.
Sonrasında taşıma IP'ye hiç dokunmaz.

---

## Aktarılması gereken durum (hepsi snapshot'a dâhil)

`/opt/mvp-api/` altında:

| Ne | İçerik |
|---|---|
| `data/` | 7.404 doküman (7.282 PDF, 122 tablo) — **en büyük parça** |
| `qdrant_storage/` | vektör indeksi; kaybolursa tüm korpusun yeniden ingest'i gerekir |
| `storage/` | sohbet geçmişi, `users.db`, `events.db` (27.676 olay), `document_registry.json`, parquet |
| `.env.production` | API anahtarları + `JWT_SECRET` (chmod 600) |
| `docker-compose.prod.yml` | zaten her deploy'da yeniden gönderiliyor |

Kutu seviyesinde ayrıca: Docker + compose kurulumu, `/etc/nginx/sites-available/`
altındaki yapılandırma, `/swapfile`, ve `~/.ssh/authorized_keys` (GitHub Actions'ın
deploy edebilmesi buna bağlı).

Bunların hiçbiri COAir'e özel değil: yukarıdaki dört uygulamanın kendi verisi,
nginx blokları ve sertifikaları da aynı diskte. Snapshot hepsini birden taşır.

---

## Kritik incelik: snapshot'ı **yazma sırasında** almayın

`storage/events/events.db`, `storage/users.db` ve Qdrant'ın segment dosyaları
canlı veritabanları. Uygulama yazarken alınan snapshot bunları **yarım yazılmış**
hâlde yakalayabilir — dosya bozuk çıkar ve bunu ancak günler sonra fark edersiniz.

Bu hafta tam olarak bu sınıftan bir kusur yaşandı: yarım/bozuk JSON'lar sohbet
geçmişini sessizce siliyordu. Aynı hatayı taşıma sırasında tekrarlamayın.

**Kural: snapshot'tan önce konteynerleri durdurun.**

---

## Yol A — Basit (kesinti ~30-45 dk, en az hareketli parça)

Lansman sonrası sakin bir saatte yapın.

```bash
SSH_KEY=~/.ssh/lightsail-eu-central-1.pem
SRV=ubuntu@18.185.38.217

# 1) Yazmaları durdur — tutarlı bir snapshot için tek gereken bu
ssh -i $SSH_KEY $SRV "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml down"
# diğer dört uygulama da yazmayı bıraksın (dental postgres özellikle)
for d in /opt/job-hunter /opt/dental-clinic-app /opt/lovelog; do
  ssh -i $SSH_KEY $SRV "cd $d && sudo docker compose down 2>/dev/null || true"
done
ssh -i $SSH_KEY $SRV "sync"
```

2. **Lightsail konsolu → örnek → Snapshots → "Create snapshot".** Bitmesini bekleyin
   (disk boyutuna göre 10-25 dk).
3. Snapshot satırında **⋮ → "Create new instance"**. Açılan ekranda:
   - Bölge: **aynı** (Frankfurt / eu-central-1)
   - Bundle: **8 GB** (Lightsail yalnızca yukarı yönde izin verir; 2 → 8 sorunsuz)
   - İsim: `mvp-api-8gb`
4. Yeni örnek açılınca **Networking → Firewall**: 22 ve 80 portlarını açın
   (kural seti bundle ile gelmez).
5. **Doğrulayın** (aşağıdaki kontrol listesi) — henüz IP'yi taşımadan, yeni örneğin
   kendi IP'si üzerinden.
6. Statik IP'yi eskiden ayırıp yeniye bağlayın. (Statik IP yoksa: `LIGHTSAIL_HOST`
   secret'ını yeni IP ile güncelleyin.)
7. Yeni kutuda ayağa kaldırın:
   ```bash
   ssh -i $SSH_KEY ubuntu@<yeni-ip> "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml up -d"
   ```
8. Eski örneği **silmeyin** — durdurun ve birkaç gün öyle bıraksın. Geri dönüş yolunuz o.

---

## Yol B — Kesintiyi dakikalara indirmek isterseniz

Adımlar aynı, tek fark: snapshot'ı aldıktan sonra eski kutuyu geri açarsınız ve
aradaki farkı sonradan senkronlarsınız.

1. Yol A'nın 1-4. adımları (snapshot alınır alınmaz eski kutuyu `up -d` ile geri açın).
2. Yeni örnek hazır ve doğrulanmış olsun.
3. Geçiş anı — eski kutuyu durdurup **yalnızca değişen dosyaları** aktarın:
   ```bash
   ssh -i $SSH_KEY $SRV "cd /opt/mvp-api && sudo docker compose -f docker-compose.prod.yml down"
   # eski kutudan yeniye, sadece delta
   ssh -i $SSH_KEY $SRV "sudo rsync -az --delete \
       /opt/mvp-api/storage/ /opt/mvp-api/data/ /opt/mvp-api/qdrant_storage/ \
       -e 'ssh -i /home/ubuntu/.ssh/<sunucudaki-anahtar>' ubuntu@<yeni-ip>:/opt/mvp-api/"
   ```
   (Ya da kendi makinenizden iki ayaklı `rsync`. Delta küçük olur; asıl kütle
   snapshot'la zaten taşındı.)
4. Statik IP'yi taşıyın, yeni kutuda `up -d`.

`--delete` bilerek var: aksi hâlde snapshot ile geçiş arasında silinen bir sohbet
yeni kutuda geri dirilir.

---

## Doğrulama — tek komut

[`scripts/verify_instance.sh`](../scripts/verify_instance.sh) her şeyi tek seferde
kontrol eder. Taşımadan **önce** eski kutuda çalıştırıp taban çizgisini alın,
sonra yenisinde çalıştırıp `diff` alın:

```bash
./scripts/verify_instance.sh http://18.185.38.217 > baseline.txt
./scripts/verify_instance.sh http://<yeni-ip>     > after.txt
diff baseline.txt after.txt
```

2026-07-29'da alınan taban çizgisi:

```
health                             {"status":"ok"}
login                              ok
documents (library)                7404
events (chronology)                27676
authored chronologies              6
conversations                      110
pdf viewer                         pdf p.5/32 image=True
chat (vectors present?)            11 citations, route=document
```

Son satır en kritiği: diğer her şey doğru gelirken `qdrant_storage/` eksik
taşınmış olabilir ve tek belirtisi sohbetin sessizce hiçbir şey bulamaması olur.
(Script kendi kontrolü için bir sohbet açtığından `conversations` sayısı her
koşuşta 1 artar — diff'teki +1 taşımadan değil, script'ten.)

<details>
<summary>Elle kontrol etmek isterseniz</summary>

Yeni örnek ayağa kalktıktan sonra, IP'yi taşımadan önce (yeni IP üzerinden):

```bash
NEW=http://<yeni-ip>

curl -s $NEW/api/health                      # {"status":"ok"}
TOKEN=$(curl -s -X POST $NEW/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"admin2","password":"admin123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 1) Doküman sayısı — 7.404 olmalı
curl -s -H "Authorization: Bearer $TOKEN" $NEW/api/library | python3 -c "import sys,json;print(len(json.load(sys.stdin)))"

# 2) Sohbet geçmişi — 106+ olmalı, ve hepsi açılmalı
curl -s -H "Authorization: Bearer $TOKEN" $NEW/api/conversations | python3 -c "import sys,json;print(len(json.load(sys.stdin)))"

# 3) Olay deposu — 27.676 olmalı
curl -s -H "Authorization: Bearer $TOKEN" $NEW/api/chronology/summary

# 4) Vektörler yerinde mi — asıl sınav. Cevap atıflı gelmeli.
#    Boş/atıfsız gelirse qdrant_storage/ eksik taşınmıştır.
CID=$(curl -s -X POST $NEW/api/conversations -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"title":"migration check"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('id') or d.get('conversation_id'))")
curl -s -X POST $NEW/api/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"message\":\"What caused the delay to construction of the depot?\",\"conversation_id\":\"$CID\",\"request_id\":\"mig\"}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('atıf:',len(d.get('citations') or []))"

# 5) PDF görüntüleyici
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  "$NEW/api/docs/CEC00381196_PART1.pdf/content?anchor=page_5"
```

Beklenen: 7.404 doküman, 106+ sohbet, 27.676 olay, atıf sayısı > 0, PDF 200.

</details>

**Diğer dört uygulamayı da unutmayın** — snapshot onları da taşır, ama çalıştıklarını
görmek gerekir:

```bash
ssh -i ~/.ssh/lightsail-eu-central-1.pem ubuntu@<yeni-ip> \
  "sudo docker ps --format '{{.Names}}\t{{.Status}}'"
```

Dokuz konteyner görünmeli. `lovelog-api` ve `lovelog` **taşımadan önce de
unhealthy'ydi** — bu taşımanın eseri değil, karıştırmayın.

Deploy hattının da hâlâ çalıştığını görün: `main`'e küçük bir commit atıp
GitHub Actions'ın yeni kutuya deploy ettiğini doğrulayın.

---

## Taşıma sonrası: 8 GB ile ne değişir

Bunları taşımayla **aynı anda** yapmayın — önce taşıma otursun, sonra tek tek.

- `docs/` ve hafıza notları "2 GB kutu bellek baskısında donuyor, cross-encoder
  KAPALI kalmalı" diyor. 8 GB'da bu kısıt kalkıyor; yeniden değerlendirilebilir.
- Deploy sağlık kapısı 240 sn'ye çekilmişti çünkü soğuk açılış swap'a takılıyordu
  ([deploy.yml](../.github/workflows/deploy.yml)). 8 GB'da açılış belirgin
  hızlanmalı; deploy sonrası ilk sorgunun ~100 sn sürmesi de bundandı.
- `/swapfile` kalabilir; zararı yok, artık nadiren dokunulur.

---

## Riskler ve geri dönüş

| Risk | Karşılık |
|---|---|
| Snapshot yazma sırasında alınır → bozuk DB | Konteynerleri önce durdurun (yukarıda) |
| Yeni örnekte IP değişir, deploy eski kutuya gider | `LIGHTSAIL_HOST` secret'ını güncelleyin; ya da önceden statik IP bağlayın |
| Firewall kuralları taşınmaz | Yeni örnekte 22 + 80'i elle açın |
| `job-hunter` unutulur | Snapshot yolu bunu zaten taşır; elle kopyalama yolunu seçmeyin |
| Bir şey ters gider | Eski örnek **silinmemiş**, durmuş hâlde: statik IP'yi geri bağlayıp `up -d` |

Eski örneği en az bir hafta tutun. Lightsail'de duran bir örnek yine ücretlendirilir,
ama bir haftalık ücret geri dönüş yolu olmamasından ucuzdur.
