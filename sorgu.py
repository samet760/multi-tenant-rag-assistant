import os
import psycopg
from dotenv import load_dotenv
from llm import sor
from embed import model

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")
ESIK = 0.54



def departman_yonlendir(tenant_id, soru_str, kullanici_id=None, rol=None):
    """Genel Asistan modunda (departman_id verilmemis) soruyu hangi
    departmana yonlendirecegini, TENANT'in kendi indekslenmis bilgisinden
    (embedding benzerligi) belirler - LLM'e SORULMAZ, departman adi/ID'si
    hiçbir yerde hardcode EDILMEZ. En yakin, departman_id'si dolu (IS NOT
    NULL) TEK parcayi bulur - departman_id'si hic atanmamis (NULL) eski
    parcalar bu yonlendirme aramasina hic girmez. Hic sonuc yoksa (tenant'in
    hic departman-etiketli parcasi yoksa) None doner, cagiran "bilgi yok"
    olarak ele alir.

    kullanici_id / rol: ADIM C4 - asagidaki sorgu, C3'teki asil getirme
    sorgusuyla AYNI yetkilendirme predikatini uygular (bkz. migrations/
    002_erisim_kontrolu.sql / PROJECT_MAP.md "Erisim kontrolu"). Yetkisiz
    bir parca ARTIK yonlendirme adayi bile olamaz - hangi departmana
    yonlendirilecegini SEC-ME asamasinda elenir, sadece sonradan gizlenmez.
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
                select departman_id
                from parcalar
                where tenant_id = %s and departman_id is not null
                and (
                    erisim_seviyesi = 'sirket'
                    or (
                        erisim_seviyesi = 'departman'
                        and departman_id is not null
                        and (
                            %s = 'yonetici'
                            or exists (
                                select 1 from kullanici_departmanlari kd
                                where kd.kullanici_id = %s
                                  and kd.departman_id = parcalar.departman_id
                            )
                        )
                    )
                )
                order by vektor <=> %s::vector
                limit 1
                """,
                (tenant_id, rol, kullanici_id, soru_str),
            )
            satir = imlec.fetchone()

    return satir[0] if satir else None


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
        departman_id = departman_yonlendir(tenant_id, soru_str, kullanici_id, rol)
        if departman_id is None:
            return "Bu bilgi dokümanlarda yer almıyor.", 0, None, []

    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            # Yetkilendirme predikati (ADIM C3, bkz. migrations/002_erisim_
            # kontrolu.sql / PROJECT_MAP.md "Erisim kontrolu"): manuel
            # secim de, yukarida departman_yonlendir'in bulduğu departman
            # da AYNI predikate tabi - hangi yoldan geldigine bakilmaksizin
            # burada uygulanir, ATLANAMAZ.
            # - erisim_seviyesi IS NULL -> ne 'sirket' ne 'departman' dalina
            #   uyar, HER ZAMAN reddedilir (varsayilan-kapali).
            # - 'sirket' -> tenant icindeki HERKESE acik.
            # - 'departman' + departman_id IS NULL -> reddedilir (ikinci
            #   AND'de acikca kontrol edilir, ayrica reddedilir).
            # - 'departman' + departman_id dolu -> yonetici HER departmani
            #   gorur (membership sorgusu ATLANIR); kullanici SADECE
            #   kullanici_departmanlari'nda o departmana ACIKCA uyeyse
            #   gorur (EXISTS alt sorgusu, ek round-trip YOK).
            #
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
                limit 3
                """,
                (soru_str, tenant_id, tenant_id, departman_id, rol, kullanici_id, soru_str),
            )
            satirlar = imlec.fetchall()

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