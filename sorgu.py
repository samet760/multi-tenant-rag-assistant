import os
import time
import psycopg
from dotenv import load_dotenv
from llm import sor, baglamsallastir, YETERSIZ_KANIT_CEVABI, YETERSIZ_KANIT_CEVAPLARI
from embed import model
from reranker import reranker_al

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")

# LATENCY DIAGNOSTICS CHECKPOINT: opt-in olcum modu - bayrak KAPALIYKEN
# davranis/performans onceki checkpoint ile BIREBIR AYNI kalir (zamanlama
# fonksiyonlari cagrilir ama zamanlama=None gecildiginde her yerde erken
# "if zamanlama is not None" kontroluyle ATLANIR - hicbir ekstra print/
# hesap YAPILMAZ). Sadece olcum/tanı amacli - RAG davranisi/yetkilendirme/
# retrieval/reranking/grounding'e HICBIR ETKISI YOK (bkz. gorev talimati).
RAG_TIMING_ACIK = os.getenv("RAG_TIMING") == "1"
# RAG V2 CHECKPOINT 2: RETIRED - ESIK ARTIK production'da cevaplanabilirlik
# KARARI VERMEZ (bkz. gorev talimati "REMOVE ESIK AS PRODUCTION
# ANSWERABILITY GATE"). Ham dense benzerlik guvenilir bir evrensel
# cevaplanabilirlik sinifladirici DEGIL - kanit: bir "Mars" niteleyicili,
# desteklenmeyen soru ~0.631 gibi YUKSEK bir dense skor alirken, gecerli bir
# parafraz ~0.538 ile bu esigin ALTINDA kaliyordu. Nihai cevaplanabilirlik
# karari artik TAMAMEN llm.py'nin deterministik YETERSIZ_KANIT_CEVAPLARI
# sozlesmesine ait (bkz. asagidaki cevapla()). Bu sabit SILINMEDI - SADECE
# rag_benchmark.py'de ACIKCA "LEGACY diagnostic only" olarak etiketlenmis,
# ISTEGE BAGLI bir tarihsel karsilastirma icin KORUNDU; cevapla()'nin
# HICBIR YERINDE ARTIK OKUNMAZ/KARSILASTIRILMAZ.
ESIK = 0.54
# RAG V2 CHECKPOINT 1: departman_yonlendir'in reranker'a gonderdigi authorized
# DENSE aday havuzunun genisligi - rag_benchmark.py'nin tani icin kullandigi
# TANI_TOP_K (10) ile AYNI deger, ayri bir sabit olarak (production/tani
# birbirinden BAGIMSIZ kalsin diye, bkz. asagidaki departman_yonlendir).
ROUTER_TOP_K = 10
# RAG V2 CHECKPOINT 2: routed departman icindeki authorized DENSE aday
# havuzunun genisligi - reranker'a giden final aday sayisi (bkz. asagidaki
# final_baglam_sec). Eskiden final getirme SQL'e gomulu "limit 3" (SON_K) ile
# dogrudan LLM'e giden parcalari cekiyordu - SON_K'nin bu rolu KALDIRILDI,
# yerini FINAL_ADAY_TOP_K (aday havuzu) + FINAL_BAGLAM_K (nihai kanit) aldi.
FINAL_ADAY_TOP_K = 10
# RAG V2 CHECKPOINT 2: reranker siralamasindan SONRA LLM'e giden VE
# provenance'i belirleyen NIHAI kanit parca sayisi (bkz. gorev talimati
# "FINAL EVIDENCE"). Eski SON_K=3'un YERINE gecti - deger BILINCLI olarak
# 3'ten 4'e cikti (gorev talimatinda acikca istendigi gibi).
FINAL_BAGLAM_K = 4



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


