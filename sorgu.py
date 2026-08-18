import os
import psycopg
from dotenv import load_dotenv
from llm import sor
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
ESIK = 0.54
# Production'ın final getirme sorgusunun ADAY SAYISI - eskiden SQL icinde
# "limit 3" olarak gomuluydu, RAG V2 tani checkpoint'i icin
# final_adaylari_getir'e PARAMETRE olarak tasindi (bkz. asagisi). cevapla()
# bu SABITI kullanir - deger DEGISMEDI, sadece adi/gorunurlugu var.
SON_K = 3



def departman_adaylari_getir(tenant_id, soru_str, kullanici_id, rol, limit):
    """Yonlendirme icin yetkilendirme-filtreli ADAY sorgusu - TEK yer, hem
    departman_yonlendir (limit=1 ile, production) HEM rag_benchmark.py
    (daha genis bir limit'le, TANI amacli) burayi cagirir. WHERE predikati /
    ORDER BY, departman_yonlendir'in ONCEKI inline sorgusuyla BIREBIR AYNI
    metin - SADECE LIMIT parametrik hale getirildi. Boylece iki cagiran ASLA
    farkli bir yetkilendirme mantigina SESSIZCE SAPAMAZ (final_adaylari_
    getir icin zaten kurulan AYNI desen, bkz. asagisi).

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


def departman_yonlendir(tenant_id, soru_str, kullanici_id=None, rol=None):
    """Genel Asistan modunda (departman_id verilmemis) soruyu hangi
    departmana yonlendirecegini, TENANT'in kendi indekslenmis bilgisinden
    (embedding benzerligi) belirler - LLM'e SORULMAZ, departman adi/ID'si
    hiçbir yerde hardcode EDILMEZ. En yakin, departman_id'si dolu (IS NOT
    NULL) TEK parcayi bulur - departman_id'si hic atanmamis (NULL) eski
    parcalar bu yonlendirme aramasina hic girmez. Hic sonuc yoksa (tenant'in
    hic departman-etiketli parcasi yoksa) (None, None) doner, cagiran "bilgi
    yok" olarak ele alir.

    DONER: (departman_id, skor) ikilisi - RAG V2 tani checkpoint'i icin
    router'in KENDI guven skorunu da gorunur kilmak amaciyla eklendi (bkz.
    rag_benchmark.py). cevapla() production akisinda skoru KULLANMAZ/
    yoksayar - davranis DEGISMEDI, sadece artik cagiran tarafta GORULEBILIR.

    ARTIK departman_adaylari_getir(..., limit=1) cagirip ILK satiri
    kullanir - SORGU METNI/WHERE/ORDER BY DEGISMEDI (sadece paylasilan
    yardimci fonksiyona TASINDI), limit=1 ONCEKI "limit 1" ile BIREBIR AYNI
    deger - kazanan (en yakin yetkili parcanin departmani) HER ZAMAN aynen
    ONCEKI gibi secilir, davranis byte-for-byte AYNI kalir.

    kullanici_id / rol: ADIM C4 - yukaridaki sorgu, C3'teki asil getirme
    sorgusuyla AYNI yetkilendirme predikatini uygular (bkz. migrations/
    002_erisim_kontrolu.sql / PROJECT_MAP.md "Erisim kontrolu"). Yetkisiz
    bir parca ARTIK yonlendirme adayi bile olamaz - hangi departmana
    yonlendirilecegini SEC-ME asamasinda elenir, sadece sonradan gizlenmez.
    """
    adaylar = departman_adaylari_getir(tenant_id, soru_str, kullanici_id, rol, 1)
    if not adaylar:
        return None, None
    return adaylar[0][0], adaylar[0][1]


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
        # Router'in kendi skoru (_router_skoru) production akisinda
        # KULLANILMAZ - sadece rag_benchmark.py::departman_yonlendir'i
        # DOGRUDAN cagirarak bu skoru gorebilir, cevapla() burada yoksayar.
        departman_id, _router_skoru = departman_yonlendir(tenant_id, soru_str, kullanici_id, rol)
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