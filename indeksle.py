import argparse
import os
import psycopg
from dotenv import load_dotenv

from parcala import parcalar_uret
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")


def indeksle(tenant, pdf_yolu):
    parcalar = parcalar_uret(pdf_yolu)
    metinler = [p["metin"] for p in parcalar]
    vektorler = model.encode(metinler, normalize_embeddings=True)

    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute("delete from parcalar where tenant_id = %s", (tenant,))

            for p, v in zip(parcalar, vektorler):
                imlec.execute(
                    "insert into parcalar (tenant_id, bolum, metin, vektor) values (%s, %s, %s, %s)",
                    (tenant, p["bolum"], p["metin"], str(v.tolist())),
                )

            baglanti.commit()

    print(f"yazildi: {len(parcalar)} (tenant={tenant}, pdf={pdf_yolu})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="english-home")
    parser.add_argument("--pdf", default="data/kurallar.pdf")
    args = parser.parse_args()
    indeksle(args.tenant, args.pdf)