def reranker_ile_sirala(soru, ogeler, metin_al):
    """AYNI aday/oge listesini BAAI/bge-reranker-v2-m3 ile TEK bir batch
    cagrisinda yeniden siralar - router (departman_yonlendir) VE final
    getirme (final_baglam_sec) arasinda PAYLASILAN TEK kod (bkz. gorev
    talimati "tiny shared reranking helper... prevents duplicated ranking
    code"). rag_benchmark.py de AYNI fonksiyonu tani amacli cagirir - kendi
    predict()/sort mantigini KOPYALAMAZ.

    metin_al: her ogeden puanlanacak metni cikaran KUCUK bir fonksiyon -
    cagiranlarin SQL kolon sirasi/veri sekli farkli oldugu icin (departman_
    adaylari_getir vs final_adaylari_getir vs rag_benchmark.py'nin tani
    amacli enumerate edilmis ogeleri) bu KASITLI olarak disaridan verilir,
    burada hicbir SQL/yetkilendirme mantigi YOKTUR - sadece zaten cekilmis
    (yetkilendirilmis) bir listeyi bellekte yeniden siralar.

    Ogeleri, reranker skoruna gore AZALAN sirada, her biriyle esli skorla
    birlikte dondurur: [(oge, reranker_skoru), ...]. Mutlak bir esik
    UYGULANMAZ - SADECE GORECELI siralama (bkz. gorev talimati). Bos liste
    verilirse bos liste doner - reranker HIC CAGRILMAZ.
    """
    if not ogeler:
        return []
    cross_encoder = reranker_al()
    ciftler = [[soru, metin_al(oge)] for oge in ogeler]
    rerank_skorlari = cross_encoder.predict(ciftler)
    esli = list(zip(ogeler, (float(s) for s in rerank_skorlari)))
    esli.sort(key=lambda cift: cift[1], reverse=True)
    return esli


def departman_yonlendir(soru, tenant_id, soru_str, kullanici_id=None, rol=None, zamanlama=None):
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
    # LATENCY DIAGNOSTICS: zamanlama SADECE RAG_TIMING=1 iken cevapla()
    # tarafindan dolu bir dict olarak gecilir - None ise (varsayilan/normal
    # istek) her perf_counter() cagrisi ATLANIR, davranis/hiz ETKILENMEZ.
    t0 = time.perf_counter() if zamanlama is not None else None
    adaylar = departman_adaylari_getir(tenant_id, soru_str, kullanici_id, rol, ROUTER_TOP_K)
    if zamanlama is not None:
        zamanlama["router_sql"] = time.perf_counter() - t0
        zamanlama["router_aday_n"] = len(adaylar)
    if not adaylar:
        return None, None

    # departman_adaylari_getir'in satir sekli: (departman_id, skor, belge_id,
    # dosya_adi, metin) - metin son eleman (indeks 4).
    t1 = time.perf_counter() if zamanlama is not None else None
    siralanmis = reranker_ile_sirala(soru, adaylar, metin_al=lambda aday: aday[4])
    if zamanlama is not None:
        # Ilk /sor istegi (uvicorn restart sonrasi) burada reranker_al()'in
        # LAZY model yuklemesini de ICERIR - bu yuzden ilk isteğin
        # router_rerank suresi, sonraki SICAK isteklerden GOZLE GORULUR
        # sekilde daha yuksek cikar (bkz. gorev talimati "distinguish cold
        # start from warm requests"). Bilinclendirmek disinda BURADA hicbir
        # ekstra model on-yukleme/lifecycle degisikligi YAPILMAZ.
        zamanlama["router_rerank"] = time.perf_counter() - t1
    en_iyi_aday, en_iyi_skor = siralanmis[0]
    return en_iyi_aday[0], en_iyi_skor


def final_adaylari_getir(tenant_id, departman_id, soru_str, kullanici_id, rol, limit):
    """Final yetkilendirme-filtreli aday sorgusu - TEK yer, hem final_baglam_
    sec (limit=FINAL_ADAY_TOP_K ile, production - RAG V2 CHECKPOINT 2'den
    itibaren reranker'a giden authorized aday havuzu) HEM rag_benchmark.py
    (tani amacli) burayi cagirir. WHERE predikati / JOIN / ORDER BY ilk
    halinden BIREBIR AYNI metin - SADECE LIMIT parametrik hale getirildi.
    Boylece iki cagiran ASLA farkli bir yetkilendirme mantigina SESSIZCE
    SAPAMAZ (bkz. RAG V2 tani checkpoint gorev talimati "Avoid duplicating
    the production SQL in a way that could silently diverge")."""
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


