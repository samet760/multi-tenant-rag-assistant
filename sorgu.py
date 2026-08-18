import os
import psycopg
from dotenv import load_dotenv
from llm import sor
from embed import model
from reranker import reranker_al

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
ESIK = 0.54
# Production'ın final getirme sorgusunun ADAY SAYISI - eskiden SQL icinde
# "limit 3" olarak gomuluydu, RAG V2 tani checkpoint'i icin
# final_adaylari_getir'e PARAMETRE olarak tasindi (bkz. asagisi). cevapla()
# bu SABITI kullanir - deger DEGISMEDI, sadece adi/gorunurlugu var.
SON_K = 3
# RAG V2 CHECKPOINT 1: departman_yonlendir'in reranker'a gonderdigi authorized
# DENSE aday havuzunun genisligi - rag_benchmark.py'nin tani icin kullandigi
# TANI_TOP_K (10) ile AYNI deger, ayri bir sabit olarak (production/tani
# birbirinden BAGIMSIZ kalsin diye, bkz. asagidaki departman_yonlendir).
ROUTER_TOP_K = 10



def departman_adaylari_getir(tenant_id, soru_str, kullanici_id, rol, limit):
    """Yonlendirme icin yetkilendirme-filtreli ADAY sorgusu - TEK yer, hem
    departman_yonlendir (limit=ROUTER_TOP_K ile, production - RAG V2
    CHECKPOINT 1'den itibaren reranker'a giden authorized aday havuzu) HEM
    rag_benchmark.py (tani amacli) burayi cagirir. WHERE predikati / ORDER
    BY, ilk halinden BIREBIR AYNI metin - SADECE LIMIT parametrik hale
    getirildi. Boylece iki cagiran ASLA farkli bir yetkilendirme mantigina
    SESSIZCE SAPAMAZ (final_adaylari_getir icin zaten kurulan AYNI desen,
    bkz. asagisi).

    Tani icin belge_id/dosya_adi/metin de SELECT edilir - final_adaylari_
    getir'deki AYNI JOIN deseniyle (b.id = p.belge_id AND b.tenant_id = %s):
    parcalar.belge_id -> belgeler.id FK'si ON DELETE CASCADE oldugu icin her
    parcalar satirinin GERCEKTEN AYNI tenant'a ait bir belgeler satiri VARDIR
    - bu JOIN satir KUMESINI/SIRALAMAYI degistiremez (hic satir dusmez/
    eklenmez), SADECE ek kolonlari GORUNUR kilar. Ekstra per-aday sorgu YOK -
    tum adaylar TEK bir sorguda gelir.
    """
    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            # Yetkilendirme predikati C3 ile AYNI mantik, tek fark: burada
            # tek bir departman_id'ye sabitlenmis outer filtre YOK (Genel
            # Asistan henuz hangi departmana yonlendirecegini SECMEDI) -
            # predikat HER aday satirin KENDI departman_id'sine gore
            # degerlendirilir (EXISTS alt sorgusu parcalar.departman_id'yi
            # referans alir).
            imlec.execute(
                """
                select p.departman_id,
                       1 - (p.vektor <=> %s::vector) as skor,
                       p.belge_id,
                       b.dosya_adi,
                       p.metin
                from parcalar p
                join belgeler b on b.id = p.belge_id and b.tenant_id = %s
                where p.tenant_id = %s and p.departman_id is not null
                and (
                    p.erisim_seviyesi = 'sirket'
                    or (
                        p.erisim_seviyesi = 'departman'
                        and p.departman_id is not null
                        and (
                            %s = 'yonetici'
                            or exists (
                                select 1 from kullanici_departmanlari kd
                                where kd.kullanici_id = %s
                                  and kd.departman_id = p.departman_id
                            )
                        )
                    )
                )
                order by p.vektor <=> %s::vector
                limit %s
                """,
                (soru_str, tenant_id, tenant_id, rol, kullanici_id, soru_str, limit),
            )
            return imlec.fetchall()


