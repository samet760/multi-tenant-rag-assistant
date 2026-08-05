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

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(
            @"select k.sifre_ozeti, k.tenant_id, k.rol, t.ad, t.logo_url
              from kullanicilar k
              join tenantlar t on t.id = k.tenant_id
              where k.eposta = @e", baglanti))
        {
            komut.Parameters.AddWithValue("e", Eposta);
            using var okuyucu = komut.ExecuteReader();
            if (okuyucu.Read())
            {
                ozet = okuyucu.GetString(0);
                tenantId = okuyucu.GetString(1);
                rol = okuyucu.GetString(2);
                firmaAdi = okuyucu.GetString(3);
                logoUrl = okuyucu.IsDBNull(4) ? null : okuyucu.GetString(4);
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
            new Claim("firma_adi", firmaAdi!)
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