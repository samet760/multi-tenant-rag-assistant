import os
import psycopg
import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from parcala import parcalar

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
TENANT = "english-home"

model = SentenceTransformer("BAAI/bge-m3")
metinler = [p["metin"] for p in parcalar]
vektorler = model.encode(metinler, normalize_embeddings=True)

with psycopg.connect(URL) as baglanti:
    with baglanti.cursor() as imlec:
        imlec.execute("delete from parcalar where tenant_id = %s", (TENANT,))

        for p, v in zip(parcalar, vektorler):
            imlec.execute(
                "insert into parcalar (tenant_id, bolum, metin, vektor) values (%s, %s, %s, %s)",
                (TENANT, p["bolum"], p["metin"], str(v.tolist())),
            )

        baglanti.commit()

print("yazildi:", len(parcalar))