using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

public class KayitModel : PageModel
{
    [BindProperty]
    public string Eposta { get; set; } = "";

    [BindProperty]
    public string SifreMetni { get; set; } = "";

    [BindProperty]
    public string TenantId { get; set; } = "";

    public string Mesaj { get; set; } = "";

    public record Tenant(string Id, string Ad);

    public List<Tenant> Tenantlar { get; set; } = new();

    private void TenantlariYukle()
    {
        Tenantlar.Clear();

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand("select id, ad from tenantlar order by ad", baglanti);
        using var okuyucu = komut.ExecuteReader();

        while (okuyucu.Read())
        {
            Tenantlar.Add(new Tenant(okuyucu.GetString(0), okuyucu.GetString(1)));
        }
    }

    public void OnGet()
    {
        TenantlariYukle();
    }

    public void OnPost()
    {
        if (string.IsNullOrWhiteSpace(Eposta) || string.IsNullOrWhiteSpace(SifreMetni))
        {
            Mesaj = "E-posta ve şifre boş olamaz.";
            TenantlariYukle();
            return;
        }

        string ozet = Sifre.Ozetle(SifreMetni);

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(
            "insert into kullanicilar (eposta, sifre_ozeti, tenant_id) values (@e, @o, @t)",
            baglanti);
        komut.Parameters.AddWithValue("e", Eposta);
        komut.Parameters.AddWithValue("o", ozet);
        komut.Parameters.AddWithValue("t", TenantId);

        try
        {
            komut.ExecuteNonQuery();
            Mesaj = "Kayıt başarılı.";
        }
        catch (PostgresException hata) when (hata.SqlState == "23505")
        {
            Mesaj = "Bu e-posta zaten kayıtlı.";
        }

        TenantlariYukle();
    }
}