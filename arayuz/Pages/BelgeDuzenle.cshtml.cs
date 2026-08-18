using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize(Roles = "yonetici")]
public class BelgeDuzenleModel : PageModel
{
    public record Departman(long Id, string Ad);

    // Tarayicidan gelen degere DOGRUDAN guvenilmiyor - Yukle.cshtml.cs'teki
    // AYNI kisitlama (migrations/002_erisim_kontrolu.sql CHECK ile birebir).
    private static readonly HashSet<string> GecerliErisimSeviyeleri = new() { "sirket", "departman" };

    [BindProperty(SupportsGet = true)]
    public long Id { get; set; }

    [BindProperty]
    public long? DepartmanId { get; set; }

    [BindProperty]
    public string? ErisimSeviyesi { get; set; }

    public bool Bulundu { get; set; }
    public string? Hata { get; set; }
    public string? DosyaAdi { get; set; }
    public List<Departman> Departmanlar { get; set; } = new();

    public IActionResult OnGet()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();
        DepartmanlariYukle(baglanti, tenant);

        // Belge bu tenant'a mi ait DOGRULANIR - baska tenant'a ait veya var
        // olmayan bir id ise genel "bulunamadi" mesaji gosterilir, hangi
        // durumun gecerli oldugu AYIRT EDILMEZ (Belgeler/Departmanlar'daki
        // ayni desen).
        using var komut = new NpgsqlCommand(
            "select dosya_adi, departman_id, erisim_seviyesi from belgeler where id = @id and tenant_id = @t", baglanti);
        komut.Parameters.AddWithValue("id", Id);
        komut.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut.ExecuteReader();
        if (!okuyucu.Read())
        {
            Hata = "Belge bulunamadı.";
            return Page();
        }

        Bulundu = true;
        DosyaAdi = okuyucu.GetString(0);
        DepartmanId = okuyucu.IsDBNull(1) ? null : okuyucu.GetInt64(1);
        ErisimSeviyesi = okuyucu.IsDBNull(2) ? null : okuyucu.GetString(2);

        return Page();
    }

    public IActionResult OnPost()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();
        DepartmanlariYukle(baglanti, tenant);

        string? dosyaAdi;
        using (var komut = new NpgsqlCommand(
            "select dosya_adi from belgeler where id = @id and tenant_id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("id", Id);
            komut.Parameters.AddWithValue("t", tenant);
            dosyaAdi = komut.ExecuteScalar() as string;
        }

        if (dosyaAdi == null)
        {
            Hata = "Belge bulunamadı.";
            return Page();
        }

        Bulundu = true;
        DosyaAdi = dosyaAdi;

        if (DepartmanId == null)
        {
            Hata = "Lütfen geçerli bir departman seçin.";
            return Page();
        }

        if (ErisimSeviyesi == null || !GecerliErisimSeviyeleri.Contains(ErisimSeviyesi))
        {
            Hata = "Lütfen geçerli bir erişim seviyesi seçin.";
            return Page();
        }

        // belgeler + parcalar metadata ayni transaction icinde guncellenir -
        // biri basarisiz olursa DIGERI de geri alinir, iki tablo asla farkli
        // departman_id/erisim_seviyesi ile YARIM kalmaz.
        using var islem = baglanti.BeginTransaction();
        try
        {
            int etkilenen;
            // UPDATE...FROM ile secilen departmanin GERCEKTEN bu tenant'a ait
            // oldugu AYNI ifade icinde ispatlanir (dep.tenant_id = @t) - ayri
            // bir "departman var mi" round trip'i GEREKMEZ. Belge id + tenant
            // eslesmezse veya departman baska tenant'a aitse 0 satir doner.
            using (var komut = new NpgsqlCommand(@"
                update belgeler b
                set departman_id = @d, erisim_seviyesi = @e
                from departmanlar dep
                where b.id = @id
                  and b.tenant_id = @t
                  and dep.id = @d
                  and dep.tenant_id = @t", baglanti, islem))
            {
                komut.Parameters.AddWithValue("id", Id);
                komut.Parameters.AddWithValue("t", tenant);
                komut.Parameters.AddWithValue("d", DepartmanId.Value);
                komut.Parameters.AddWithValue("e", ErisimSeviyesi);
                etkilenen = komut.ExecuteNonQuery();
            }

            if (etkilenen == 0)
            {
                islem.Rollback();
                Hata = "Belge veya departman bulunamadı.";
                return Page();
            }

            // Belgenin TUM parcalari - vektorler/metin degismiyor, sadece
            // denormalize edilmis departman_id/erisim_seviyesi kopyalari
            // (bkz. PROJECT_MAP.md - retrieval belgeler'e HIC JOIN yapmadan
            // dogrudan parcalar'i filtreliyor). tenant_id ayrica kontrol
            // edilir - belge_id yukarida zaten dogrulandi, bu SADECE ayni
            // savunma-katmani deseni.
            using (var komut = new NpgsqlCommand(
                "update parcalar set departman_id = @d, erisim_seviyesi = @e where belge_id = @id and tenant_id = @t",
                baglanti, islem))
            {
                komut.Parameters.AddWithValue("id", Id);
                komut.Parameters.AddWithValue("t", tenant);
                komut.Parameters.AddWithValue("d", DepartmanId.Value);
                komut.Parameters.AddWithValue("e", ErisimSeviyesi);
                komut.ExecuteNonQuery();
            }

            islem.Commit();
        }
        catch
        {
            islem.Rollback();
            Hata = "Belge güncellenirken bir hata oluştu.";
            return Page();
        }

        return RedirectToPage("/Belgeler", new { departmanId = DepartmanId });
    }

    private void DepartmanlariYukle(NpgsqlConnection baglanti, string tenant)
    {
        using var komut = new NpgsqlCommand(
            "select id, ad from departmanlar where tenant_id = @t order by ad", baglanti);
        komut.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Departmanlar.Add(new Departman(okuyucu.GetInt64(0), okuyucu.GetString(1)));
        }
    }
}
