import os
import psycopg
from dotenv import load_dotenv
from llm import sor
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
ESIK = 0.54



def cevapla(soru, tenant_id):
    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(
                """
                select metin, 1 - (vektor <=> %s::vector) as skor
                from parcalar
                where tenant_id = %s
                order by vektor <=> %s::vector
                limit 3
                """,
                (soru_str, tenant_id, soru_str),
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