def final_baglam_sec(soru, tenant_id, departman_id, soru_str, kullanici_id, rol, zamanlama=None):
    """RAG V2 CHECKPOINT 2: routed departman icinde authorized DENSE top-
    FINAL_ADAY_TOP_K aday cekilir (final_adaylari_getir - AYNI yetkilendirme
    predikati, DEGISMEDI), reranker_ile_sirala ile YENIDEN siralanir, ilk
    FINAL_BAGLAM_K parca NIHAI KANIT olarak secilir.

    Bu liste, hem LLM'e giden BAGLAM hem provenance'in TEK KAYNAGIDIR (bkz.
    gorev talimati "PROVENANCE - CRITICAL") - baska HICBIR asamadan (router
    adaylari, final dense top-10'un reranker'da kaybeden geri kalani, esik
    altinda kalan herhangi bir aday) kaynak/baglam TURETILMEZ.

    TEKILLESTIRME YAPILMAZ - ayni belgeden birden fazla parca tamamlayici
    olabilir (bkz. gorev talimati "FINAL EVIDENCE"), ikisi de secilebilir;
    dense siralama DEGIL, reranker sirasi KORUNUR (provenance'in kendi
    tekillestirmesi SONRADAN, cevapla() icinde, belge_id'ye gore ayrica
    yapilir - bu SADECE goruntuleme icindir, LLM'e giden 'secilen' listesini
    ETKILEMEZ).

    DONER: (final_kanit, dense_top_skor).
    - final_kanit: final_adaylari_getir'in kendi satir sekliyle (metin,
      dense_skor, belge_id, dosya_adi), reranker sirasina gore, ilk
      FINAL_BAGLAM_K (daha az aday varsa hepsi).
    - dense_top_skor: authorized aday havuzunun EN YUKSEK dense (cosine)
      skoru - ESKI ESIK karsilastirmasinin kullandigi AYNI deger
      (adaylar[0][1], final_adaylari_getir zaten dense ORDER BY ile
      donuyor). ARTIK HICBIR KARARI ETKILEMEZ - SADECE cevapla()'nin donus
      degerindeki 'skor' alaninin ESKI, geriye-donuk-uyumlu anlamini
      korumak icin tasinir (bkz. gorev talimati "PRESERVE /sor CONTRACT").

    Hic authorized aday yoksa ([], 0) doner - cagiran bunu MEVCUT "bilgi
    yok" davranisiyla ele alir, reranker bu durumda HIC CAGRILMAZ.
    """
    t0 = time.perf_counter() if zamanlama is not None else None
    adaylar = final_adaylari_getir(tenant_id, departman_id, soru_str, kullanici_id, rol, FINAL_ADAY_TOP_K)
    if zamanlama is not None:
        zamanlama["final_sql"] = time.perf_counter() - t0
        zamanlama["final_aday_n"] = len(adaylar)
    if not adaylar:
        return [], 0

    dense_top_skor = adaylar[0][1]

    # final_adaylari_getir'in satir sekli: (metin, skor, belge_id,
    # dosya_adi) - metin ilk eleman (indeks 0).
    t1 = time.perf_counter() if zamanlama is not None else None
    siralanmis = reranker_ile_sirala(soru, adaylar, metin_al=lambda aday: aday[0])
    if zamanlama is not None:
        # Router asamasindaki AYNI not gecerli: reranker_al() tekil oldugu
        # icin model SADECE ilk cagrida yuklenir - bir istekte HEM router
        # HEM final rerank calisirsa, model yukleme suresi SADECE router_
        # rerank'a (ilk cagrilan) yansir, final_rerank zaten SICAK olur.
        zamanlama["final_rerank"] = time.perf_counter() - t1
    final_kanit = [aday for aday, _rerank_skoru in siralanmis[:FINAL_BAGLAM_K]]
    if zamanlama is not None:
        zamanlama["final_kanit_n"] = len(final_kanit)
    return final_kanit, dense_top_skor


def _zamanlama_yazdir(zamanlama):
    """LATENCY DIAGNOSTICS: tek satirlik, hassas-olmayan bir tanı satiri
    yazdirir - SADECE cevapla() RAG_TIMING_ACIK iken cagirir. .env/token/
    sifre/baglanti dizesi/tam kullanici mesaji/belge icerigi/parca metni HIC
    yazilmaz - sadece asama sureleri (saniye) ve kucuk sayimlar (bkz. gorev
    talimati "DO NOT log ... full user messages ... sensitive chunk
    text")."""
    print(
        "[RAG_TIMING] "
        f"contextualize={zamanlama.get('contextualize', 0.0):.2f}s "
        f"embed={zamanlama.get('embed', 0.0):.2f}s "
        f"router_sql={zamanlama.get('router_sql', 0.0):.2f}s "
        f"router_rerank={zamanlama.get('router_rerank', 0.0):.2f}s "
        f"final_sql={zamanlama.get('final_sql', 0.0):.2f}s "
        f"final_rerank={zamanlama.get('final_rerank', 0.0):.2f}s "
        f"llm={zamanlama.get('llm', 0.0):.2f}s "
        f"total={zamanlama.get('total', 0.0):.2f}s "
        "| "
        f"gecmis={zamanlama.get('gecmis_n', 0)} "
        f"router_aday={zamanlama.get('router_aday_n', 0)} "
        f"final_aday={zamanlama.get('final_aday_n', 0)} "
        f"final_kanit={zamanlama.get('final_kanit_n', 0)}"
    )


