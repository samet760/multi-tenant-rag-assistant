using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;
using System.Net.Http.Json;

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

    // Composer'daki gizli alandan (POST) veya URL'den (GET/redirect sonrasi
    // sayfa yeniden yuklendiginde, bkz. asagidaki OnPostAsync'in redirect'i)
    // baglanir - SohbetId ile AYNI ikili baglama deseni.
    // null = "✨ Genel Asistan" (departman otomatik secilir, bkz. sorgu.py::
    // departman_yonlendir) - DB'de karsiligi olmayan, sadece bu null durumun
    // adi. Dolu deger = kullanicinin ACIKCA sectigi gercek departman.
    [BindProperty(SupportsGet = true)]
    public long? DepartmanId { get; set; }

    public string Cevap { get; set; } = "";

    public string? Hata { get; set; }

    public record Mesaj(string Rol, string Metin, double? Skor);
    public List<Mesaj> Mesajlar { get; set; } = new();

    public record Departman(long Id, string Ad);
    public List<Departman> Departmanlar { get; set; } = new();

    public void OnGet()
    {
        DepartmanlariYukle();
        MesajlariYukle();
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

    // Secilen departman ID'si GERCEKTEN bu tenant'a mi ait - tarayicidan
    // gelen degere DOGRUDAN guvenilmiyor, DB'de tenant_id ile birlikte
    // dogrulaniyor (Yukle.cshtml.cs::DepartmanGecerliMi ile AYNI desen).
    private bool DepartmanGecerliMi(long departmanId, string tenant)
    {
        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(
            "select 1 from departmanlar where id = @d and tenant_id = @t", baglanti);
        komut.Parameters.AddWithValue("d", departmanId);
        komut.Parameters.AddWithValue("t", tenant);
        return komut.ExecuteScalar() != null;
    }

    private void MesajlariYukle()
    {
        if (SohbetId == null) return;

        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;

        const string SQL = @"
            select m.rol, m.metin, m.skor from mesajlar m
            join sohbetler s on s.id = m.sohbet_id
            where m.sohbet_id = @s and s.tenant_id = @t and s.eposta = @e
            order by m.id";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("s", SohbetId.Value);
        komut.Parameters.AddWithValue("t", tenant);
        komut.Parameters.AddWithValue("e", eposta!);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Mesajlar.Add(new Mesaj(
                okuyucu.GetString(0),
                okuyucu.GetString(1),
                okuyucu.IsDBNull(2) ? null : okuyucu.GetDouble(2)
            ));
        }
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

        // DepartmanId == null artik GECERLI bir secim: "✨ Genel Asistan"
        // (departman Python tarafinda otomatik yonlendirilir). SADECE
        // ACIKCA bir departman secildiyse (null degilse) sahiplik FastAPI
        // cagrilmadan ONCE dogrulanir - gecersiz/baska tenant'a ait bir ID
        // gonderilirse istek HIC gonderilmez, kucuk bir hata gosterilir.
        if (DepartmanId != null && !DepartmanGecerliMi(DepartmanId.Value, tenant))
        {
            Hata = "Lütfen geçerli bir departman seçin.";
            return Page();
        }

        var istemci = new HttpClient();
        var eposta = User.Identity!.Name;
        var govde = new { soru = Soru, tenant_id = tenant, departman_id = DepartmanId };

        SorguYaniti? sonuc = null;
        try
        {
            var yanit = await istemci.PostAsJsonAsync("http://127.0.0.1:8000/sor", govde);
            sonuc = await yanit.Content.ReadFromJsonAsync<SorguYaniti>();
            Cevap = sonuc?.cevap ?? "";
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

        using (var komut = new NpgsqlCommand(SQL_MESAJ, baglanti))
        {
            komut.Parameters.AddWithValue("s", SohbetId.Value);
            komut.Parameters.AddWithValue("r", "cevap");
            komut.Parameters.AddWithValue("m", Cevap);
            komut.Parameters.AddWithValue("sk", (object?)sonuc?.skor ?? DBNull.Value);
            komut.ExecuteNonQuery();
        }

        return RedirectToPage(new { sohbetId = SohbetId, departmanId = DepartmanId });
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
    }
}
