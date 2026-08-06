using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;
using Microsoft.AspNetCore.Mvc;

namespace arayuz.Pages;

[Authorize]
public class BelgelerModel : PageModel
{
    public record Belge(long Id, string DosyaAdi, DateTime Tarih, long ParcaSayisi, string? DosyaYolu);

    public List<Belge> Liste { get; set; } = new();

    [BindProperty(SupportsGet = true)]
    public string? Ara { get; set; }

    public void OnGet()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        var sql = @"
            select b.id,
                   b.dosya_adi,
                   b.yukleme_tarihi,
                   (select count(*) from parcalar p where p.belge_id = b.id) as parca_sayisi,
                   b.dosya_yolu
            from belgeler b
            where b.tenant_id = @t";

        if (!string.IsNullOrWhiteSpace(Ara))
        {
            sql += " and dosya_adi ilike @ara";
        }

        sql += " order by b.yukleme_tarihi desc";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(sql, baglanti);
        komut.Parameters.AddWithValue("t", tenant);

        if (!string.IsNullOrWhiteSpace(Ara))
        {
            komut.Parameters.AddWithValue("ara", "%" + Ara + "%");
        }

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Liste.Add(new Belge(
                okuyucu.GetInt64(0),
                okuyucu.GetString(1),
                okuyucu.GetDateTime(2),
                okuyucu.GetInt64(3),
                okuyucu.IsDBNull(4) ? null : okuyucu.GetString(4)
            ));
        }
    }
    [Authorize(Roles = "yonetici")]
    public IActionResult OnPostSil(long id)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();

        string? dosyaYolu;
        using (var komut = new NpgsqlCommand(
            "select dosya_yolu from belgeler where id = @id and tenant_id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);
            var sonuc = komut.ExecuteScalar();
            dosyaYolu = sonuc == null || sonuc == DBNull.Value ? null : (string)sonuc;
        }

        using (var komut = new NpgsqlCommand(
            "delete from belgeler where id = @id and tenant_id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("id", id);
            komut.Parameters.AddWithValue("t", tenant);
            komut.ExecuteNonQuery();
        }

        if (dosyaYolu != null && System.IO.File.Exists(dosyaYolu))
        {
            System.IO.File.Delete(dosyaYolu);
        }

        return RedirectToPage();
    }
}