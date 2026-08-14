import os
import psycopg
from dotenv import load_dotenv
from llm import sor
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
ESIK = 0.54



def departman_yonlendir(tenant_id, soru_str):
    """Genel Asistan modunda (departman_id verilmemis) soruyu hangi
    departmana yonlendirecegini, TENANT'in kendi indekslenmis bilgisinden
    (embedding benzerligi) belirler - LLM'e SORULMAZ, departman adi/ID'si
    hiçbir yerde hardcode EDILMEZ. En yakin, departman_id'si dolu (IS NOT
    NULL) TEK parcayi bulur - departman_id'si hic atanmamis (NULL) eski
    parcalar bu yonlendirme aramasina hic girmez. Hic sonuc yoksa (tenant'in
    hic departman-etiketli parcasi yoksa) None doner, cagiran "bilgi yok"
    olarak ele alir.
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


def cevapla(soru, tenant_id, departman_id=None):
    # TEK encode - hem yonlendirme sorgusu hem asagidaki asil getirme AYNI
    # soru_str'i kullanir, ikinci bir model.encode() cagrisi YAPILMAZ.
    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    if departman_id is None:
        # Genel Asistan: departman otomatik secilir. Hicbir departmana
        # yonlendirilemiyorsa (tenant'in departman-etiketli hic parcasi
        # yoksa) TUM departmanlarda arama YAPILMAZ - guvenli "bilgi yok"
        # cevabi doner (bkz. gorev talimati).
        departman_id = departman_yonlendir(tenant_id, soru_str)
        if departman_id is None:
            return "Bu bilgi dokümanlarda yer almıyor.", 0

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

    if not satirlar or satirlar[0][1] < ESIK:
        en_iyi = satirlar[0][1] if satirlar else 0
        return "Bu bilgi dokümanlarda yer almıyor.", en_iyi

    secilen = [s[0] for s in satirlar]
    return sor(soru, secilen), satirlar[0][1]




if __name__ == "__main__":
    cevap, skor = cevapla("kasa sayımını kim yapar", "english-home")
    print(skor, cevap)