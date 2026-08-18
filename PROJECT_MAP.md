# Proje Haritası

Kısa referans — tam mimari için kod tabanının kendisine bakılmalı, bu sadece hızlı yönlendirme içindir.

## Tenant / auth akışı

- `tenant_id` bir **text slug** (`"english-home"`, `"test-firma"`), `tenantlar.id`. Numeric surrogate değil.
- Login: `arayuz/Pages/Giris.cshtml.cs` → `kullanicilar` + `tenantlar` join → `tenant_id`, `rol`, `firma_adi`, `logo_url`, **`kullanici_id`** cookie claim'lerine yazılır (`"Cerez"` şeması). `kullanici_id` = `kullanicilar.id`, sadece DB'den doğrulanmış login satırından gelir (bkz. "Erişim kontrolü" bölümü).
- Her sayfa `User.FindFirst("tenant_id")!.Value` ile okur. Roller: `kullanici`, `yonetici` (`[Authorize(Roles="yonetici")]`).
- Python tarafının kendi auth mekanizması YOK — `.NET`'in her isteğe eklediği `tenant_id`/`kullanici_id`/`rol` parametrelerine güvenir (iç ağ, 127.0.0.1); bu güven `/sor` için artık sadece `tenant_id` ile sınırlı değil, RAG yetkilendirmesinin de temeli (bkz. "Erişim kontrolü").

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
| `mesaj_kaynaklari` | `mesaj_id` bigint, `belge_id` bigint, `olusturma_tarihi`, PK(`mesaj_id`,`belge_id`) | FK `mesaj_id→mesajlar.id` ON DELETE CASCADE, FK `belge_id→belgeler.id` ON DELETE CASCADE |

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
- Belge listesi/gezinme: `arayuz/Pages/Belgeler.cshtml(.cs)`
- Belge açma (yetkilendirmeli indirme): `arayuz/Pages/BelgeIndir.cshtml.cs`
- Belge metadata düzenleme: `arayuz/Pages/BelgeDuzenle.cshtml(.cs)`
- Departman yönetimi (CRUD): `arayuz/Pages/Departmanlar.cshtml(.cs)`
- Kullanıcı yönetimi (rol yükselt/düşür): `arayuz/Pages/Kullanicilar.cshtml(.cs)`
- Kullanıcı-departman yetki yönetimi: `arayuz/Pages/KullaniciDepartmanlari.cshtml(.cs)`
- Salt-okunur kullanıcı yetkileri: `arayuz/Pages/Yetkilerim.cshtml(.cs)`

## Kural: tenant filtresi her sorguda açık olmalı

