using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Mvc.RazorPages;
using System.Net.Http.Json;

namespace arayuz.Pages;

public class IndexModel : PageModel
{
    [BindProperty]
    public string Soru { get; set; } = "";

    public string Cevap { get; set; } = "";

    public string SorulanSoru { get; set; } = "";

    public async Task OnPostAsync()
    {
        var istemci = new HttpClient();
        var govde = new { soru = Soru, tenant_id = "english-home" };
        var yanit = await istemci.PostAsJsonAsync("http://127.0.0.1:8000/sor", govde);
        var sonuc = await yanit.Content.ReadFromJsonAsync<SorguYaniti>();
        Cevap = sonuc?.cevap ?? "";
        SorulanSoru = Soru;
        
    }

    public class SorguYaniti
    {
        public string cevap { get; set; } = "";
    }
}