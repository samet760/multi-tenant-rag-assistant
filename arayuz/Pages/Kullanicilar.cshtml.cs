using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize(Roles = "yonetici")]
public class KullanicilarModel : PageModel
{
    public record Kullanici(long Id, string Eposta, string Rol);

    public List<Kullanici> Liste { get; set; } = new();
    public bool Sahip { get; set; }
    public string? SahipEposta { get; set; }

    public void OnGet()
    {
        Yukle();
    }

    private void Yukle()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;

        using var baglanti = Db.Baglan();

        using (var komut = new NpgsqlCommand("select sahip_eposta from tenantlar where id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("t", tenant);
            var sonuc = komut.ExecuteScalar();
            SahipEposta = sonuc == null || sonuc == DBNull.Value ? null : (string)sonuc;
        }

        Sahip = SahipEposta != null && SahipEposta == eposta;

        const string SQL = "select id, eposta, rol from kullanicilar where tenant_id = @t order by eposta";

        using var komut2 = new NpgsqlCommand(SQL, baglanti);
        komut2.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut2.ExecuteReader();
        while (okuyucu.Read())
        {
            Liste.Add(new Kullanici(
                okuyucu.GetInt64(0),
                okuyucu.GetString(1),
                okuyucu.GetString(2)
            ));
        }
    }

    public IActionResult OnPostYukselt(long id)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        const string SQL = "update kullanicilar set rol = 'yonetici' where id = @id and tenant_id = @t and rol = 'kullanici'";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("id", id);
        komut.Parameters.AddWithValue("t", tenant);
        komut.ExecuteNonQuery();

        return RedirectToPage();
    }

    public IActionResult OnPostDusur(long id)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;

        using var baglanti = Db.Baglan();

        string? sahipEposta;
        using (var komut = new NpgsqlCommand("select sahip_eposta from tenantlar where id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("t", tenant);
            var sonuc = komut.ExecuteScalar();
            sahipEposta = sonuc == null || sonuc == DBNull.Value ? null : (string)sonuc;
        }

        if (sahipEposta == null || sahipEposta != eposta)
        {
            return RedirectToPage();
        }

        const string SQL = @"
            update kullanicilar set rol = 'kullanici'
            where id = @id and tenant_id = @t and rol = 'yonetici' and eposta <> @sahipEposta";

        using var komut2 = new NpgsqlCommand(SQL, baglanti);
        komut2.Parameters.AddWithValue("id", id);
        komut2.Parameters.AddWithValue("t", tenant);
        komut2.Parameters.AddWithValue("sahipEposta", sahipEposta);
        komut2.ExecuteNonQuery();

        return RedirectToPage();
    }
}