def departman_yonlendir(soru, tenant_id, soru_str, kullanici_id=None, rol=None):
    """Genel Asistan modunda (departman_id verilmemis) soruyu hangi
    departmana yonlendirecegini belirler - LLM'e (sor()/OpenRouter'a)
    SORULMAZ, departman adi/ID'si hiçbir yerde hardcode EDILMEZ.

    RAG V2 CHECKPOINT 1: yonlendirme artik SADECE dense top-1 DEGIL, iki
    asamali:
      1) departman_adaylari_getir ile authorized DENSE top-ROUTER_TOP_K aday
         cekilir (AYNI yetkilendirme predikati, WHERE icinde, ORDER BY/LIMIT
         'tan ONCE - bkz. asagidaki "Guvenlik" notu).
      2) Bu adaylarin metni, BAAI/bge-reranker-v2-m3 (bkz. reranker.py) ile
         soru'ya karsi TEK bir batch cagrisinda yeniden puanlanir; EN YUKSEK
         reranker skoruna sahip adayin departmani KAZANIR.
    Boylece dense top-1'in yanlis departmani sectigi (ama dogru parcanin
    dense top-10 icinde zaten var oldugu) durumlarda, reranker dogru
    departmani ONE CIKARABILIR - bkz. RAG V2 benchmark kaniti (rag_
    benchmark.py --rerank ile dogrulandi).

    Hic aday yoksa (tenant'in hic yetkili departman-etiketli parcasi yoksa)
    (None, None) doner - MEVCUT "hic departman bulunamadi" davranisi
    AYNEN korunur, reranker bu durumda HIC CAGRILMAZ.

    DONER: (departman_id, reranker_skoru) - ikinci deger ARTIK dense skor
    DEGIL, kazanan adayin reranker alaka skoru (routing kararini gercekten
    ACIKLAYAN skor budur). cevapla() bu degeri KULLANMAZ/yoksayar (mevcut
    davranis DEGISMEDI), sadece raporlama/tani icin GORULEBILIR. Mutlak bir
    esik burada UYDURULMAZ - reranker SADECE aday havuzu icinde GORECELI
    siralama icin kullanilir (bkz. gorev talimati).

    GUVENLIK: reranker'a giden HICBIR aday, departman_adaylari_getir'in
    WHERE'inde uygulanan tenant/erisim_seviyesi/departman_id/kullanici_
    departmanlari predikatini ATLAMAZ - yetkilendirme HER ZAMAN reranker'dan
    ONCE, SQL'in kendisinde tamamlanir (bkz. migrations/002_erisim_
    kontrolu.sql / PROJECT_MAP.md "Erisim kontrolu"). Reranker sadece ZATEN
    yetkilendirilmis bir listeyi YENIDEN SIRALAR, yeni satir EKLEMEZ/
    filtrelemeyi GEVSETMEZ.

    MODEL YASAM DONGUSU: reranker_al() tembel tekil (bkz. reranker.py) -
    ilk /sor istegi modeli yukler, sonraki HER istek (bu FastAPI/uvicorn
    surecinin omru boyunca) AYNI yuklu ornegi yeniden kullanir, istek
    basina YENIDEN YUKLEME OLMAZ.
    """
    adaylar = departman_adaylari_getir(tenant_id, soru_str, kullanici_id, rol, ROUTER_TOP_K)
    if not adaylar:
        return None, None

    # TEK batch cagrisi - aday basina ayri bir predict() cagrisi YOK.
    cross_encoder = reranker_al()
    ciftler = [[soru, aday[4]] for aday in adaylar]
    rerank_skorlari = cross_encoder.predict(ciftler)

    en_iyi_indeks = max(range(len(adaylar)), key=lambda i: rerank_skorlari[i])
    en_iyi_aday = adaylar[en_iyi_indeks]
    return en_iyi_aday[0], float(rerank_skorlari[en_iyi_indeks])


def final_adaylari_getir(tenant_id, departman_id, soru_str, kullanici_id, rol, limit):
    """Final yetkilendirme-filtreli aday sorgusu - TEK yer, hem cevapla()
    (limit=SON_K ile, production) HEM rag_benchmark.py (daha genis bir
    limit'le, TANI amacli) burayi cagirir. WHERE predikati / JOIN / ORDER BY
    ONCEKI inline sorguyla BIREBIR AYNI metin - SADECE LIMIT parametrik
    hale getirildi. Boylece iki cagiran ASLA farkli bir yetkilendirme
    mantigina SESSIZCE SAPAMAZ (bkz. RAG V2 tani checkpoint gorev talimati
    "Avoid duplicating the production SQL in a way that could silently
    diverge")."""
    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            # ADIM P2 (kaynak izlenebilirligi): AYNI yetkilendirme-filtreli
            # sorguya belgeler JOIN edilir - p.belge_id/b.dosya_adi SADECE bu
            # sorgunun zaten dondurdugu (yetkilendirilmis) satirlardan gelir,
            # ikinci/ayri bir dosya-adi sorgusu YOK. JOIN kosulu tenant'i
            # IKI KEZ dogrular (b.tenant_id = %s, p.tenant_id zaten WHERE'de) -
            # parcalar.belge_id FK'si zaten belgeler.id'ye cascade bagli
            # oldugu icin bu normalde gereksiz ama BelgeDuzenle/Belgeler'deki
            # AYNI "iki tarafi da ayrica ispatla" desenine uyar.
            imlec.execute(
                """
                select p.metin,
                       1 - (p.vektor <=> %s::vector) as skor,
                       p.belge_id,
                       b.dosya_adi
                from parcalar p
                join belgeler b on b.id = p.belge_id and b.tenant_id = %s
                where p.tenant_id = %s and p.departman_id = %s
                and (
                    p.erisim_seviyesi = 'sirket'
                    or (
                        p.erisim_seviyesi = 'departman'
                        and p.departman_id is not null
                        and (
                            %s = 'yonetici'
                            or exists (
                                select 1 from kullanici_departmanlari kd
                                where kd.kullanici_id = %s
                                  and kd.departman_id = p.departman_id
                            )
                        )
                    )
                )
                order by p.vektor <=> %s::vector
                limit %s
                """,
                (soru_str, tenant_id, tenant_id, departman_id, rol, kullanici_id, soru_str, limit),
            )
            return imlec.fetchall()


