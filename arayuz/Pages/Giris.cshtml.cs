using System.Security.Claims;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

public class GirisModel : PageModel
{
    [BindProperty]
    public string Eposta { get; set; } = "";

    [BindProperty]
    public string SifreMetni { get; set; } = "";

    public string Mesaj { get; set; } = "";

    public async Task<IActionResult> OnPostAsync()
    {
        string? ozet = null;
        string? tenantId = null;
        string? rol = null;
        string? firmaAdi = null;
        string? logoUrl = null;
        long? kullaniciId = null;

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(
            @"select k.id, k.sifre_ozeti, k.tenant_id, k.rol, t.ad, t.logo_url
              from kullanicilar k
              join tenantlar t on t.id = k.tenant_id
              where k.eposta = @e", baglanti))
        {
            komut.Parameters.AddWithValue("e", Eposta);
            using var okuyucu = komut.ExecuteReader();
            if (okuyucu.Read())
            {
                kullaniciId = okuyucu.GetInt64(0);
                ozet = okuyucu.GetString(1);
                tenantId = okuyucu.GetString(2);
                rol = okuyucu.GetString(3);
                firmaAdi = okuyucu.GetString(4);
                logoUrl = okuyucu.IsDBNull(5) ? null : okuyucu.GetString(5);
            }
        }

        if (ozet == null || !Sifre.Dogrula(SifreMetni, ozet))
        {
            Mesaj = "E-posta veya şifre hatalı.";
            return Page();
        }

        var claimler = new List<Claim>
        {
            new Claim(ClaimTypes.Name, Eposta),
            new Claim("tenant_id", tenantId!),
            new Claim(ClaimTypes.Role, rol!),
            new Claim("firma_adi", firmaAdi!),
            new Claim("kullanici_id", kullaniciId!.Value.ToString())
        };

        if (logoUrl != null)
        {
            claimler.Add(new Claim("logo_url", logoUrl));
        }

        var kimlik = new ClaimsIdentity(claimler, "Cerez", ClaimTypes.Name, ClaimTypes.Role);
        await HttpContext.SignInAsync("Cerez", new ClaimsPrincipal(kimlik));

        return RedirectToPage("/Index");
    }
}