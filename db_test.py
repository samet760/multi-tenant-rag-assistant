import os
import psycopg
from dotenv import load_dotenv

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")

with psycopg.connect(URL) as baglanti:
    with baglanti.cursor() as imlec:
        imlec.execute("select count(*) from parcalar")
        print("baglanti tamam, satir sayisi:", imlec.fetchone()[0])