Merkezi bir RLS/middleware YOK. Her yeni sorguda `where tenant_id = @t` (veya Python'da `%s`) elle eklenmek zorunda — `parcalar` gibi `belgeler`'e join yapmayan tablolarda `tenant_id` bu yüzden ayrıca (FK'siz) denormalize edilmiş durumda.

## Departman mimarisi — mevcut durum

Adım A–E tamamlandı: DB temeli, upload'da departman seçimi, departman-filtreli retrieval, sohbette manuel departman seçici, Genel Asistan otomatik yönlendirme.

- `departmanlar` tablosu var (`tenant_id`, `ad`, UNIQUE(`tenant_id`,`ad`)). English Home için 4 departman seed edildi (bkz. `migrations/001_departmanlar.sql`).
- `belgeler.departman_id` ve `parcalar.departman_id` nullable, `parcalar.departman_id` `tenant_id` ile aynı gerekçeyle FK'siz denormalize. Mevcut eski satırlar `departman_id = NULL` kaldı, backfill yapılmadı.
- Upload (`Yukle.cshtml(.cs)`) departmanı zorunlu kılar, sahiplik sunucu tarafında doğrulanır, `indeksle.py` her iki tabloya da yazar.
- Sohbet (`Index.cshtml(.cs)`) sağ-üstte tenant'a özel bir departman seçici gösterir; seçim composer'ın gizli alanına senkronlanıp `/sor`'a `departman_id` olarak gider.
- **`Genel Asistan` = embedding/retrieval-tabanlı dinamik departman yönlendirmesi; bir DB departmanı DEĞİL.** `DepartmanId == null` bu modu temsil eder (varsayılan, taze sohbette seçili). `sorgu.py::departman_yonlendir` soruyu (tek encode, ikinci model çağrısı yok) `departman_id IS NOT NULL` olan en yakın parçaya göre bir departmana yönlendirir; departman-etiketli hiç parça yoksa TÜM departmanlarda aramaya düşmez, güvenli "bilgi yok" cevabı döner. Kullanıcı açıkça bir departman seçtiğinde yönlendirme tamamen atlanır. Departman isimleri/ID'leri hiçbir yerde hardcode edilmedi.

## Erişim kontrolü (Adım A–C, tamamlandı ve runtime-test edildi)

DB temeli (`migrations/002_erisim_kontrolu.sql`) ve uygulama katmanındaki zorunlu kılma (Adım C) ikisi de tamamlandı — yetkilendirme artık gerçekten uygulanıyor, sadece şema değil.

- `kullanici_departmanlari` (`kullanici_id`, `departman_id`, PK ikili) — bir kullanıcının **açıkça üye olduğu** departmanları tutar, çok-çok. Hiç satır seed edilmedi (üyelik tahmin edilerek atanmaz).
- `belgeler.erisim_seviyesi` / `parcalar.erisim_seviyesi` (nullable text, CHECK `'sirket'` / `'departman'`) — bu iki eksen BİLİNÇLİ olarak ayrı: `departman_id` belgenin **konusunu/sahipliğini** açıklar, `erisim_seviyesi` ise o belgeyi **kimin okuyabileceğini** açıklar. `'sirket'` = tenant'taki herkes okuyabilir, `'departman'` = sadece `kullanici_departmanlari` üzerinden o departmana üye kullanıcılar (veya `yonetici`) okuyabilir.
- **Güvenilir kimlik akışı:** `Giris.cshtml.cs` → `kullanici_id`/`rol` claim'leri → `Index.cshtml.cs::OnPostAsync` bunları (mevcut `tenant_id`/`departman_id` ile birlikte) `/sor`'a gönderir → `servis.py::SoruIstegi` (`kullanici_id`, `rol` zorunlu alanlar) → `sorgu.py::cevapla`/`departman_yonlendir`. Tarayıcıdan gelen hiçbir değere güvenilmez, sadece DB'den doğrulanmış login satırına.
- **Yetkilendirme kuralı (`kullanici` rolü):** bir parça (`sirket` erişimliyse HERKESE), (`departman` erişimliyse VE `departman_id` doluysa VE `kullanici_departmanlari`'nda o departman için açık bir üyelik satırı varsa) okunabilir.
- **`yonetici` MVP'de tenant admin'i gibi davranır:** `sirket` parçalarına ek olarak, aynı tenant içindeki HERHANGİ bir `departman` parçasını `kullanici_departmanlari` üyeliği ARANMADAN okuyabilir.
- **Varsayılan-red kuralları (herkes için):** `erisim_seviyesi IS NULL` → reddedilir (ne `sirket` ne `departman` dalına uyar). `erisim_seviyesi = 'departman'` VE `departman_id IS NULL` → reddedilir. Mevcut satırlar backfill edilmedi, bilinçli olarak NULL kaldı.
- **Predikat SQL WHERE içinde, vector `ORDER BY`/`LIMIT`'ten ÖNCE uygulanır** — yetkisiz bir parça aday havuzuna hiç girmez, sonradan filtrelenmez. AYNI predikat hem `sorgu.py::departman_yonlendir` (Genel Asistan yönlendirmesi) hem `cevapla`'nın asıl getirme sorgusunda kullanılır — manuel departman seçimi de bu predikate tabidir, ATLAYAMAZ.
- **Runtime doğrulandı:** `sirket` izinli → erişim VAR; `NULL` erişim → RED; üyeliksiz `departman` → RED; üyelikli `departman` → erişim VAR; `yonetici` üyeliksiz `departman`'a → erişim VAR; Genel Asistan yönlendirmesi sadece yetkili aday havuzuna göre karar veriyor.

## Admin & Bilgi Yönetimi — tamamlandı

Yukarıdaki departman mimarisi ve erişim kontrolü temeli üzerine, Supabase SQL Editor'e HİÇ gerek kalmadan uygulama içinden yönetim için eklendi:

- **Departman yönetimi** (`arayuz/Pages/Departmanlar.cshtml(.cs)`, yönetici-only): listeleme, oluşturma, yeniden adlandırma, silme — hepsi `tenant_id` scoped. Silme, `belgeler.departman_id` FK'sinin (ON DELETE NO ACTION, bkz. migrations/001) engeliyle korunur — o departmana bağlı belge varsa Postgres silmeyi reddeder; force-delete veya arşiv modeli YOK, admin önce belgeleri başka bir departmana taşımak/silmek zorunda.
- **Güvenli departman-bazlı belge gezinme** (`/Belgeler`, bkz. yukarıdaki dosya listesi): önce tenant departmanları kart/liste olarak gösterilir, bir departman seçilince (`?departmanId=`) o departmanın belgeleri listelenir. Normal `kullanici` sadece yetkili olduğu belgeleri görür (`sirket` → tenant geneli, `departman` → `kullanici_departmanlari` üyeliği zorunlu); `yonetici` üyelik aranmadan tüm `departman` belgelerini de görür. `erisim_seviyesi IS NULL` her zaman gizli (varsayılan-red). Doğrudan `/BelgeIndir?id=` açma da AYNI yetkilendirme predikatını tekrar uygular ve reddedince tek tip `NotFound()` döner — liste kısıtı id tahmin ederek ATLANAMAZ.
- **Kullanıcı-departman yetki yönetimi** (`arayuz/Pages/KullaniciDepartmanlari.cshtml(.cs)`, `/Kullanicilar`'daki her kullanıcı satırından ulaşılır): açık `kullanici_departmanlari` satırları uygulama içinden verilebilir/kaldırılabilir. Her grant/revoke, hem kullanıcının hem departmanın çağıran yöneticinin tenant'ına ait olduğunu AYNI SQL ifadesi içinde ispatlar (tablonun kendi `tenant_id` kolonu yok). `yonetici` kullanıcılar için üyelik kontrolleri UI'da BİLİNÇLİ olarak gösterilmez — rol zaten üyelikten bağımsız tenant geneli erişime sahip, editable checkbox göstermek yanıltıcı olurdu.
- **Belge metadata düzenleme** (`arayuz/Pages/BelgeDuzenle.cshtml(.cs)`, yönetici-only): mevcut bir belgenin departmanı ve erişim seviyesi düzeltilebilir. `belgeler` ve o belgeye ait TÜM `parcalar` satırları AYNI transaction içinde güncellenir (biri başarısız olursa ikisi de geri alınır) — vektörler/metin/chunk'lar YENİDEN ÜRETİLMEZ, sadece denormalize metadata kopyaları senkron tutulur.
- **Salt-okunur "Departman Yetkilerim"** (`arayuz/Pages/Yetkilerim.cshtml(.cs)`, normal `kullanici`'ye özel nav girişi): kullanıcı sadece kendi açık departman üyeliklerini görür, hiçbir mutasyon kontrolü YOK. Şirket geneli erişim AÇIKLAYICI bir not olarak gösterilir, bireysel bir izinmiş gibi SUNULMAZ. `yonetici` bu sayfaya nav linki almaz (rol zaten üyelikten bağımsız erişime sahip); sayfa doğrudan URL ile ziyaret edilirse güvenli, salt-bilgilendirici bir mesaj gösterir.

**Runtime doğrulandı:** erişim-kontrolü izin/red matrisi (`sirket`/`departman`/`NULL` × `kullanici`/`yonetici` × üyelikli/üyeliksiz), güvenli routing (`?departmanId=` ile cross-tenant/geçersiz id fail-safe), güvenli belge listeleme/açma (`BelgeIndir` id tahminiyle atlanamıyor), izin verme/kaldırma (cross-tenant çift hiçbir satırı etkilemiyor), belge metadata değişikliği (`belgeler`+`parcalar` atomik senkron), departman CRUD güvenliği (silme FK koruması, cross-tenant id'ler hiçbir işlemi etkilemiyor).

## RAG Kaynak İzlenebilirliği (Source / Provenance) — P1: DB temeli

`migrations/003_mesaj_kaynaklari.sql` — sadece SEMA, henüz hiçbir uygulama kodu (`sorgu.py`/`servis.py`/`Index.cshtml(.cs)`) bu tabloyu KULLANMIYOR.

- `mesaj_kaynaklari` (`mesaj_id`, `belge_id`, PK ikili) — bir asistan mesajına RAG bağlamında hangi belge(ler)in sağlandığını tutar, çok-çok. FK `mesaj_id→mesajlar.id` ve `belge_id→belgeler.id` ikisi de ON DELETE CASCADE — bir mesaj silinince kaynak satırları, bir belge silinince o belgeye ait kaynak satırları otomatik temizlenir (silinen belge geçmiş provenance'da "donuk isim/stale link" olarak KALMAZ).
- **Bilinçli tasarım kararı:** `dosya_adi`/`dosya_yolu` burada TUTULMAZ, sadece `belge_id` ilişkisi saklanır. Kullanıcının departman üyeliği sohbetten SONRA değişebileceği için, dosya adı "donuk" bir kopya olarak saklansaydı eski bir sohbet açıldığında kullanıcı ARTIK erişimi olmayan bir belgenin adını görebilirdi. Bunun yerine dosya adı/erişilebilirlik HER RENDER'DA GÜNCEL yetkilendirme kurallarıyla (bkz. yukarıdaki "Erişim kontrolü") çözülecek — erişim sonradan iptal edilmişse kaynak o an gösterilmeyecek.
- Mevcut mesajlar için backfill YAPILMADI — eski cevaplar sıfır kaynak satırına sahip. Uygulama entegrasyonu (yazma/render/yetkilendirme sorgusu) HENÜZ yapılmadı, ayrı bir adımda gelecek.
