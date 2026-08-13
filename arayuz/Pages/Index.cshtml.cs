using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;
using System.Net.Http.Json;

namespace arayuz.Pages;

[Microsoft.AspNetCore.Authorization.Authorize]
public class IndexModel : PageModel
{
    public const int SoruMaksUzunluk = 4000;

    [BindProperty]
    public string Soru { get; set; } = "";

    [BindProperty(SupportsGet = true)]
    public long? SohbetId { get; set; }

    public string Cevap { get; set; } = "";

    public string? Hata { get; set; }

    public record Mesaj(string Rol, string Metin, double? Skor);
    public List<Mesaj> Mesajlar { get; set; } = new();

    public void OnGet()
    {
        MesajlariYukle();
    }

    private void MesajlariYukle()
    {
        if (SohbetId == null) return;

        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;

        const string SQL = @"
            select m.rol, m.metin, m.skor from mesajlar m
            join sohbetler s on s.id = m.sohbet_id
            where m.sohbet_id = @s and s.tenant_id = @t and s.eposta = @e
            order by m.id";

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(SQL, baglanti);
        komut.Parameters.AddWithValue("s", SohbetId.Value);
        komut.Parameters.AddWithValue("t", tenant);
        komut.Parameters.AddWithValue("e", eposta!);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Mesajlar.Add(new Mesaj(
                okuyucu.GetString(0),
                okuyucu.GetString(1),
                okuyucu.IsDBNull(2) ? null : okuyucu.GetDouble(2)
            ));
        }
    }

    public async Task<IActionResult> OnPostAsync()
    {
        if (string.IsNullOrWhiteSpace(Soru))
        {
            return Page();
        }

        if (Soru.Length > SoruMaksUzunluk)
        {
            Hata = $"Soru en fazla {SoruMaksUzunluk} karakter olabilir.";
            return Page();
        }

        var istemci = new HttpClient();
        var tenant = User.FindFirst("tenant_id")!.Value;
        var eposta = User.Identity!.Name;
        var govde = new { soru = Soru, tenant_id = tenant };

        SorguYaniti? sonuc = null;
        try
        {
            var yanit = await istemci.PostAsJsonAsync("http://127.0.0.1:8000/sor", govde);
            sonuc = await yanit.Content.ReadFromJsonAsync<SorguYaniti>();
            Cevap = sonuc?.cevap ?? "";
        }
        catch (Exception ex) when (ex is TimeoutException ||
            (ex is TaskCanceledException tce && tce.InnerException is TimeoutException))
        {
            // HttpClient'in kendi (varsayilan 100s) suresi doldugunda TaskCanceledException
            // firlatir ve InnerException TimeoutException olur - bu ikisi DISINDA baska
            // bir TaskCanceledException (orn. istemci baglantiyi kesti) burada YUTULMAZ,
            // filtreye takilmadigi icin normal sekilde yukari firlar.
            Cevap = "İstek zaman aşımına uğradı. Lütfen daha kısa veya daha net bir soru deneyin.";
        }

        using var baglanti = Db.Baglan();

        if (SohbetId == null)
        {
            const string SQL_SOHBET = @"
                insert into sohbetler (tenant_id, eposta, baslik)
                values (@t, @e, @b) returning id";

            var baslik = Soru.Length > 50 ? Soru.Substring(0, 50) : Soru;

            using var komut = new NpgsqlCommand(SQL_SOHBET, baglanti);
            komut.Parameters.AddWithValue("t", tenant);
            komut.Parameters.AddWithValue("e", eposta!);
            komut.Parameters.AddWithValue("b", baslik);

            SohbetId = (long)komut.ExecuteScalar()!;
        }

        const string SQL_MESAJ = "insert into mesajlar (sohbet_id, rol, metin, skor) values (@s, @r, @m, @sk)";

        using (var komut = new NpgsqlCommand(SQL_MESAJ, baglanti))
        {
            komut.Parameters.AddWithValue("s", SohbetId.Value);
            komut.Parameters.AddWithValue("r", "soru");
            komut.Parameters.AddWithValue("m", Soru);
            komut.Parameters.AddWithValue("sk", DBNull.Value);
            komut.ExecuteNonQuery();
        }

        using (var komut = new NpgsqlCommand(SQL_MESAJ, baglanti))
        {
            komut.Parameters.AddWithValue("s", SohbetId.Value);
            komut.Parameters.AddWithValue("r", "cevap");
            komut.Parameters.AddWithValue("m", Cevap);
            komut.Parameters.AddWithValue("sk", (object?)sonuc?.skor ?? DBNull.Value);
            komut.ExecuteNonQuery();
        }

        return RedirectToPage(new { sohbetId = SohbetId });
    }

    public class SorguYaniti
    {
        public string cevap { get; set; } = "";
        public double? skor { get; set; }
    }
}
