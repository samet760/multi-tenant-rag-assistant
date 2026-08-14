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
| `belgeler` | `id` bigint PK, `tenant_id`, `dosya_adi`, `dosya_yolu` (nullable), `departman_id` (nullable) | FK `tenant_id→tenantlar.id`, FK `departman_id→departmanlar.id` |
| `parcalar` | `id` bigint PK, `tenant_id` (FK'siz, denormalize), `bolum` (nullable, hep NULL — kullanılmıyor), `metin`, `vektor vector(1024)`, `belge_id`, `departman_id` (nullable, FK'siz, denormalize) | FK `belge_id→belgeler.id` ON DELETE CASCADE |
| `departmanlar` | `id` bigserial PK, `tenant_id`, `ad`, `olusturma_tarihi`, UNIQUE(`tenant_id`,`ad`) | FK `tenant_id→tenantlar.id` |
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

**Adım A (bu commit) tamamlandı: sadece DB temeli.**

- `departmanlar` tablosu var (`tenant_id`, `ad`, UNIQUE(`tenant_id`,`ad`)).
- `belgeler.departman_id` ve `parcalar.departman_id` eklendi, ikisi de **nullable**, `parcalar.departman_id` `tenant_id` ile aynı gerekçeyle **FK'siz denormalize**.
- English Home için 4 departman seed edildi (bkz. `migrations/001_departmanlar.sql`). `Genel Asistan` bir departman **değil** — ileride ayrı bir yönlendirme modu olacak, DB'de satır olarak yok.
- Mevcut belgeler/parcalar `departman_id = NULL` kaldı, backfill yapılmadı.
- **Henüz uygulama koduna bağlanmadı** — `indeksle.py`, `servis.py`, `sorgu.py`, `Yukle`/`Index` sayfaları departman kolonlarını henüz kullanmıyor. Departman isimleri hiçbir yerde hardcode edilmemeli; ileride tenant'a göre `departmanlar` tablosundan okunmalı.
