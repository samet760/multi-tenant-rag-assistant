import os
import psycopg
from dotenv import load_dotenv
from llm import sor
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
ESIK = 0.54



def cevapla(soru, tenant_id, departman_id=None):
    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    # departman_id verilmediyse (henuz sohbet tarafinda departman secimi
    # YOK - bkz. gorev talimati) eski davranis aynen korunur: sadece
    # tenant_id ile filtrelenir. Verildiginde departman_id = %s esitligi
    # kullanilir - bu, departman_id IS NULL olan (henuz departman
    # atanmamis) eski parcalari departman-filtreli aramada OTOMATIK
    # eler (SQL'de NULL hicbir esitlige eslesmez), ayrica bir CASE/IS NOT
    # NULL kosulu GEREKMEZ.
    sorgu = """
        select metin, 1 - (vektor <=> %s::vector) as skor
        from parcalar
        where tenant_id = %s
    """
    parametreler = [soru_str, tenant_id]

    if departman_id is not None:
        sorgu += " and departman_id = %s"
        parametreler.append(departman_id)

    sorgu += " order by vektor <=> %s::vector limit 3"
    parametreler.append(soru_str)

    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(sorgu, parametreler)
            satirlar = imlec.fetchall()

    if not satirlar or satirlar[0][1] < ESIK:
        en_iyi = satirlar[0][1] if satirlar else 0
        return "Bu bilgi dokümanlarda yer almıyor.", en_iyi

    secilen = [s[0] for s in satirlar]
    return sor(soru, secilen), satirlar[0][1]




if __name__ == "__main__":
    cevap, skor = cevapla("kasa sayımını kim yapar", "english-home")
    print(skor, cevap)