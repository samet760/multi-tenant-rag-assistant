using Microsoft.Extensions.FileProviders;

DotNetEnv.Env.Load("../.env");

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddAuthentication("Cerez")
    .AddCookie("Cerez", ayar =>
    {
        ayar.LoginPath = "/Giris";
        ayar.AccessDeniedPath = "/Yetkisiz";
    });

// Add services to the container.
builder.Services.AddRazorPages();

var app = builder.Build();

// Configure the HTTP request pipeline.
if (!app.Environment.IsDevelopment())
{
    app.UseExceptionHandler("/Error");
    // The default HSTS value is 30 days. You may want to change this for production scenarios, see https://aka.ms/aspnetcore-hsts.
    app.UseHsts();
}

app.UseHttpsRedirection();

app.UseRouting();

var logolarYolu = Path.Combine(app.Environment.WebRootPath, "logolar");
Directory.CreateDirectory(logolarYolu);
app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(logolarYolu),
    RequestPath = "/logolar"
});

app.UseAuthentication();
app.UseAuthorization();

app.MapStaticAssets();
app.MapRazorPages()
   .WithStaticAssets();

app.Run();
