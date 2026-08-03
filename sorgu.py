import os
import psycopg
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from llm import sor

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
TENANT = "english-home"
ESIK = 0.55

model = SentenceTransformer("BAAI/bge-m3")


def cevapla(soru):
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
                (soru_str, TENANT, soru_str),
            )
            satirlar = imlec.fetchall()

    if not satirlar or satirlar[0][1] < ESIK:
        en_iyi = satirlar[0][1] if satirlar else 0
        return f"[ESIK {en_iyi:.3f}] Bu bilgi dokümanlarda yer almıyor."

    secilen = [s[0] for s in satirlar]
    return sor(soru, secilen)


if __name__ == "__main__":
    print(cevapla("kasa sayımını kim yapar"))