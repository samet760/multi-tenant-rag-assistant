using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Text.Json;

namespace arayuz.Pages;

[Microsoft.AspNetCore.Authorization.Authorize]
public class IndexModel : PageModel
{
    public const int SoruMaksUzunluk = 4000;
    public const int SohbetBaslikMaksUzunluk = 100;

    [BindProperty]
    public string Soru { get; set; } = "";

    [BindProperty(SupportsGet = true)]
    public long? SohbetId { get; set; }

    // Normal sohbette manuel departman secimi YOK (bkz. gorev talimati) -
    // her soru HER ZAMAN otomatik yonlendirme modunda gonderilir (bkz.
    // sorgu.py::departman_yonlendir). Bu sadece EN SON sorunun otomatik
    // yonlendirildigi departmani tutar - SALT gorsel etiket icin (bkz.
    // GosterilenDepartmanEtiketi), FastAPI'ye giden istegi HICBIR SEKILDE
    // ETKILEMEZ - bir sonraki soru yine sifirdan/BAGIMSIZ otomatik
    // yonlendirilir, burada gosterilen deger bir SONRAKI istegi kisitlamaz.
    // Composer'daki gizli alandan (POST'ta OnPostAsync gorulmez, sadece
    // uzerine yazilir) veya URL'den (GET/redirect sonrasi sayfa yeniden
    // yuklendiginde) baglanir - SohbetId ile AYNI ikili baglama deseni.
    [BindProperty(SupportsGet = true)]
    public long? SonKullanilanDepartmanId { get; set; }

    public string Cevap { get; set; } = "";

    public string? Hata { get; set; }

    // belge_id/dosya_adi: hem FastAPI'nin /sor yanitindaki "kaynaklar"
    // dizisiyle (bkz. SorguYaniti) HEM mesaj gecmisi yeniden yuklenirken
    // (bkz. MesajlariYukle) AYNI sekle - Python tarafiyla birebir ayni alan
    // adlari, ekstra JSON eslestirme secenegi GEREKMEZ.
    public record Kaynak(long belge_id, string? dosya_adi);

    public record Mesaj(string Rol, string Metin, double? Skor, List<Kaynak> Kaynaklar);
    public List<Mesaj> Mesajlar { get; set; } = new();

    public record Departman(long Id, string Ad);
    public List<Departman> Departmanlar { get; set; } = new();

    // RAG V2 CHECKPOINT 3 (kisa konusma hafizasi): FastAPI'ye gonderilen
    // gecmis mesaj sekli - servis.py::GecmisMesaj ile alan alan AYNI
    // (mesaj_rolu/metin, snake_case), ekstra bir .Select() esleme adimi
    // GEREKMEZ (bkz. Kaynak ayni desen).
    public record OncekiMesaj(string mesaj_rolu, string metin);

    public IActionResult OnGet()
    {
        DepartmanlariYukle();

        if (SohbetId != null)
        {
            // "kullanici_id" claim'i SADECE C1'de eklendi - MesajlariYukle
            // artik GUNCEL yetkilendirmeyi uygulamak icin bu kimlige
            // ihtiyac duyuyor (bkz. asagisi). Taze/bos sohbet (SohbetId ==
            // null) icin bu kontrole HIC gerek yok - sadece GECMIS acilirken
            // zorlanir, OnPostAsync'teki AYNI desen.
            var kullaniciIdClaim = User.FindFirst("kullanici_id");
            if (kullaniciIdClaim == null)
            {
                return RedirectToPage("/Cikis");
            }
            var kullaniciId = long.Parse(kullaniciIdClaim.Value);
            var rol = User.FindFirst(ClaimTypes.Role)!.Value;

            MesajlariYukle(kullaniciId, rol);
        }

        return Page();
    }

