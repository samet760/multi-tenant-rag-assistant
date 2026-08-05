using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize(Roles = "yonetici")]
public class LogoModel : PageModel
{
    private static readonly string[] IzinliUzantilar = { ".png", ".jpg", ".jpeg", ".webp" };
    private const long MaksimumBoyut = 2 * 1024 * 1024;

    [BindProperty]
    public IFormFile? Dosya { get; set; }

    public string? Mesaj { get; set; }
    public string? MevcutLogo { get; set; }

    public void OnGet()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand("select logo_url from tenantlar where id = @t", baglanti);
        komut.Parameters.AddWithValue("t", tenant);
        var sonuc = komut.ExecuteScalar();
        MevcutLogo = sonuc == null || sonuc == DBNull.Value ? null : (string)sonuc;
    }

    public async Task OnPostAsync()
    {
        if (Dosya == null || Dosya.Length == 0)
        {
            Mesaj = "Dosya seçilmedi.";
            return;
        }

        var uzanti = Path.GetExtension(Dosya.FileName).ToLowerInvariant();
        if (!IzinliUzantilar.Contains(uzanti))
        {
            Mesaj = "Sadece png, jpg veya webp yüklenebilir.";
            return;
        }

        if (Dosya.Length > MaksimumBoyut)
        {
            Mesaj = "Dosya 2 MB'ı aşamaz.";
            return;
        }

        var tenant = User.FindFirst("tenant_id")!.Value;

        var klasor = Path.Combine(Directory.GetCurrentDirectory(), "wwwroot", "logolar");
        Directory.CreateDirectory(klasor);

        var dosyaAdi = tenant + uzanti;
        var yol = Path.Combine(klasor, dosyaAdi);

        using (var akis = new FileStream(yol, FileMode.Create))
        {
            await Dosya.CopyToAsync(akis);
        }

        var url = $"/logolar/{dosyaAdi}";

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand("update tenantlar set logo_url = @u where id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("u", url);
            komut.Parameters.AddWithValue("t", tenant);
            komut.ExecuteNonQuery();
        }

        Mesaj = "Logo yüklendi.";
        MevcutLogo = url;
    }
}
