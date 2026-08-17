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
}
