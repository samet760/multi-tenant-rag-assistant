using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize(Roles = "yonetici")]
public class KullaniciDepartmanlariModel : PageModel
{
    public record DepartmanUyelik(long Id, string Ad, bool Uye);

    [BindProperty(SupportsGet = true)]
    public long KullaniciId { get; set; }

    public bool Bulundu { get; set; }
    public string? Hata { get; set; }
    public string? Eposta { get; set; }
    public string? Rol { get; set; }
    public List<DepartmanUyelik> Departmanlar { get; set; } = new();

    public void OnGet()
    {
        Yukle();
    }

    private void Yukle()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();

        // Secilen kullanicinin bu tenant'a ait oldugu DOGRULANIR - baska
        // tenant'a ait veya var olmayan bir id ise genel bir "bulunamadi"
        // mesaji gosterilir, hangi durumun gecerli oldugu AYIRT EDILMEZ
        // (Departmanlar.cshtml.cs'teki ayni desen).
        using (var komut = new NpgsqlCommand(
            "select eposta, rol from kullanicilar where id = @id and tenant_id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("id", KullaniciId);
            komut.Parameters.AddWithValue("t", tenant);
            using var okuyucu = komut.ExecuteReader();
            if (!okuyucu.Read())
            {
                Hata = "Kullanıcı bulunamadı.";
                return;
            }
            Eposta = okuyucu.GetString(0);
            Rol = okuyucu.GetString(1);
        }

        Bulundu = true;

        if (Rol == "yonetici")
        {
            // Yonetici icin uyelik listesi ANLAMSIZ (bkz. sorgu.py / Belgeler
            // yetkilendirme predikati - yonetici membership ARANMADAN tum
            // departman erisimine sahip), bu yuzden hic sorgulanmaz.
            return;
        }

        // Tek round trip: tenant'in TUM departmanlari, secili kullanicinin
        // uyeligiyle LEFT JOIN'lenir. departmanlar zaten tenant_id=@t ile
        // filtrelendigi icin baska tenant'a ait bir departman asla listeye
        // giremez; kullanici_departmanlari da SADECE bu departman_id +
        // kullanici_id kombinasyonu icin JOIN edilir.
        const string SQL = @"
            select d.id, d.ad, (kd.kullanici_id is not null) as uye
            from departmanlar d
            left join kullanici_departmanlari kd
                on kd.departman_id = d.id and kd.kullanici_id = @id
            where d.tenant_id = @t
            order by d.ad";

        using (var komut2 = new NpgsqlCommand(SQL, baglanti))
        {
            komut2.Parameters.AddWithValue("id", KullaniciId);
            komut2.Parameters.AddWithValue("t", tenant);

            using var okuyucu = komut2.ExecuteReader();
            while (okuyucu.Read())
            {
                Departmanlar.Add(new DepartmanUyelik(
                    okuyucu.GetInt64(0),
                    okuyucu.GetString(1),
                    okuyucu.GetBoolean(2)
                ));
            }
        }
    }

    public IActionResult OnPostVer(long kullaniciId, long departmanId)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        // Kullanici + departman ownership'i AYRI round trip'lerde ONCEDEN
        // kontrol EDILMEZ - tek INSERT...SELECT icinde kaynastirilir. k.id/
        // d.id sadece ikisi de bu tenant'a aitse (ve hedef 'kullanici'
        // roluyse) satir uretir - tampered/cross-tenant bir id çifti HICBIR
        // satir eklemez, hata da FIRLATMAZ (sessizce 0 satir). ON CONFLICT
        // DO NOTHING ayni ciftin tekrar gonderilmesini (cift tikla vb.)
        // zararsiz kilar.
        const string SQL = @"
            insert into kullanici_departmanlari (kullanici_id, departman_id)
            select k.id, d.id
            from kullanicilar k
            cross join departmanlar d
            where k.id = @kid
              and k.tenant_id = @t
              and k.rol = 'kullanici'
              and d.id = @did
              and d.tenant_id = @t
            on conflict (kullanici_id, departman_id) do nothing";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("kid", kullaniciId);
        komut.Parameters.AddWithValue("did", departmanId);
        komut.Parameters.AddWithValue("t", tenant);
        komut.ExecuteNonQuery();

        return RedirectToPage(new { kullaniciId });
    }

    public IActionResult OnPostAl(long kullaniciId, long departmanId)
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        // Bare "delete where kullanici_id=@kid and departman_id=@did" DEGIL
        // - kullanici_departmanlari'nin kendi tenant_id kolonu YOK (bkz.
        // migrations/002_erisim_kontrolu.sql), o yuzden her iki tarafin da
        // bu tenant'a ait oldugu USING ile AYNI ifade icinde ISPATLANIR.
        // Tampered cross-tenant bir cift bu WHERE'e hic uymaz, HICBIR satir
        // silinmez.
        const string SQL = @"
            delete from kullanici_departmanlari kd
            using kullanicilar k, departmanlar d
            where kd.kullanici_id = k.id
              and kd.departman_id = d.id
              and kd.kullanici_id = @kid
              and kd.departman_id = @did
              and k.tenant_id = @t
              and d.tenant_id = @t";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("kid", kullaniciId);
        komut.Parameters.AddWithValue("did", departmanId);
        komut.Parameters.AddWithValue("t", tenant);
        komut.ExecuteNonQuery();

        return RedirectToPage(new { kullaniciId });
    }
}
