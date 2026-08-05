import os
import psycopg
from dotenv import load_dotenv
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
TENANT = "english-home"

sorular = [
    "kasa sayımını kim yapar",
    "mesaide telefon kullanabilir miyim",
    "müşteri bilgisi paylaşılır mı",
    "mağaza kaçta açılıyor",
    "geç kalırsam ne olur",
    "hava nasıl olacak",
    "python nasil öğrenilir",
    "en iyi pizza nerede",
    "kedim hasta",
    "dolar kaç lira",
    "maaşım ne zaman yatar",
    "yıllık zam oranı kaç",
    "doğum izni kaç gün",
]

with psycopg.connect(URL) as baglanti:
    with baglanti.cursor() as imlec:
        for soru in sorular:
            soru_v = model.encode(soru, normalize_embeddings=True)
            soru_str = str(soru_v.tolist())

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

            print(f"\n=== {soru}")
            for sira, (metin, skor) in enumerate(satirlar, 1):
                print(f"  {sira}. skor={skor:.3f}")
                print(f"     {metin[:100]}...")