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

    public string? Mesaj { get; set; }

    public async Task OnPostAsync()
    {
        if (Dosya == null || Dosya.Length == 0)
        {
            Mesaj = "Dosya seçilmedi.";
            return;
        }

        var tenant = User.FindFirst("tenant_id")!.Value;

        using var icerik = new MultipartFormDataContent();
        icerik.Add(new StringContent(tenant), "tenant_id");
        icerik.Add(new StringContent(Dosya.FileName), "dosya_adi");
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
