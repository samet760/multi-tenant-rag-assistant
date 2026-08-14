using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using Npgsql;

namespace arayuz.Pages;

[Authorize(Roles = "yonetici")]
public class YukleModel : PageModel
{
    private readonly IWebHostEnvironment _ortam;

    public YukleModel(IWebHostEnvironment ortam)
    {
        _ortam = ortam;
    }

    [BindProperty]
    public IFormFile? Dosya { get; set; }

    [BindProperty]
    public long? DepartmanId { get; set; }

    public string? Mesaj { get; set; }

    public record Departman(long Id, string Ad);
    public List<Departman> Departmanlar { get; set; } = new();

    public void OnGet()
    {
        DepartmanlariYukle();
    }

    // Dropdown'u doldurmak icin - GET'te ve POST'ta (basarili/basarisiz
    // her durumda sayfa yeniden render edilecegi icin) cagrilir.
    private void DepartmanlariYukle()
    {
        var tenant = User.FindFirst("tenant_id")!.Value;

        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(
            "select id, ad from departmanlar where tenant_id = @t order by ad", baglanti);
        komut.Parameters.AddWithValue("t", tenant);

        using var okuyucu = komut.ExecuteReader();
        while (okuyucu.Read())
        {
            Departmanlar.Add(new Departman(okuyucu.GetInt64(0), okuyucu.GetString(1)));
        }
    }

    // Secilen departman ID'si (dropdown'dan gelen) GERCEKTEN bu tenant'a mi
    // ait - tarayicidan gelen degere DOGRUDAN guvenilmiyor, DB'de tenant_id
    // ile birlikte dogrulaniyor. Baska bir tenant'in departman ID'si manuel
    // POST edilirse bu sorgu 0 satir doner ve yukleme reddedilir.
    private bool DepartmanGecerliMi(long departmanId, string tenant)
    {
        using var baglanti = Db.Baglan();
        using var komut = new NpgsqlCommand(
            "select 1 from departmanlar where id = @d and tenant_id = @t", baglanti);
        komut.Parameters.AddWithValue("d", departmanId);
        komut.Parameters.AddWithValue("t", tenant);
        return komut.ExecuteScalar() != null;
    }

    public async Task OnPostAsync()
    {
        DepartmanlariYukle();

        if (Dosya == null || Dosya.Length == 0)
        {
            Mesaj = "Dosya seçilmedi.";
            return;
        }

        var tenant = User.FindFirst("tenant_id")!.Value;

        if (DepartmanId == null || !DepartmanGecerliMi(DepartmanId.Value, tenant))
        {
            Mesaj = "Lütfen geçerli bir departman seçin.";
            return;
        }

        using var icerik = new MultipartFormDataContent();
        icerik.Add(new StringContent(tenant), "tenant_id");
        icerik.Add(new StringContent(Dosya.FileName), "dosya_adi");
        icerik.Add(new StringContent(DepartmanId.Value.ToString()), "departman_id");
        icerik.Add(new StreamContent(Dosya.OpenReadStream()), "dosya", "belge.pdf");

        var istemci = new HttpClient();
        istemci.Timeout = TimeSpan.FromMinutes(5);

        var yanit = await istemci.PostAsync("http://127.0.0.1:8000/indeksle", icerik);

        if (!yanit.IsSuccessStatusCode)
        {
            Mesaj = $"Hata: {(int)yanit.StatusCode}";
            return;
        }

        var sonuc = await yanit.Content.ReadFromJsonAsync<IndeksleYaniti>();
        Mesaj = $"{Dosya.FileName} yüklendi ve indekslendi.";

        if (sonuc == null)
        {
            return;
        }

        try
        {
            var klasor = Path.Combine(_ortam.ContentRootPath, "belge-deposu");
            Directory.CreateDirectory(klasor);
            var yol = Path.Combine(klasor, sonuc.belge_id + ".pdf");

            await using (var kaynak = Dosya.OpenReadStream())
            await using (var hedef = new FileStream(yol, FileMode.Create))
            {
                await kaynak.CopyToAsync(hedef);
            }

            using var baglanti = Db.Baglan();
            using var komut = new NpgsqlCommand(
                "update belgeler set dosya_yolu = @y where id = @b and tenant_id = @t", baglanti);
            komut.Parameters.AddWithValue("y", yol);
            komut.Parameters.AddWithValue("b", sonuc.belge_id);
            komut.Parameters.AddWithValue("t", tenant);
            komut.ExecuteNonQuery();
        }
        catch
        {
            Mesaj = $"{Dosya.FileName} yüklendi ve indekslendi, ancak dosya kopyası saklanamadı.";
        }
    }

    private class IndeksleYaniti
    {
        public string durum { get; set; } = "";
        public long belge_id { get; set; }
    }
}
