using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize]
public class BelgeIndirModel : PageModel
{
    public IActionResult OnGet(long id)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        var kullaniciIdClaim = User.FindFirst("kullanici_id");
        if (kullaniciIdClaim == null)
        {
            return RedirectToPage("/Cikis");
        }
        var kullaniciId = long.Parse(kullaniciIdClaim.Value);
        var rol = User.FindFirst(ClaimTypes.Role)!.Value;

        string? dosyaAdi = null;
        string? dosyaYolu = null;

        // Ayni yetkilendirme predikati Belgeler.cshtml.cs liste sorgusuyla
        // AYNI - id + tenant_id tek basina YETERSIZ (bir belge id'sini
        // bilmek/tahmin etmek liste kisitini ATLAMAMALI). Satir donmezse
        // (yok / baska tenant / yetkisiz) asagida tek tip NotFound() doner -
        // hangi sebepten reddedildigi ACIKLANMAZ.
        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(
            @"select b.dosya_adi, b.dosya_yolu
              from belgeler b
              where b.id = @id and b.tenant_id = @t
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
              )", baglanti))
        {
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("rol", rol);
            komut.Parameters.AddWithValue("kid", kullaniciId);

            using var okuyucu = komut.ExecuteReader();
            if (okuyucu.Read())
            {
                dosyaAdi = okuyucu.GetString(0);
                dosyaYolu = okuyucu.IsDBNull(1) ? null : okuyucu.GetString(1);
            }
        }

        if (dosyaYolu == null || !System.IO.File.Exists(dosyaYolu))
        {
            return NotFound();
        }

        return PhysicalFile(dosyaYolu, "application/pdf", dosyaAdi);
    }
}