def cevapla(soru, tenant_id, departman_id=None, kullanici_id=None, rol=None, gecmis=None):
    # kullanici_id / rol: servis.py'den gelen GUVENILIR .NET kimligi - hem
    # departman_yonlendir (ADIM C4) hem asagidaki asil getirme (ADIM C3)
    # yetkilendirme predikatinde kullanilir.

    # LATENCY DIAGNOSTICS CHECKPOINT: zamanlama, RAG_TIMING=1 DEGILSE None -
    # asagidaki HER "if zamanlama is not None" kontrolu bu durumda ATLANIR,
    # bayrak kapaliyken tek ekstra maliyet bu ucuz None-kontrolleridir (bkz.
    # gorev talimati "default behavior ... must remain unchanged except for
    # negligible timing-code overhead"). finally bloğu, HANGI return
    # yolundan cikilirsa cikilsin (erken "departman bulunamadi"/"kanit yok"/
    # "yetersiz kanit" ya da basarili yol) toplam sureyi dogru olcer ve TEK
    # bir satir yazdirir.
    zamanlama = {} if RAG_TIMING_ACIK else None
    t_toplam = time.perf_counter() if zamanlama is not None else None
    try:
        # RAG V2 CHECKPOINT 3 (kisa konusma hafizasi): gecmis - .NET'in AYNI
        # sohbetten, AYNI kullaniciya ait (tenant_id+eposta scoped), yeni soru
        # DB'ye YAZILMADAN ONCE cekilmis en fazla son 2 mesaji (bkz.
        # Index.cshtml.cs::OncekiMesajlariGetir) - baska bir sohbetten/
        # kullanicidan/tenant'tan asla gelemez, bu GUVENIRLIK zaten .NET
        # tarafinda SAGLANMISTIR, burada TEKRAR SORGULANMAZ.
        #
        # gecmis BOSSA/None ise (ilk soru ya da .NET hic gondermedi)
        # baglamsallastir() HIC CAGRILMAZ - EKSTRA saglayici istegi YOK, soru
        # AYNEN kullanilir; davranis eskisiyle BIREBIR AYNI kalir (bkz. gorev
        # talimati "no history / first question -> current behavior exactly as
        # today"). Aksi halde soru, SADECE bu kisa gecmisi kullanarak BAGIMSIZ/
        # standalone bir retrieval sorusuna donusturulur - bu donusturulmus soru
        # embedding/routing/reranking/final retrieval/final cevap uretimi icin
        # KULLANILIR (bkz. gorev talimati "WHICH QUESTION GOES WHERE"). Onceki
        # asistan cevaplari bu adimda SADECE referans cozmek icin kullanilir,
        # otorite bir kanit DEGILDIR - nihai cevap HALA SADECE asagidaki final
        # RAG kanitindan (final_kanit) gelir, bu adim SADECE retrieval sorgusunu
        # iyilestirir.
        if zamanlama is not None:
            zamanlama["gecmis_n"] = len(gecmis) if gecmis else 0
        t0 = time.perf_counter() if zamanlama is not None else None
        retrieval_sorusu = baglamsallastir(soru, gecmis) if gecmis else soru
        if zamanlama is not None:
            # gecmis yoksa baglamsallastir() zaten hic CAGRILMADI - LATENCY
            # DIAGNOSTICS gorev talimati "0 / skipped when there is no
            # history" geregi burada acikca 0.0 yazilir, ELAPSED SURE
            # ATLANIR (olculecek bir sey yok).
            zamanlama["contextualize"] = (time.perf_counter() - t0) if gecmis else 0.0

        # TEK encode - hem yonlendirme sorgusu hem asagidaki asil getirme AYNI
        # soru_str'i kullanir, ikinci bir model.encode() cagrisi YAPILMAZ.
        t0 = time.perf_counter() if zamanlama is not None else None
        soru_v = model.encode(retrieval_sorusu, normalize_embeddings=True)
        soru_str = str(soru_v.tolist())
        if zamanlama is not None:
            zamanlama["embed"] = time.perf_counter() - t0

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
            departman_id, _router_skoru = departman_yonlendir(retrieval_sorusu, tenant_id, soru_str, kullanici_id, rol, zamanlama)
            if departman_id is None:
                return YETERSIZ_KANIT_CEVABI, 0, None, []

        # RAG V2 CHECKPOINT 2: final_baglam_sec, ROUTED departman icindeki
        # yetkilendirme predikatini (final_adaylari_getir icinde, DEGISMEDI)
        # HER ZAMAN reranker'dan ONCE uygular, sonra authorized dense top-
        # FINAL_ADAY_TOP_K'yi reranker ile yeniden siralayip ilk FINAL_BAGLAM_K
        # parcayi NIHAI KANIT olarak dondurur (bkz. final_baglam_sec docstring'i
        # - "PROVENANCE - CRITICAL" notu). ESIK ARTIK burada KARSILASTIRILMAZ.
        final_kanit, dense_top_skor = final_baglam_sec(retrieval_sorusu, tenant_id, departman_id, soru_str, kullanici_id, rol, zamanlama)

        if not final_kanit:
            # Routed departmanda HICBIR yetkili aday yok - guvenli "bilgi yok"
            # yolu, LLM HIC CAGRILMAZ (verilecek baglam yok). Eskiden bu ESIK'in
            # "0 satir" dali ile AYNI davranistı - sadece artik "esik altinda
            # kaldi" nedeni YOK, sadece "aday hic yok" nedeni var.
            return YETERSIZ_KANIT_CEVABI, dense_top_skor, departman_id, []

        # secilen: reranker SIRASINDA, TEKILLESTIRME OLMADAN - ayni belgeden
        # birden fazla parca gelmisse (tamamlayici olabilir, bkz. gorev talimati
        # "FINAL EVIDENCE") HEPSI LLM'e gider. Nihai cevap uretimi de
        # retrieval_sorusu'nu kullanir - final cevap LLM'i (llm.py::sor) hicbir
        # konusma gecmisi GORMEZ, SADECE "BAGLAM + SORU" gorur; orijinal ham
        # "Peki hafta sonu?" gonderilseydi bu LLM icin de eksik/anlamsiz
        # kalirdi (bkz. gorev talimati "smallest clean approach").
        secilen = [aday[0] for aday in final_kanit]
        t0 = time.perf_counter() if zamanlama is not None else None
        cevap_metni = sor(retrieval_sorusu, secilen)
        if zamanlama is not None:
            zamanlama["llm"] = time.perf_counter() - t0

        # LLM'in KENDISI, sunulan NIHAI kanidin soruyu YETERSIZ karsiladigina
        # karar verebilir (bkz. llm.py rule 2/3 + YETERSIZ_KANIT_CEVAPLARI - bu
        # sabit kume, LLM'in SISTEM promptunda HARFIYEN uretmeye ZORLANDIGI iki
        # cumleyle BIREBIR AYNI, tek kaynaktan gelir). Bu durumda kaynaklar da
        # BOS doner - UI'da "Kaynaklar: X.pdf" gosterip hemen altinda "yeterli
        # bilgi yok" demek YANILTICI olurdu. Kontrol TAM ESITLIK - fuzzy bir
        # substring/regex TAHMINI DEGIL (bkz. gorev talimati).
        if cevap_metni in YETERSIZ_KANIT_CEVAPLARI:
            return cevap_metni, dense_top_skor, departman_id, []

        # Kaynaklar SADECE final_kanit'in (LLM'e VERILEN, reranker sirali NIHAI
        # kanit) belgelerinden olusur - baska HICBIR aday havuzundan (router,
        # dense top-10'un reranker'da kaybeden geri kalani) provenance
        # TURETILMEZ. Ilk-gorulme sirasi korunarak belge_id'ye gore
        # TEKILLESTIRILIR - ayni belgeden birden fazla parca gelmisse
        # (bkz. PROJECT_MAP.md "Top-K provenance semantics") tek bir kaynak
        # satiri olarak gorunur. Bu tekillestirme SADECE goruntuleme icindir -
        # LLM'e giden 'secilen' listesi (yukarida) TEKILLESTIRILMEMISTI.
        kaynaklar = []
        gorulen_belgeler = set()
        for aday in final_kanit:
            belge_id, dosya_adi = aday[2], aday[3]
            if belge_id in gorulen_belgeler:
                continue
            gorulen_belgeler.add(belge_id)
            kaynaklar.append({"belge_id": belge_id, "dosya_adi": dosya_adi})

        return cevap_metni, dense_top_skor, departman_id, kaynaklar
    finally:
        if zamanlama is not None:
            zamanlama["total"] = time.perf_counter() - t_toplam
            _zamanlama_yazdir(zamanlama)




if __name__ == "__main__":
    cevap, skor, departman_id, kaynaklar = cevapla("kasa sayımını kim yapar", "english-home")
    print(skor, departman_id, kaynaklar, cevap)