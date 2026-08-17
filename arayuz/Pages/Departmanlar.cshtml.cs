using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize(Roles = "yonetici")]
public class DepartmanlarModel : PageModel
{
    [BindProperty]
    public string YeniAd { get; set; } = "";

    public string? Hata { get; set; }

    public record Departman(long Id, string Ad);
    public List<Departman> Liste { get; set; } = new();

    public void OnGet()
    {
        Yukle();
    }

    private void Yukle()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        const string SQL = "select id, ad from departmanlar where tenant_id = @t order by ad";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Liste.Add(new Departman(okuyucu.GetInt64(0), okuyucu.GetString(1)));
        }
    }

    public IActionResult OnPostEkle()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;
        var ad = (YeniAd ?? "").Trim();

        if (ad.Length == 0)
        {
            Hata = "Departman adı boş olamaz.";
            Yukle();
            return Page();
        }

        using var baglanti = Db.Baglan();
        try
        {
            using var komut = new NpgsqlCommand(
                "insert into departmanlar (tenant_id, ad) values (@t, @ad)", baglanti);
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("ad", ad);
            komut.ExecuteNonQuery();
        }
        catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.UniqueViolation)
        {
            // UNIQUE(tenant_id, ad) (bkz. migrations/001_departmanlar.sql) - ayni
            // isim BASKA bir tenant'ta serbestce var olabilir, constraint zaten
            // tenant_id ile BIRLIKTE tanimli, burada ayrica kontrol GEREKMEZ.
            Hata = "Bu isimde bir departman zaten var.";
            Yukle();
            return Page();
        }

        return RedirectToPage();
    }

    public IActionResult OnPostYenidenAdlandir(long id, string ad)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;
        var yeniAd = (ad ?? "").Trim();

        if (yeniAd.Length == 0)
        {
            Hata = "Departman adı boş olamaz.";
            Yukle();
            return Page();
        }

        using var baglanti = Db.Baglan();
        int etkilenenSatir;
        try
        {
            using var komut = new NpgsqlCommand(
                "update departmanlar set ad = @ad where id = @id and tenant_id = @t", baglanti);
            komut.Parameters.AddWithValue("ad", yeniAd);
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);
            etkilenenSatir = komut.ExecuteNonQuery();
        }
        catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.UniqueViolation)
        {
            Hata = "Bu isimde bir departman zaten var.";
            Yukle();
            return Page();
        }

        // id + tenant_id BIRLIKTE eslesmediyse (baska tenant'a ait ya da hic
        // yok) UPDATE 0 satir etkiler - hangisi oldugunu AYIRT ETMEDEN genel
        // bir hata gosterilir, cross-tenant bilgi SIZDIRILMAZ.
        if (etkilenenSatir == 0)
        {
            Hata = "Departman bulunamadı.";
            Yukle();
            return Page();
        }

        return RedirectToPage();
    }

    public IActionResult OnPostSil(long id)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();
        int etkilenenSatir;
        try
        {
            using var komut = new NpgsqlCommand(
                "delete from departmanlar where id = @id and tenant_id = @t", baglanti);
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);
            etkilenenSatir = komut.ExecuteNonQuery();
        }
        catch (PostgresException ex) when (ex.SqlState == PostgresErrorCodes.ForeignKeyViolation)
        {
            // belgeler.departman_id -> departmanlar.id FK'si (ON DELETE
            // CLAUSE YOK, varsayilan NO ACTION) - baglantili belge varsa
            // Postgres silmeyi burada REDDEDER, bilgi/parca ASLA sessizce
            // silinmez. kullanici_departmanlari zaten ON DELETE CASCADE
            // (bkz. migrations/002) - departman GERCEKTEN silinebiliyorsa
            // ayri bir manuel temizlik GEREKMEZ.
            Hata = "Bu departmana bağlı belgeler var. Silmeden önce bu belgeleri başka bir departmana taşıyın veya silin.";
            Yukle();
            return Page();
        }

        // id + tenant_id BIRLIKTE eslesmediyse (baska tenant'a ait ya da hic
        // yok) DELETE 0 satir etkiler - YenidenAdlandir ile AYNI gerekce,
        // cross-tenant bilgi SIZDIRILMAZ.
        if (etkilenenSatir == 0)
        {
            Hata = "Departman bulunamadı.";
            Yukle();
            return Page();
        }

        return RedirectToPage();
    }
}
