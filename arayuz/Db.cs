using Npgsql;

namespace arayuz;

public static class Db
{
    public static NpgsqlConnection Baglan()
    {
        var url = Environment.GetEnvironmentVariable("SUPABASE_DB_URL")
            ?? throw new Exception("SUPABASE_DB_URL bulunamadi");

        var uri = new Uri(url);
        var kullanici = uri.UserInfo.Split(':')[0];
        var sifre = Uri.UnescapeDataString(uri.UserInfo.Split(':')[1]);

        var dize =
            $"Host={uri.Host};Port={uri.Port};Username={kullanici};" +
            $"Password={sifre};Database={uri.AbsolutePath.TrimStart('/')};SSL Mode=Require";

        var baglanti = new NpgsqlConnection(dize);
        baglanti.Open();
        return baglanti;
    }
}
