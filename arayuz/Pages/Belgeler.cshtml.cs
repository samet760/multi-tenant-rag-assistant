using System.Security.Claims;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;
using Microsoft.AspNetCore.Mvc;

namespace arayuz.Pages;

[Authorize]
public class BelgelerModel : PageModel
{
    public record Belge(long Id, string DosyaAdi, DateTime Tarih, long ParcaSayisi, string? DosyaYolu);
    public record Departman(long Id, string Ad);

    public List<Belge> Liste { get; set; } = new();
    public List<Departman> Departmanlar { get; set; } = new();
    public string? SeciliDepartmanAdi { get; set; }

    [BindProperty(SupportsGet = true)]
    public string? Ara { get; set; }

    [BindProperty(SupportsGet = true)]
    public long? DepartmanId { get; set; }

    public IActionResult OnGet()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        // "kullanici_id" claim'i sadece erisim kontrolu C1'de eklendi -
        // ondan once acilmis oturumlarda bulunmaz (bkz. Index.cshtml.cs
        // ayni desen). Uydurulmus bir kimlikle devam ETMEK YERINE kullanici
        // yeniden giris yapmaya zorlanir.
        var kullaniciIdClaim = User.FindFirst("kullanici_id");
        if (kullaniciIdClaim == null)
        {
            return RedirectToPage("/Cikis");
        }
        var kullaniciId = long.Parse(kullaniciIdClaim.Value);
        var rol = User.FindFirst(ClaimTypes.Role)!.Value;
        var yonetici = rol == "yonetici";

        using var baglanti = Db.Baglan();

        if (DepartmanId == null)
        {
            DepartmanlariYukle(baglanti, tenant, kullaniciId, yonetici);
            return Page();
        }

        // Secilen departman bu tenant'a mi ait dogrula - baska tenant'a ait
        // veya var olmayan bir id ise sessizce bos liste (fail-safe), hata
        // sayfasi/exception ile departmanin varligi ACIKLANMAZ.
        string? departmanAdi;
        using (var komut = new NpgsqlCommand(
            "select ad from departmanlar where id = @d and tenant_id = @t", baglanti))
        {
            komut.Parameters.AddWithValue("d", DepartmanId.Value);
            komut.Parameters.AddWithValue("t", tenant);
            departmanAdi = komut.ExecuteScalar() as string;
        }

        if (departmanAdi == null)
        {
            DepartmanId = null;
            DepartmanlariYukle(baglanti, tenant, kullaniciId, yonetici);
            return Page();
        }

        SeciliDepartmanAdi = departmanAdi;

        // Yetkilendirme predikati sorgu.py::cevapla ile AYNI mantik (bkz.
        // migrations/002_erisim_kontrolu.sql / PROJECT_MAP.md), parcalar
        // yerine belgeler uzerinde: erisim_seviyesi IS NULL -> hicbir dala
        // uymaz (red). 'departman' + departman_id IS NULL -> acikca
        // reddedilir. 'departman' + dolu departman_id -> yonetici membership
        // ARANMADAN gorur, kullanici SADECE kullanici_departmanlari'nda
        // acikca uyeyse gorur. Predikat WHERE icinde, satirlar donmeden
        // ONCE uygulanir - yetkisiz dosya adlari HIC listeye girmez.
        var sql = @"
            select b.id,
                   b.dosya_adi,
                   b.yukleme_tarihi,
                   (select count(*) from parcalar p where p.belge_id = b.id) as parca_sayisi,
                   b.dosya_yolu
            from belgeler b
            where b.tenant_id = @t and b.departman_id = @d
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
            )";

        if (!string.IsNullOrWhiteSpace(Ara))
        {
            sql += " and b.dosya_adi ilike @ara";
        }

        sql += " order by b.yukleme_tarihi desc";

        using (var komut = new NpgsqlCommand(sql, baglanti))
        {
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("d", DepartmanId.Value);
            komut.Parameters.AddWithValue("rol", rol);
            komut.Parameters.AddWithValue("kid", kullaniciId);

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

        return Page();
    }

    private void DepartmanlariYukle(NpgsqlConnection baglanti, string tenant, long kullaniciId, bool yonetici)
    {
        // Yonetici tum tenant departmanlarini gorur (belge sayisina
        // bakilmaksizin - admin yapiyi denetler). Normal kullanici SADECE
        // en az bir yetkili belgesi olan departmanlari gorur; bu filtre
        // EXISTS alt sorgusuyla SQL icinde uygulanir - tum departmanlari
        // cekip dosya adlarina gore hafizada elemek YAPILMAZ (gorev
        // talimati: yetkisiz belge adlari hic bellege bile alinmamali).
        var sql = yonetici
            ? "select id, ad from departmanlar where tenant_id = @t order by ad"
            : @"
                select d.id, d.ad
                from departmanlar d
                where d.tenant_id = @t
                and exists (
                    select 1 from belgeler b
                    where b.tenant_id = @t and b.departman_id = d.id
                    and (
                        b.erisim_seviyesi = 'sirket'
                        or (
                            b.erisim_seviyesi = 'departman'
                            and b.departman_id is not null
                            and exists (
                                select 1 from kullanici_departmanlari kd
                                where kd.kullanici_id = @kid and kd.departman_id = b.departman_id
                            )
                        )
                    )
                )
                order by d.ad";

        using var komut = new NpgsqlCommand(sql, baglanti);
        komut.Parameters.AddWithValue("t", tenant);
        if (!yonetici)
        {
            komut.Parameters.AddWithValue("kid", kullaniciId);
        }

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Departmanlar.Add(new Departman(okuyucu.GetInt64(0), okuyucu.GetString(1)));
        }
    }

    [Authorize(Roles = "yonetici")]
    public IActionResult OnPostSil(long id, long? departmanId)
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

        return RedirectToPage(new { departmanId });
    }
}
