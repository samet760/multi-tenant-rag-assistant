using Microsoft.AspNetCore.Mvc;
using Npgsql;

namespace arayuz.ViewComponents;

public record SohbetOzet(long Id, string Baslik);

public record SohbetPaneliModeli(List<SohbetOzet> Sohbetler, int GosterilenSayisi, bool DahaFazlaVar);

public class SohbetPaneliViewComponent : ViewComponent
{
    // "Daha fazla goster" her tiklandiginda sohbetSayisi query parametresi
    // bu katlar halinde buyur (20 -> 40 -> 60...) - bkz. Default.cshtml.
    public const int SayfaBoyutu = 20;

    public IViewComponentResult Invoke()
    {
        if (UserClaimsPrincipal.Identity?.IsAuthenticated != true)
        {
            return Content("");
        }

        var tenant = UserClaimsPrincipal.FindFirst("tenant_id")!.Value;
        var eposta = UserClaimsPrincipal.Identity!.Name;

        // Gecersiz/eksik/SayfaBoyutu'ndan KUCUK bir deger her zaman
        // varsayilan SayfaBoyutu'na (20) duser - "daha fazla" asla geriye
        // (gosterilen sayiyi azaltarak) calisamaz.
        var gosterilecekSayi = SayfaBoyutu;
        if (int.TryParse(HttpContext.Request.Query["sohbetSayisi"], out var istenenSayi) && istenenSayi > gosterilecekSayi)
        {
            gosterilecekSayi = istenenSayi;
        }

        // Sinirin (gosterilecekSayi) otesinde baska sohbet var mi bilmek
        // icin TUM gecmisi cekmek yerine istenenden 1 FAZLASI istenir -
        // fazladan gelen satir sadece DahaFazlaVar bayragi icin kullanilir,
        // listeye DAHIL EDILMEZ (asagida atiliyor).
        const string SQL = @"
            select id, baslik from sohbetler
            where tenant_id = @t and eposta = @e
            order by olusturma_tarihi desc limit @lim";

        var liste = new List<SohbetOzet>();

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(SQL, baglanti))
        {
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("e", eposta!);
            komut.Parameters.AddWithValue("lim", gosterilecekSayi + 1);

            using var okuyucu = komut.ExecuteReader();
            while (okuyucu.Read())
            {
                liste.Add(new SohbetOzet(okuyucu.GetInt64(0), okuyucu.GetString(1)));
            }
        }

        var dahaFazlaVar = liste.Count > gosterilecekSayi;
        if (dahaFazlaVar)
        {
            liste.RemoveAt(liste.Count - 1);
        }

        return View(new SohbetPaneliModeli(liste, gosterilecekSayi, dahaFazlaVar));
    }
}
