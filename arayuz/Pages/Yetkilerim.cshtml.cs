using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize]
public class YetkilerimModel : PageModel
{
    public record Departman(long Id, string Ad);

    public string? Rol { get; set; }
    public List<Departman> Departmanlar { get; set; } = new();

    public IActionResult OnGet()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        // "kullanici_id" claim'i sadece erisim kontrolu C1'de eklendi -
        // ondan once acilmis oturumlarda bulunmaz (bkz. Belgeler/BelgeIndir
        // ayni desen). Uydurulmus bir kimlikle devam ETMEK YERINE kullanici
        // yeniden giris yapmaya zorlanir.
        var kullaniciIdClaim = User.FindFirst("kullanici_id");
        if (kullaniciIdClaim == null)
        {
            return RedirectToPage("/Cikis");
        }
        var kullaniciId = long.Parse(kullaniciIdClaim.Value);
        Rol = User.FindFirst(ClaimTypes.Role)!.Value;

        if (Rol == "yonetici")
        {
            // Yonetici membership'ten BAGIMSIZ tum departman erisimine
            // sahip (bkz. Belgeler/sorgu.py yetkilendirme predikati -
            // rol='yonetici' EXISTS kontrolunu tamamen atlar) - uyelik
            // sorgusu bu kullanici icin ANLAMSIZ, hic calistirilmaz.
            return Page();
        }

        // Sadece OTURUM ACMIS kullanicinin KENDI uyelikleri - hem kullanici
        // (kd.kullanici_id = @kid, baska bir id'ye asla genisletilmez) HEM
        // departman (d.tenant_id = @t) HEM kullanicinin kendisi (k.tenant_id
        // = @t) bu tenant'a ait oldugu AYNI sorguda ispatlanir.
        const string SQL = @"
            select d.id, d.ad
            from kullanici_departmanlari kd
            join kullanicilar k on k.id = kd.kullanici_id
            join departmanlar d on d.id = kd.departman_id
            where kd.kullanici_id = @kid
              and k.tenant_id = @t
              and d.tenant_id = @t
            order by d.ad";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("kid", kullaniciId);
        komut.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Departmanlar.Add(new Departman(okuyucu.GetInt64(0), okuyucu.GetString(1)));
        }

        return Page();
    }
}
