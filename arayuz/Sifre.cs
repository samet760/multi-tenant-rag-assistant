using System.Security.Cryptography;

namespace arayuz;

public static class Sifre
{
    private const int TuzUzunlugu = 16;
    private const int OzetUzunlugu = 32;
    private const int Tekrar = 100_000;

    public static string Ozetle(string sifre)
    {
        byte[] tuz = RandomNumberGenerator.GetBytes(TuzUzunlugu);
        byte[] ozet = Rfc2898DeriveBytes.Pbkdf2(
            sifre, tuz, Tekrar, HashAlgorithmName.SHA256, OzetUzunlugu);
        return Convert.ToBase64String(tuz) + ":" + Convert.ToBase64String(ozet);
    }

    public static bool Dogrula(string sifre, string kayitli)
    {
        string[] parcalar = kayitli.Split(':');
        if (parcalar.Length != 2) return false;

        byte[] tuz = Convert.FromBase64String(parcalar[0]);
        byte[] kayitliOzet = Convert.FromBase64String(parcalar[1]);

        byte[] yeniOzet = Rfc2898DeriveBytes.Pbkdf2(
            sifre, tuz, Tekrar, HashAlgorithmName.SHA256, OzetUzunlugu);

        return CryptographicOperations.FixedTimeEquals(kayitliOzet, yeniOzet);
    }
}