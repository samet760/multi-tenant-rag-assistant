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

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(
            "select sifre_ozeti, tenant_id from kullanicilar where eposta = @e", baglanti))
        {
            komut.Parameters.AddWithValue("e", Eposta);
            using var okuyucu = komut.ExecuteReader();
            if (okuyucu.Read())
            {
                ozet = okuyucu.GetString(0);
                tenantId = okuyucu.GetString(1);
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
            new Claim("tenant_id", tenantId!)
        };

        var kimlik = new ClaimsIdentity(claimler, "Cerez");
        await HttpContext.SignInAsync("Cerez", new ClaimsPrincipal(kimlik));

        return RedirectToPage("/Index");
    }
}