    // Sag-ust departman secicisini doldurur - GET'te ve POST'ta (basarili/
    // basarisiz her durumda sayfa yeniden render edilecegi icin) cagrilir,
    // arayuz/Pages/Yukle.cshtml.cs::DepartmanlariYukle ile AYNI desen.
    private void DepartmanlariYukle()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(
            "select id, ad from departmanlar where tenant_id = @t order by ad", baglanti);
        komut.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Departmanlar.Add(new Departman(okuyucu.GetInt64(0), okuyucu.GetString(1)));
        }
    }

    // Ust-baslikta gosterilecek metin - SALT OKUNUR/goruntuleme amacli (bkz.
    // gorev talimati: "OUTPUT/display state only, not an input constraint").
    // - En son soru bir departmana otomatik yonlendirilmisse: o departmanin
    //   adi.
    // - Hicbiri yoksa (taze sohbet / henuz yonlendirme olmadi): "Genel Asistan".
    public string GosterilenDepartmanEtiketi()
    {
        if (SonKullanilanDepartmanId == null)
        {
            return "Genel Asistan";
        }

        return Departmanlar.FirstOrDefault(d => d.Id == SonKullanilanDepartmanId.Value)?.Ad ?? "Genel Asistan";
    }

    private void MesajlariYukle(long kullaniciId, string rol)
    {
        if (SohbetId == null) return;

        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;

        // Kaynaklar KALICI bir "o an neydi" kopyasi DEGIL - mesaj_kaynaklari
        // sadece mesaj<->belge ILISKISINI tutar (bkz. migrations/003), dosya
        // adi/gorunurluk HER render'da GUNCEL yetkilendirme kurallariyla
        // (Belgeler/BelgeIndir'deki AYNI predikat) burada, TEK sorguda
        // yeniden cozulur - N+1 YOK, korelasyonlu alt sorgu her mesaj satiri
        // icin ayri bir .NET->DB gidis-donusu GEREKTIRMEZ. Uyelik sonradan
        // iptal edilirse bu kaynak bir daha DONMEZ; geri verilirse iliski
        // hala var oldugu icin tekrar GORUNUR.
        const string SQL = @"
            select m.id,
                   m.rol,
                   m.metin,
                   m.skor,
                   coalesce((
                       select json_agg(json_build_object('belge_id', b.id, 'dosya_adi', b.dosya_adi) order by mk.belge_id)
                       from mesaj_kaynaklari mk
                       join belgeler b on b.id = mk.belge_id
                       where mk.mesaj_id = m.id
                         and b.tenant_id = @t
                         and (
                             b.erisim_seviyesi = 'sirket'
                             or (
                                 b.erisim_seviyesi = 'departman'
                                 and b.departman_id is not null
                                 and (
                                     @rol = 'yonetici'
                                     or exists (
                                         select 1 from kullanici_departmanlari kd
                                         where kd.kullanici_id = @kid and kd.departman_id = b.departman_id
                                     )
                                 )
                             )
                         )
                   ), '[]') as kaynaklar_json
            from mesajlar m
            join sohbetler s on s.id = m.sohbet_id
            where m.sohbet_id = @s and s.tenant_id = @t and s.eposta = @e
            order by m.id";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("s", SohbetId.Value);
        komut.Parameters.AddWithValue("t", tenant);
        komut.Parameters.AddWithValue("e", eposta!);
        komut.Parameters.AddWithValue("rol", rol);
        komut.Parameters.AddWithValue("kid", kullaniciId);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            var kaynaklarJson = okuyucu.GetString(4);
            var kaynaklar = JsonSerializer.Deserialize<List<Kaynak>>(kaynaklarJson) ?? new();

            Mesajlar.Add(new Mesaj(
                okuyucu.GetString(1),
                okuyucu.GetString(2),
                okuyucu.IsDBNull(3) ? null : okuyucu.GetDouble(3),
                kaynaklar
            ));
        }
    }

    // RAG V2 CHECKPOINT 3 (kisa konusma hafizasi): AYNI sohbet+tenant+eposta
    // sahiplik kontrolu - MesajlariYukle/OnPostSohbetSil ile BIREBIR AYNI
    // desen, baska bir kullanicinin/tenant'in/sohbetin mesaji ASLA sizmaz.
    // Cagrildiginda SohbetId != null GARANTI (bkz. cagiran) - taze/ilk soru
    // icin bu metot HIC CAGRILMAZ, ekstra sorgu ATILMAZ. Yeni soru bu nokta
    // itibariyle HENUZ mesajlar tablosuna YAZILMADI (INSERT'ler OnPostAsync'te
    // /sor cagrisindan SONRA yapiliyor) - bu yuzden "onceki 2 mesaj" hicbir
    // ekstra filtreye gerek kalmadan mevcut soruyu asla ICERMEZ.
    private List<OncekiMesaj> OncekiMesajlariGetir(string tenant, string eposta)
    {
        const string SQL = @"
            select m.rol, m.metin
            from mesajlar m
            join sohbetler s on s.id = m.sohbet_id
            where m.sohbet_id = @s and s.tenant_id = @t and s.eposta = @e
            order by m.id desc
            limit 2";

        var liste = new List<OncekiMesaj>();
        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("s", SohbetId!.Value);
        komut.Parameters.AddWithValue("t", tenant);
        komut.Parameters.AddWithValue("e", eposta);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            liste.Add(new OncekiMesaj(okuyucu.GetString(0), okuyucu.GetString(1)));
        }

        // DESC ile cekildi (en yeni ONCE) - kronolojik siraya (en eski ONCE)
        // CEVIR, LLM'e "ONCEKI SORU -> ONCEKI CEVAP" akisinda gitsin diye.
        liste.Reverse();
        return liste;
    }

    public async Task<IActionResult> OnPostAsync()
    {
        DepartmanlariYukle();

        if (string.IsNullOrWhiteSpace(Soru))
        {
            return Page();
        }

        if (Soru.Length > SoruMaksUzunluk)
        {
            Hata = $"Soru en fazla {SoruMaksUzunluk} karakter olabilir.";
            return Page();
        }

        var tenant = User.FindFirst("tenant_id")!.Value;

        // "kullanici_id" claim'i SADECE C1'de eklendi - C1'den ONCE acilmis
        // oturumlarda bulunmaz. Uydurulmus/varsayilan bir kimlikle devam
        // ETMEK YERINE (gorev talimati) kullanici yeniden giris yapmaya
        // zorlanir - Cikis sayfasi mevcut cerezi temizler.
        var kullaniciIdClaim = User.FindFirst("kullanici_id");
        if (kullaniciIdClaim == null)
        {
            return RedirectToPage("/Cikis");
        }
        var kullaniciId = long.Parse(kullaniciIdClaim.Value);
        var rol = User.FindFirst(ClaimTypes.Role)!.Value;

        var istemci = new HttpClient();
        var eposta = User.Identity!.Name;

        // RAG V2 CHECKPOINT 3 (kisa konusma hafizasi): SADECE mevcut bir
        // sohbette (SohbetId != null) ve GERCEKTEN onceki mesaj VARSA
        // gonderilir - taze/ilk soru icin bu HER ZAMAN null kalir, ekstra
        // sorgu/LLM cagrisi/davranis degisikligi OLMAZ (bkz. gorev talimati
        // "no history / first question -> current behavior exactly as
        // today").
        List<OncekiMesaj>? gecmis = null;
        if (SohbetId != null)
        {
            var oncekiMesajlar = OncekiMesajlariGetir(tenant, eposta!);
            if (oncekiMesajlar.Count > 0)
            {
                gecmis = oncekiMesajlar;
            }
        }

        // departman_id her zaman null gonderilir - normal sohbette manuel
        // secim YOK, her soru sorgu.py::departman_yonlendir uzerinden
        // BAGIMSIZ/sifirdan otomatik yonlendirilir (bkz. gorev talimati).
        var govde = new { soru = Soru, tenant_id = tenant, departman_id = (long?)null, kullanici_id = kullaniciId, rol, gecmis };

        SorguYaniti? sonuc = null;
        try
        {
            var yanit = await istemci.PostAsJsonAsync("http://127.0.0.1:8000/sor", govde);

            if (!yanit.IsSuccessStatusCode)
            {
                // FastAPI 500/502 gibi basarisiz durum kodu dondurdu - govde
                // "Internal Server Error" gibi duz metin olabilir, JSON
                // deserialize HIC denenmez.
                Cevap = "Yanıt oluşturulurken bir servis hatası oluştu. Lütfen tekrar deneyin.";
            }
            else
            {
                var govdeMetni = await yanit.Content.ReadAsStringAsync();
                try
                {
                    sonuc = JsonSerializer.Deserialize<SorguYaniti>(govdeMetni);
                }
                catch (JsonException)
                {
                    // 200 dondu ama govde gecerli JSON degil - sadece bu
                    // deserialize hatasi yutulur, sayfa CRASH etmez.
                    sonuc = null;
                }

                Cevap = sonuc?.cevap ?? "Yanıt oluşturulurken bir servis hatası oluştu. Lütfen tekrar deneyin.";

                // Yanitin GERCEKTEN yonlendirildigi departman SALT gorsel
                // etikete yansir (bkz. GosterilenDepartmanEtiketi) - bir
                // sonraki soru bundan ETKILENMEZ, yine sifirdan otomatik
                // yonlendirilir.
                SonKullanilanDepartmanId = sonuc?.departman_id;
            }
        }
        catch (Exception ex) when (ex is TimeoutException ||
            (ex is TaskCanceledException tce && tce.InnerException is TimeoutException))
        {
            // HttpClient'in kendi (varsayilan 100s) suresi doldugunda TaskCanceledException
            // firlatir ve InnerException TimeoutException olur - bu ikisi DISINDA baska
            // bir TaskCanceledException (orn. istemci baglantiyi kesti) burada YUTULMAZ,
            // filtreye takilmadigi icin normal sekilde yukari firlar.
            Cevap = "İstek zaman aşımına uğradı. Lütfen daha kısa veya daha net bir soru deneyin.";
        }

        using var baglanti = Db.Baglan();

        if (SohbetId == null)
        {
            const string SQL_SOHBET = @"
                insert into sohbetler (tenant_id, eposta, baslik)
                values (@t, @e, @b) returning id";

            var baslik = Soru.Length > 50 ? Soru.Substring(0, 50) : Soru;

            using var komut = new NpgsqlCommand(SQL_SOHBET, baglanti);
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("e", eposta!);
            komut.Parameters.AddWithValue("b", baslik);

            SohbetId = (long)komut.ExecuteScalar()!;
        }

        const string SQL_MESAJ = "insert into mesajlar (sohbet_id, rol, metin, skor) values (@s, @r, @m, @sk)";

        using (var komut = new NpgsqlCommand(SQL_MESAJ, baglanti))
        {
            komut.Parameters.AddWithValue("s", SohbetId.Value);
            komut.Parameters.AddWithValue("r", "soru");
            komut.Parameters.AddWithValue("m", Soru);
            komut.Parameters.AddWithValue("sk", DBNull.Value);
            komut.ExecuteNonQuery();
        }

        // Cevap mesaji + kaynak iliskileri AYNI transaction icinde: biri
        // basarisiz olursa digeri de geri alinir, mesaj asla kaynaksiz-yarim
        // bir durumda KALMAZ (bkz. gorev talimati "atomic where practical").
        using (var islem = baglanti.BeginTransaction())
        {
            long cevapMesajId;
            const string SQL_MESAJ_CEVAP = "insert into mesajlar (sohbet_id, rol, metin, skor) values (@s, @r, @m, @sk) returning id";

            using (var komut = new NpgsqlCommand(SQL_MESAJ_CEVAP, baglanti, islem))
            {
                komut.Parameters.AddWithValue("s", SohbetId.Value);
                komut.Parameters.AddWithValue("r", "cevap");
                komut.Parameters.AddWithValue("m", Cevap);
                komut.Parameters.AddWithValue("sk", (object?)sonuc?.skor ?? DBNull.Value);
                cevapMesajId = (long)komut.ExecuteScalar()!;
            }

            // FastAPI'nin dondurdugu belge_id'lere DOGRUDAN guvenilmez -
            // dosya_adi BURADA hic okunmaz/saklanmaz (bkz. Kaynak/gorev
            // talimati), sadece belge_id'ler bu tenant'a GERCEKTEN ait
            // belgeler.id'lerine karsilik geliyorsa iliskilendirilir (tek
            // INSERT...SELECT, ayri bir "belge var mi" round trip'i YOK -
            // Belgeler/BelgeDuzenle'deki AYNI "ownership'i sorgunun kendi
            // WHERE'inde ispatla" deseni). Arada silinmis bir belge varsa o
            // id icin satir uretilmez, hata da FIRLATMAZ.
            var belgeIdler = sonuc?.kaynaklar?.Select(k => k.belge_id).Distinct().ToArray() ?? Array.Empty<long>();
            if (belgeIdler.Length > 0)
            {
                const string SQL_KAYNAK = @"
                    insert into mesaj_kaynaklari (mesaj_id, belge_id)
                    select @mesajId, b.id
                    from belgeler b
                    where b.tenant_id = @t and b.id = any(@belgeIdler)";

                using var komut = new NpgsqlCommand(SQL_KAYNAK, baglanti, islem);
                komut.Parameters.AddWithValue("mesajId", cevapMesajId);
                komut.Parameters.AddWithValue("t", tenant);
                komut.Parameters.AddWithValue("belgeIdler", belgeIdler);
                komut.ExecuteNonQuery();
            }

            islem.Commit();
        }

        return RedirectToPage(new { sohbetId = SohbetId, sonKullanilanDepartmanId = SonKullanilanDepartmanId });
    }

    // Sohbet paneli (SohbetPaneliViewComponent) satirindaki "..." menusunden
    // cagrilir - soru sorma OnPostAsync akisindan BILINCLI olarak ayri
    // tutulur (bkz. gorev talimati). Ikisi de senkron (Belgeler.cshtml.cs
    // OnPostSil ile ayni stil): sadece ADO.NET cagrisi, async I/O yok.
    public IActionResult OnPostSohbetYenidenAdlandir(long id, string? yeniBaslik, long? aktifSohbetId)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;

        // Bos/sadece-bosluk isim KAYDEDILMEZ - sunucu tarafi son karar
        // mercii (istemci JS'i zaten bunu Escape/iptal gibi ele aliyor,
        // ama JS kapaliyken veya dogrudan POST'ta da ayni kural gecerli
        // olmali). Sessizce yok sayilir, hata gosterilmez - "adini
        // degistir"den vazgecmis gibi davranilir.
        var baslik = (yeniBaslik ?? "").Trim();
        if (baslik.Length > 0)
        {
            if (baslik.Length > SohbetBaslikMaksUzunluk)
            {
                baslik = baslik.Substring(0, SohbetBaslikMaksUzunluk);
            }

            using var baglanti = Db.Baglan();
            using var komut = new NpgsqlCommand(
                "update sohbetler set baslik = @b where id = @id and tenant_id = @t and eposta = @e", baglanti);
            komut.Parameters.AddWithValue("b", baslik);
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("e", eposta!);
            komut.ExecuteNonQuery();
        }

        // Sohbet ID'si degismedi - aktif sohbet neyse (varsa) ayni sekilde
        // acik kalir, sadece panel yeni basligi gosterir.
        return RedirectToPage(new { sohbetId = aktifSohbetId });
    }

    public IActionResult OnPostSohbetSil(long id, long? aktifSohbetId)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(
            // tenant_id + eposta birlikte SAHIPLIK kontrolu: sohbetler
            // tenant icinde bile kullaniciya OZEL (bkz. MesajlariYukle/
            // SohbetPaneliViewComponent ayni filtre) - id tarayicidan
            // gelse bile baska bir kullanicinin sohbeti silinemez.
            "delete from sohbetler where id = @id and tenant_id = @t and eposta = @e", baglanti))
        {
            // mesajlar.sohbet_id -> sohbetler.id FK'si ON DELETE CASCADE
            // (veritabaninda dogrulandi) - bagli mesajlar burada ayrica
            // silinmeden otomatik temizlenir, yetim mesaj KALMAZ.
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("e", eposta!);
            komut.ExecuteNonQuery();
        }

        // Silinen, o an acik olan sohbetse taze/bos yeni-sohbet durumuna
        // don (sohbetId'siz /Index) - degilse acik sohbet ayni sekilde
        // acik kalir, panelde sadece silinen satir kaybolur.
        var silinenAktifti = aktifSohbetId.HasValue && aktifSohbetId.Value == id;
        return RedirectToPage(new { sohbetId = silinenAktifti ? (long?)null : aktifSohbetId });
    }

    public class SorguYaniti
    {
        public string cevap { get; set; } = "";
        public double? skor { get; set; }

        // Yanit hangi departmanda arandi (elle secilmis ya da Genel Asistan
        // tarafindan otomatik yonlendirilmis) - SADECE gorsel etiket icin
        // kullanilir, bkz. OnPostAsync/GosterilenDepartmanEtiketi.
        public long? departman_id { get; set; }

        // sorgu.py::cevapla'nin LLM'e verdigi (zaten yetkilendirme-filtreli)
        // parcalarin belgeleri (bkz. PROJECT_MAP.md "RAG Kaynak
        // İzlenebilirliği"). dosya_adi burada PARSE edilebilir ama asla
        // KALICI olarak saklanmaz/gecmis render'da guvenilmez - sadece
        // belge_id kalici iliski icin kullanilir (bkz. OnPostAsync).
        public List<Kaynak>? kaynaklar { get; set; }
    }
}
