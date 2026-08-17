# Proje Haritası

Kısa referans — tam mimari için kod tabanının kendisine bakılmalı, bu sadece hızlı yönlendirme içindir.

## Tenant / auth akışı

- `tenant_id` bir **text slug** (`"english-home"`, `"test-firma"`), `tenantlar.id`. Numeric surrogate değil.
- Login: `arayuz/Pages/Giris.cshtml.cs` → `kullanicilar` + `tenantlar` join → `tenant_id`, `rol`, `firma_adi`, `logo_url` cookie claim'lerine yazılır (`"Cerez"` şeması).
- Her sayfa `User.FindFirst("tenant_id")!.Value` ile okur. Roller: `kullanici`, `yonetici` (`[Authorize(Roles="yonetici")]`).
- Python tarafının **hiç auth bilgisi yok** — `.NET`'in her isteğe eklediği `tenant_id` string parametresine körü körüne güvenir (iç ağ, 127.0.0.1).

## DB tabloları ve ilişkiler

| Tablo | Anahtar kolonlar | İlişki |
|---|---|---|
| `tenantlar` | `id` text (slug) PK, `ad`, `sahip_eposta`, `logo_url` | — |
| `kullanicilar` | `id` bigint PK, `eposta` unique, `tenant_id`, `rol` | FK→`tenantlar.id` |
| `belgeler` | `id` bigint PK, `tenant_id`, `dosya_adi`, `dosya_yolu` (nullable), `departman_id` (nullable), `erisim_seviyesi` (nullable text, CHECK `sirket`/`departman`) | FK `tenant_id→tenantlar.id`, FK `departman_id→departmanlar.id` |
| `parcalar` | `id` bigint PK, `tenant_id` (FK'siz, denormalize), `bolum` (nullable, hep NULL — kullanılmıyor), `metin`, `vektor vector(1024)`, `belge_id`, `departman_id` (nullable, FK'siz, denormalize), `erisim_seviyesi` (nullable text, FK'siz denormalize, CHECK `sirket`/`departman`) | FK `belge_id→belgeler.id` ON DELETE CASCADE |
| `departmanlar` | `id` bigserial PK, `tenant_id`, `ad`, `olusturma_tarihi`, UNIQUE(`tenant_id`,`ad`) | FK `tenant_id→tenantlar.id` |
| `kullanici_departmanlari` | `kullanici_id` bigint, `departman_id` bigint, `olusturma_tarihi`, PK(`kullanici_id`,`departman_id`) | FK `kullanici_id→kullanicilar.id` ON DELETE CASCADE, FK `departman_id→departmanlar.id` ON DELETE CASCADE |
| `sohbetler` | `id` bigint PK, `tenant_id`, `eposta`, `baslik` | — |
| `mesajlar` | `id` bigint PK, `sohbet_id`, `rol`, `metin`, `skor` (nullable) | FK `sohbet_id→sohbetler.id` ON DELETE CASCADE |

`vektor` üzerinde ANN indeksi yok (brute-force `<=>` taraması) — küçük veri hacminde sorun değil.

## Belge yükleme akışı

`Yukle.cshtml` (yonetici-only) → `YukleModel.OnPostAsync` (`arayuz/Pages/Yukle.cshtml.cs`) → multipart POST `http://127.0.0.1:8000/indeksle` → `servis.py::indeksle_endpoint` → `indeksle.py::indeksle()` (metadata `belgeler`'e INSERT edilen TEK yer) → `.NET` tarafı ayrıca PDF'i `belge-deposu/`'a kopyalayıp `belgeler.dosya_yolu`'nu ayrı bir `UPDATE` ile yazar (Python bu kolonu hiç bilmez).

## Chunk / embedding akışı

`pdf_oku.py` (metin çıkarma) → `parcala.py::parcalar_uret` (300 karakter, 50 örtüşme, sabit boyut) → `embed.py` (`BAAI/bge-m3`, tekil `model`) → `indeksle.py::indeksle()` hepsini toplu `encode()` edip `parcalar`'a yazar (`belge_id` ile bağlı, `tenant_id` ayrıca denormalize).

## Retrieval akışı

`sorgu.py::cevapla(soru, tenant_id)` → soru embed edilir → **doğrudan `parcalar` üzerinde**, `belgeler`'e JOIN yapmadan, `WHERE tenant_id=%s ORDER BY vektor<=>%s LIMIT 3` → skor `ESIK`(0.54) altındaysa reddeder → üstündeyse `llm.py::sor()` (OpenRouter, Türkçe/literal-only sistem promptu). `servis.py::/sor` bunu FastAPI endpoint olarak açar, `Index.cshtml.cs::OnPostAsync` çağırır.

## Chat akışı (üst seviye)

`Index.cshtml` composer → `IndexModel.OnPostAsync` → `/sor`'a POST + cevabı `mesajlar`'a yaz → `SohbetPaneliViewComponent` (`arayuz/Views/Shared/Components/SohbetPaneli/Default.cshtml`) sol panelde son 20 sohbeti listeler ("Daha fazla göster" ile 20'şer artar), hover'da `⋯` menüsünden yeniden adlandırma/silme (`OnPostSohbetYenidenAdlandir` / `OnPostSohbetSil`, ikisi de `IndexModel`'de).

## Önemli dosyalar (alan → dosya)

- Auth/login: `arayuz/Pages/Giris.cshtml.cs`, `arayuz/Sifre.cs`
- DB bağlantısı: `arayuz/Db.cs` (tek bağlantı yardımcı fonksiyonu, repository katmanı YOK — her sayfa kendi `NpgsqlCommand`'ını yazar)
- Belge yükleme: `arayuz/Pages/Yukle.cshtml(.cs)`, `servis.py`, `indeksle.py`
- Chunking/embedding: `parcala.py`, `embed.py`, `pdf_oku.py`
- Retrieval/LLM: `sorgu.py`, `llm.py`
- Chat sayfası: `arayuz/Pages/Index.cshtml(.cs)`
- Sohbet paneli: `arayuz/ViewComponents/SohbetPaneliViewComponent.cs`, `arayuz/Views/Shared/Components/SohbetPaneli/Default.cshtml`
- Belge listesi: `arayuz/Pages/Belgeler.cshtml(.cs)`

## Kural: tenant filtresi her sorguda açık olmalı

Merkezi bir RLS/middleware YOK. Her yeni sorguda `where tenant_id = @t` (veya Python'da `%s`) elle eklenmek zorunda — `parcalar` gibi `belgeler`'e join yapmayan tablolarda `tenant_id` bu yüzden ayrıca (FK'siz) denormalize edilmiş durumda.

## Departman mimarisi — mevcut durum

Adım A–E tamamlandı: DB temeli, upload'da departman seçimi, departman-filtreli retrieval, sohbette manuel departman seçici, Genel Asistan otomatik yönlendirme.

- `departmanlar` tablosu var (`tenant_id`, `ad`, UNIQUE(`tenant_id`,`ad`)). English Home için 4 departman seed edildi (bkz. `migrations/001_departmanlar.sql`).
- `belgeler.departman_id` ve `parcalar.departman_id` nullable, `parcalar.departman_id` `tenant_id` ile aynı gerekçeyle FK'siz denormalize. Mevcut eski satırlar `departman_id = NULL` kaldı, backfill yapılmadı.
- Upload (`Yukle.cshtml(.cs)`) departmanı zorunlu kılar, sahiplik sunucu tarafında doğrulanır, `indeksle.py` her iki tabloya da yazar.
- Sohbet (`Index.cshtml(.cs)`) sağ-üstte tenant'a özel bir departman seçici gösterir; seçim composer'ın gizli alanına senkronlanıp `/sor`'a `departman_id` olarak gider.
- **`Genel Asistan` = embedding/retrieval-tabanlı dinamik departman yönlendirmesi; bir DB departmanı DEĞİL.** `DepartmanId == null` bu modu temsil eder (varsayılan, taze sohbette seçili). `sorgu.py::departman_yonlendir` soruyu (tek encode, ikinci model çağrısı yok) `departman_id IS NOT NULL` olan en yakın parçaya göre bir departmana yönlendirir; departman-etiketli hiç parça yoksa TÜM departmanlarda aramaya düşmez, güvenli "bilgi yok" cevabı döner. Kullanıcı açıkça bir departman seçtiğinde yönlendirme tamamen atlanır. Departman isimleri/ID'leri hiçbir yerde hardcode edilmedi.

## Erişim kontrolü — DB temeli (Adım A, `migrations/002_erisim_kontrolu.sql`)

Sadece şema hazır — uygulama kodu (servis.py/sorgu.py/indeksle.py/Razor) henüz bu tabloyu/kolonları kullanmıyor, ayrı bir entegrasyon adımında bağlanacak.

- `kullanici_departmanlari` (`kullanici_id`, `departman_id`, PK ikili) — bir kullanıcının **açıkça üye olduğu** departmanları tutar, çok-çok. Hiç satır seed edilmedi (üyelik tahmin edilerek atanmaz).
- `belgeler.erisim_seviyesi` / `parcalar.erisim_seviyesi` (nullable text, CHECK `'sirket'` / `'departman'`) — bu iki eksen BİLİNÇLİ olarak ayrı: `departman_id` belgenin **konusunu/sahipliğini** açıklar, `erisim_seviyesi` ise o belgeyi **kimin okuyabileceğini** açıklar. `'sirket'` = tenant'taki herkes okuyabilir, `'departman'` = sadece `kullanici_departmanlari` üzerinden o departmana üye kullanıcılar okuyabilir.
- **NULL = default-deny.** Mevcut satırlar backfill edilmedi, bilinçli olarak NULL kaldı — entegrasyon tamamlanana kadar (ve entegrasyondan sonra da, seviyesi hiç atanmamış herhangi bir satır için) NULL bir satır erişime KAPALI sayılacak, "sirket" gibi açık/varsayılan sayılmayacak.
