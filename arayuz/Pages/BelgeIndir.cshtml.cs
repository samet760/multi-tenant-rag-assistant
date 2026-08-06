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

        string? dosyaAdi = null;
        string? dosyaYolu = null;

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(
            "select dosya_adi, dosya_yolu from belgeler where id = @id and tenant_id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);

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
