using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;
using Microsoft.AspNetCore.Mvc;

namespace arayuz.Pages;

[Authorize]
public class BelgelerModel : PageModel
{
    public record Belge(long Id, string DosyaAdi, DateTime Tarih, long ParcaSayisi);

    public List<Belge> Liste { get; set; } = new();

    public void OnGet()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        const string SQL = @"
            select b.id,
                   b.dosya_adi,
                   b.yukleme_tarihi,
                   (select count(*) from parcalar p where p.belge_id = b.id) as parca_sayisi
            from belgeler b
            where b.tenant_id = @t
            order by b.yukleme_tarihi desc";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Liste.Add(new Belge(
                okuyucu.GetInt64(0),
                okuyucu.GetString(1),
                okuyucu.GetDateTime(2),
                okuyucu.GetInt64(3)
            ));
        }
    }
    [Authorize(Roles = "yonetici")]
    public IActionResult OnPostSil(long id)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        const string SQL = "delete from belgeler where id = @id and tenant_id = @t";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("id", id);
        komut.Parameters.AddWithValue("t", tenant);
        komut.ExecuteNonQuery();

        return RedirectToPage();
    }
}