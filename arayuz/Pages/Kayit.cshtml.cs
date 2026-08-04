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

    public void OnPost()
    {
        if (string.IsNullOrWhiteSpace(Eposta) || string.IsNullOrWhiteSpace(SifreMetni))
        {
            Mesaj = "E-posta ve şifre boş olamaz.";
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
    }
}