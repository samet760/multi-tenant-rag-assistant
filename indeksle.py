import argparse
import os
import psycopg
from dotenv import load_dotenv
from embed import model
from parcala import parcalar_uret

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")


def indeksle(tenant, pdf_yolu, dosya_adi, departman_id=None):
    parcalar = parcalar_uret(pdf_yolu)
    metinler = [p["metin"] for p in parcalar]
    vektorler = model.encode(metinler, normalize_embeddings=True)

    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(
                "insert into belgeler (tenant_id, dosya_adi, departman_id) values (%s, %s, %s) returning id",
                (tenant, dosya_adi, departman_id),
            )
            belge_id = imlec.fetchone()[0]

            for p, v in zip(parcalar, vektorler):
                imlec.execute(
                    "insert into parcalar (tenant_id, bolum, metin, vektor, belge_id, departman_id) values (%s, %s, %s, %s, %s, %s)",
                    (tenant, p["bolum"], p["metin"], str(v.tolist()), belge_id, departman_id),
                )

            baglanti.commit()

    print(f"yazildi: {len(parcalar)} (tenant={tenant}, belge_id={belge_id}, departman_id={departman_id}, dosya={dosya_adi})")
    return belge_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default="english-home")
    parser.add_argument("--pdf", default="data/kurallar.pdf")
    parser.add_argument("--departman-id", type=int, default=None)
    args = parser.parse_args()
    indeksle(args.tenant, args.pdf, os.path.basename(args.pdf), args.departman_id)