def cevapla(soru, tenant_id, departman_id=None, kullanici_id=None, rol=None):
    # kullanici_id / rol: servis.py'den gelen GUVENILIR .NET kimligi - hem
    # departman_yonlendir (ADIM C4) hem asagidaki asil getirme (ADIM C3)
    # yetkilendirme predikatinde kullanilir.

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
        # basarisiz, gosterilecek departman adi yok" olarak okur. Dorduncu
        # deger (kaynaklar) BOS - hicbir parca LLM'e verilmedi, yonlendirme
        # adaylari kaynak SAYILMAZ (bkz. ADIM P2 "Guvenlik" notu).
        # Router'in kendi (reranker) skoru (_router_skoru) production
        # akisinda KULLANILMAZ - sadece rag_benchmark.py::departman_yonlendir'i
        # DOGRUDAN cagirarak bu skoru gorebilir, cevapla() burada yoksayar.
        departman_id, _router_skoru = departman_yonlendir(soru, tenant_id, soru_str, kullanici_id, rol)
        if departman_id is None:
            return "Bu bilgi dokümanlarda yer almıyor.", 0, None, []

    # Yetkilendirme predikati (ADIM C3, bkz. migrations/002_erisim_
    # kontrolu.sql / PROJECT_MAP.md "Erisim kontrolu"): manuel secim de,
    # yukarida departman_yonlendir'in bulduğu departman da AYNI predikate
    # tabi - hangi yoldan geldigine bakilmaksizin final_adaylari_getir
    # icinde uygulanir, ATLANAMAZ.
    # - erisim_seviyesi IS NULL -> ne 'sirket' ne 'departman' dalina uyar,
    #   HER ZAMAN reddedilir (varsayilan-kapali).
    # - 'sirket' -> tenant icindeki HERKESE acik.
    # - 'departman' + departman_id IS NULL -> reddedilir.
    # - 'departman' + departman_id dolu -> yonetici HER departmani gorur
    #   (membership sorgusu ATLANIR); kullanici SADECE kullanici_
    #   departmanlari'nda o departmana ACIKCA uyeyse gorur.
    satirlar = final_adaylari_getir(tenant_id, departman_id, soru_str, kullanici_id, rol, SON_K)

    # departman_id BURADA HER ZAMAN dolu (elle secilmis ya da yukarida
    # yonlendirilmis) - fonksiyon hangi departmanda arandigini HER YANITTA
    # geri bildirir; bu SADECE raporlama, retrieval/esik/LLM akisi degismedi.
    if not satirlar or satirlar[0][1] < ESIK:
        en_iyi = satirlar[0][1] if satirlar else 0
        # Esik altinda kalan/hic satir donmeyen aday parcalar LLM'e HIC
        # VERILMEDI - kaynaklar BOS doner, esigi gecemeyen bir belge "kaynak"
        # olarak GOSTERILMEZ.
        return "Bu bilgi dokümanlarda yer almıyor.", en_iyi, departman_id, []

    secilen = [s[0] for s in satirlar]

    # Kaynaklar SADECE LLM'e verilen (secilen) parcalarin belgelerinden
    # olusur, ilk-gorulme sirasi korunarak belge_id'ye gore TEKILLESTIRILIR -
    # ayni belgeden birden fazla parca gelmisse (sik durum, bkz. PROJECT_MAP.md
    # "Top-K provenance semantics") tek bir kaynak satiri olarak gorunur.
    kaynaklar = []
    gorulen_belgeler = set()
    for _, _, belge_id, dosya_adi in satirlar:
        if belge_id in gorulen_belgeler:
            continue
        gorulen_belgeler.add(belge_id)
        kaynaklar.append({"belge_id": belge_id, "dosya_adi": dosya_adi})

    return sor(soru, secilen), satirlar[0][1], departman_id, kaynaklar




if __name__ == "__main__":
    cevap, skor, departman_id, kaynaklar = cevapla("kasa sayımını kim yapar", "english-home")
    print(skor, departman_id, kaynaklar, cevap)