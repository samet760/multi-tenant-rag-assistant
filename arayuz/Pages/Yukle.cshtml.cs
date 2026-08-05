using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;

namespace arayuz.Pages;

[Authorize(Roles = "yonetici")]
public class YukleModel : PageModel
{
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

        if (yanit.IsSuccessStatusCode)
        {
            Mesaj = $"{Dosya.FileName} yüklendi ve indekslendi.";
        }
        else
        {
            Mesaj = $"Hata: {(int)yanit.StatusCode}";
        }
    }
}