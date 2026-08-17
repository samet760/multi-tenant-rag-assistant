import os
import psycopg
from dotenv import load_dotenv
from llm import sor
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
ESIK = 0.54



def departman_yonlendir(tenant_id, soru_str, kullanici_id=None, rol=None):
    """Genel Asistan modunda (departman_id verilmemis) soruyu hangi
    departmana yonlendirecegini, TENANT'in kendi indekslenmis bilgisinden
    (embedding benzerligi) belirler - LLM'e SORULMAZ, departman adi/ID'si
    hiçbir yerde hardcode EDILMEZ. En yakin, departman_id'si dolu (IS NOT
    NULL) TEK parcayi bulur - departman_id'si hic atanmamis (NULL) eski
    parcalar bu yonlendirme aramasina hic girmez. Hic sonuc yoksa (tenant'in
    hic departman-etiketli parcasi yoksa) None doner, cagiran "bilgi yok"
    olarak ele alir.

    kullanici_id / rol: ADIM C2'de SADECE parametre olarak tasiniyor - ADIM
    C4'te bu fonksiyonun SQL'ine erisim_seviyesi/kullanici_departmanlari
    yetkilendirme predikati eklenecek, o predikat bu ikisine ihtiyac
    duyacak. Simdilik SQL'de KULLANILMIYOR, yonlendirme sonucunu
    ETKILEMIYOR.
    """
    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(
                """
                select departman_id
                from parcalar
                where tenant_id = %s and departman_id is not null
                order by vektor <=> %s::vector
                limit 1
                """,
                (tenant_id, soru_str),
            )
            satir = imlec.fetchone()

    return satir[0] if satir else None


def cevapla(soru, tenant_id, departman_id=None, kullanici_id=None, rol=None):
    # kullanici_id / rol: ADIM C2'de SADECE tasiniyor (servis.py'den gelen
    # GUVENILIR .NET kimligi) - ADIM C3/C4'te retrieval/yonlendirme SQL'ine
    # eklenecek yetkilendirme predikati bunlari kullanacak. Simdilik hicbir
    # SQL'de KULLANILMIYOR, mevcut RAG davranisini DEGISTIRMEZ.

    # TEK encode - hem yonlendirme sorgusu hem asagidaki asil getirme AYNI
    # soru_str'i kullanir, ikinci bir model.encode() cagrisi YAPILMAZ.
    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    if departman_id is None:
        # Genel Asistan: departman otomatik secilir. Hicbir departmana
        # yonlendirilemiyorsa (tenant'in departman-etiketli hic parcasi
        # yoksa) TUM departmanlarda arama YAPILMAZ - guvenli "bilgi yok"
        # cevabi doner (bkz. gorev talimati). Ucuncu deger (departman_id)
        # HIC belirlenemedigi icin None - cagiran (.NET) bunu "yonlendirme
        # basarisiz, gosterilecek departman adi yok" olarak okur.
        departman_id = departman_yonlendir(tenant_id, soru_str, kullanici_id, rol)
        if departman_id is None:
            return "Bu bilgi dokümanlarda yer almıyor.", 0, None

    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(
                """
                select metin, 1 - (vektor <=> %s::vector) as skor
                from parcalar
                where tenant_id = %s and departman_id = %s
                order by vektor <=> %s::vector
                limit 3
                """,
                (soru_str, tenant_id, departman_id, soru_str),
            )
            satirlar = imlec.fetchall()

    # departman_id BURADA HER ZAMAN dolu (elle secilmis ya da yukarida
    # yonlendirilmis) - fonksiyon hangi departmanda arandigini HER YANITTA
    # geri bildirir; bu SADECE raporlama, retrieval/esik/LLM akisi degismedi.
    if not satirlar or satirlar[0][1] < ESIK:
        en_iyi = satirlar[0][1] if satirlar else 0
        return "Bu bilgi dokümanlarda yer almıyor.", en_iyi, departman_id

    secilen = [s[0] for s in satirlar]
    return sor(soru, secilen), satirlar[0][1], departman_id




if __name__ == "__main__":
    cevap, skor, departman_id = cevapla("kasa sayımını kim yapar", "english-home")
    print(skor, departman_id, cevap)