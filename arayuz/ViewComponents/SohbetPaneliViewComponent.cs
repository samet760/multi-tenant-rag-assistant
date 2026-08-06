using Microsoft.AspNetCore.Mvc;
using Npgsql;

namespace arayuz.ViewComponents;

public record SohbetOzet(long Id, string Baslik);

public class SohbetPaneliViewComponent : ViewComponent
{
    public IViewComponentResult Invoke()
    {
        if (UserClaimsPrincipal.Identity?.IsAuthenticated != true)
        {
            return Content("");
        }

        var tenant = UserClaimsPrincipal.FindFirst("tenant_id")!.Value;
        var eposta = UserClaimsPrincipal.Identity!.Name;

        const string SQL = @"
            select id, baslik from sohbetler
            where tenant_id = @t and eposta = @e
            order by olusturma_tarihi desc limit 20";

        var liste = new List<SohbetOzet>();

        using (var baglanti = Db.Baglan())
        using (var komut = new NpgsqlCommand(SQL, baglanti))
        {
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("e", eposta!);

            using var okuyucu = komut.ExecuteReader();
            while (okuyucu.Read())
            {
                liste.Add(new SohbetOzet(okuyucu.GetInt64(0), okuyucu.GetString(1)));
            }
        }

        return View(liste);
    }
}
