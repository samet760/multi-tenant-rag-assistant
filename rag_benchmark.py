"""RAG V2 tani/benchmark araci - CHECKPOINT: SADECE tani altyapisi.

Bu script PRODUCTION RAG davranisini DEGISTIRMEZ. Yetkilendirme kararini
VEREN tek yer sorgu.py (departman_adaylari_getir + final_adaylari_getir)
olarak KALIR - bu script kendi SQL'ini/kendi yetkilendirme predikatini ASLA
yazmaz, sadece sorgu.py'nin AYNI, tek yerde tanimli fonksiyonlarini cagirir.
Reranker skorlama da AYNI sekilde sorgu.py::reranker_ile_sirala (production
ile PAYLASILAN tek kod) uzerinden yapilir - bu script kendi predict()/sort
mantigini KOPYALAMAZ.

DUZELTME 1 (tani semantigi): LLM baglami ile provenance FARKLI seyler -
baglam (final_kanit_parcalari) TEKILLESTIRME OLMADAN reranker sirasindaki
ilk FINAL_BAGLAM_K parcadir; provenance (final_provenance_belgeleri) bu AYNI
parcalarin belge_id'ye gore SONRADAN tekillestirilmis hali. Biri digerinin
YERINE GECEMEZ/ADI OLARAK KULLANILAMAZ.

DUZELTME 2 (profil cozumleme): kullanici_id/tenant_id/rol elle YAZILMAZ -
"--eposta" ile verilen bir e-posta, SALT-OKUNUR tek bir SELECT ile mevcut
kullanicilar tablosundan cozulur (bkz. profil_coz). rol HER ZAMAN bu
sorgudan gelir, CLI'dan asla ezilemez/uydurulamaz. sifre_ozeti (hash) dahil
hicbir sir okunmaz/yazdirilmaz.

RAG V2 CHECKPOINT 1 (router reranking): sorgu.py::departman_yonlendir
production icinde authorized dense top-ROUTER_TOP_K adayi BAAI/bge-
reranker-v2-m3 ile yeniden siralar - bu HER ZAMAN calisir (bayrakla
GIZLENMEZ), bu yuzden bu script de router kazananini/tam aday listesini
HER ZAMAN gosterir - "opsiyonel" bir --rerank bayragina ARTIK GEREK YOK.

RAG V2 CHECKPOINT 2 (final retrieval reranking + ESIK'in emekliye
ayrilmasi): sorgu.py::final_baglam_sec, routed departman icinde authorized
dense top-FINAL_ADAY_TOP_K adayi AYNI reranker ile yeniden siralar, ilk
FINAL_BAGLAM_K parcayi NIHAI KANIT olarak secer - LLM'e giden VE
provenance'i belirleyen TEK kaynak budur. ESIK ARTIK production'da HICBIR
KARARI ETKILEMEZ (bkz. sorgu.py'deki RETIRED notu) - nihai cevaplanabilirlik
karari llm.py'nin deterministik YETERSIZ_KANIT_CEVAPLARI sozlesmesine ait.
Bu script ESIK'i SADECE acikca "[LEGACY diagnostic only]" etiketiyle,
tarihsel karsilastirma icin gosterir - production kararinin bir parcasi
OLARAK SUNULMAZ.

Kullanim (elle, CLI):
    python rag_benchmark.py --eposta test2@gmail.com
    python rag_benchmark.py --eposta test2@gmail.com --soru "magaza kac saat acik"
    python rag_benchmark.py --eposta test2@gmail.com --soru "magaza kac saat acik" --cevap-uret
"""

import argparse
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import psycopg
from dotenv import load_dotenv

from embed import model
from sorgu import (
    ESIK,
    FINAL_ADAY_TOP_K,
    FINAL_BAGLAM_K,
    cevapla,
    departman_adaylari_getir,
    departman_yonlendir,
    final_adaylari_getir,
    reranker_ile_sirala,
)

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")

# Router tani amacli aday havuzu genisligi - production'in ROUTER_TOP_K'siyla
# (sorgu.py) AYNI deger, ayri bir sabit olarak (production/tani birbirinden
# BAGIMSIZ kalsin diye).
TANI_TOP_K = 10


@dataclass
class TestProfili:
    """Kimlik dogrulanmis test profili - GUVENILIR .NET kimliginin (bkz.
    servis.py::SoruIstegi / Giris.cshtml.cs) test ortamindaki karsiligi.
    profil_coz() tarafindan kullanicilar tablosundan COZULUR - elle
    UYDURULMAZ (bkz. asagisi)."""

    ad: str
    tenant_id: str
    kullanici_id: int
    rol: str


@dataclass
class AdayParca:
    rank: int
    skor: float
    belge_id: int
    dosya_adi: str
    metin_onizleme: str


@dataclass
class RouterAdayi:
    rank: int
    skor: float
    departman_id: int
    departman_adi: Optional[str]
    belge_id: int
    dosya_adi: str
    metin_onizleme: str


@dataclass
class DepartmanOzeti:
    departman_id: int
    departman_adi: Optional[str]
    en_iyi_skor: float
    en_iyi_rank: int
    aday_sayisi: int


@dataclass
class RerankAdayi:
    rerank_rank: int
    rerank_skoru: float
    dense_rank: int
    dense_skor: float
    departman_id: Optional[int]
    departman_adi: Optional[str]
    belge_id: int
    dosya_adi: str
    metin_onizleme: str


@dataclass
class BenchmarkSonucu:
    soru: str
    profil_adi: str
    tenant_id: str
    kullanici_id: int
    rol: str

    # --- ROUTER (bkz. sorgu.py::departman_yonlendir) ---
    routed_departman_id: Optional[int]
    routed_departman_adi: Optional[str]
    router_skoru: Optional[float]  # departman_yonlendir'in reranker skoru - PRODUCTION kazanani
    router_dense_top10: list = field(default_factory=list)   # departman_adaylari_getir, dense sira
    router_departman_ozet: list = field(default_factory=list)
    router_rerank_top10: list = field(default_factory=list)  # AYNI adaylar, reranker_ile_sirala ile TAM liste
    router_rerank_sn: Optional[float] = None

    # --- FINAL RETRIEVAL (routed departman icinde, bkz. sorgu.py::final_baglam_sec) ---
    final_dense_top10: list = field(default_factory=list)    # final_adaylari_getir, dense sira
    final_rerank_top10: list = field(default_factory=list)   # AYNI adaylar, reranker_ile_sirala ile TAM liste
    final_rerank_sn: Optional[float] = None
    final_kanit_parcalari: list = field(default_factory=list)     # final_rerank_top10[:FINAL_BAGLAM_K] - NIHAI KANIT
    final_provenance_belgeleri: list = field(default_factory=list)  # final_kanit_parcalari'ndan TEKILLESTIRILMIS

    # --- LEGACY diagnostic only - ESIK production'da ARTIK KULLANILMIYOR ---
    legacy_dense_top_skor: float = 0.0
    legacy_esik_kabul_ederdi: bool = False

    cevap: Optional[str] = None
    sure_sn: float = 0.0


def profil_coz(eposta: str) -> Optional[TestProfili]:
    """Test profilini ID/rol UYDURMADAN, dogrudan mevcut kullanicilar
    tablosundan COZER - salt-okunur, tek SELECT. sifre_ozeti (hash) dahil
    HICBIR SIR okunmaz/yazdirilmaz. rol BURADAN gelir, cagirandan/CLI'dan
    ASLA elle verilmez/ezilmez - bu arac boylece gercekte var olmayan bir
    yetki seviyesini SIMULE EDEMEZ. Kayit yoksa None doner."""
    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(
                "select id, tenant_id, rol from kullanicilar where eposta = %s",
                (eposta,),
            )
            satir = imlec.fetchone()

    if satir is None:
        return None

    kullanici_id, tenant_id, rol = satir
    return TestProfili(ad=eposta, tenant_id=tenant_id, kullanici_id=kullanici_id, rol=rol)


def _departman_adi(tenant_id: str, departman_id: Optional[int]) -> Optional[str]:
    """Departman adini SADECE goruntuleme icin cozer - yetkilendirme
    ICERMEZ/ETKILEMEZ (arayuz/Pages/*.cshtml.cs'teki id+tenant_id ile scoped,
    salt-okunur lookup deseniyle AYNI - hangi parcalarin gorulebildigini
    DEGIL, sadece zaten donen bir id'nin adini soyler)."""
    if departman_id is None:
        return None
    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(
                "select ad from departmanlar where id = %s and tenant_id = %s",
                (departman_id, tenant_id),
            )
            satir = imlec.fetchone()
    return satir[0] if satir else None


def _departman_adlari(tenant_id: str, departman_idler) -> dict:
    """Birden fazla departman adini TEK sorguda cozer (id = ANY(...)) -
    router top-10'daki HER benzersiz departman icin AYRI bir sorgu atmamak
    icin (bkz. gorev talimati "Avoid N+1 queries"). Salt-okunur,
    yetkilendirme ICERMEZ/ETKILEMEZ - _departman_adi ile AYNI id+tenant_id
    scoped lookup deseni, sadece toplu."""
    departman_idler = list(set(departman_idler))
    if not departman_idler:
        return {}
    with psycopg.connect(URL) as baglanti:
        with baglanti.cursor() as imlec:
            imlec.execute(
                "select id, ad from departmanlar where tenant_id = %s and id = any(%s)",
                (tenant_id, departman_idler),
            )
            return {satir[0]: satir[1] for satir in imlec.fetchall()}


def calistir(soru: str, profil: TestProfili, cevap_uret: bool = False) -> BenchmarkSonucu:
    """TEK giris noktasi: sorgu.py'nin production-authoritative
    fonksiyonlarini (departman_yonlendir, departman_adaylari_getir,
    final_adaylari_getir, reranker_ile_sirala) HIC DEGISTIRMEDEN cagirir -
    kendi SQL'ini/kendi reranking mantigini ASLA yazmaz. Router VE final
    reranking artik production'da HER ZAMAN calistigi icin (bkz. RAG V2
    CHECKPOINT 1/2), bu fonksiyon da ikisini de HER ZAMAN hesaplar - ayrik
    bir "--rerank" bayragina ARTIK GEREK YOK. cevap_uret=True verilirse,
    AYRICA production cevapla()'yi (gercek LLM cevabi icin) de cagirir -
    varsayilan False, boylece gunluk tani calistirmalari OpenRouter'a istek
    ATMAZ/ucret DOGURMAZ."""
    basla = time.time()

    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    # --- ROUTER ---
    # departman_yonlendir production icinde ARTIK HER ZAMAN reranker
    # kullaniyor (bkz. sorgu.py, RAG V2 CHECKPOINT 1) - bu satir HER ZAMAN
    # production'in GERCEKTEN sececegi departmani/skoru gosterir.
    departman_id, router_skoru = departman_yonlendir(
        soru, profil.tenant_id, soru_str, profil.kullanici_id, profil.rol
    )

    sonuc = BenchmarkSonucu(
        soru=soru,
        profil_adi=profil.ad,
        tenant_id=profil.tenant_id,
        kullanici_id=profil.kullanici_id,
        rol=profil.rol,
        routed_departman_id=departman_id,
        routed_departman_adi=_departman_adi(profil.tenant_id, departman_id),
        router_skoru=router_skoru,
    )

    router_adaylari = departman_adaylari_getir(
        profil.tenant_id, soru_str, profil.kullanici_id, profil.rol, TANI_TOP_K
    )
    if router_adaylari:
        dep_adlari = _departman_adlari(profil.tenant_id, (r[0] for r in router_adaylari))

        ozet_by_dep: dict = {}
        for i, (r_dep_id, r_skor, r_belge_id, r_dosya_adi, r_metin) in enumerate(router_adaylari, start=1):
            sonuc.router_dense_top10.append(
                RouterAdayi(i, r_skor, r_dep_id, dep_adlari.get(r_dep_id), r_belge_id, r_dosya_adi, r_metin[:120])
            )
            # Satirlar zaten skor ORDER BY'a gore siralanmis geldigi icin
            # bir departmanin ILK GORULDUGU satir otomatik onun EN IYI
            # adayi/rank'i olur.
            if r_dep_id not in ozet_by_dep:
                ozet_by_dep[r_dep_id] = DepartmanOzeti(r_dep_id, dep_adlari.get(r_dep_id), r_skor, i, 1)
            else:
                ozet_by_dep[r_dep_id].aday_sayisi += 1
        sonuc.router_departman_ozet = list(ozet_by_dep.values())

        # Router'in TAM reranker siralamasi - departman_yonlendir'in ZATEN
        # kullandigi AYNI (yukarida zaten cekilmis) satirlar uzerinde,
        # sorgu.py::reranker_ile_sirala (production ile PAYLASILAN tek kod)
        # ile - ikinci bir SQL sorgusu YOK. id() ile dense_rank haritalanir -
        # reranker_ile_sirala AYNI tuple nesnelerini dondurur, KOPYALAMAZ.
        dense_rank_by_id = {id(a): i for i, a in enumerate(router_adaylari, start=1)}
        rerank_basla = time.time()
        router_siralanmis = reranker_ile_sirala(soru, router_adaylari, metin_al=lambda a: a[4])
        sonuc.router_rerank_sn = round(time.time() - rerank_basla, 2)
        for rerank_rank, (aday, rerank_skoru) in enumerate(router_siralanmis, start=1):
            r_dep_id, r_skor, r_belge_id, r_dosya_adi, r_metin = aday
            sonuc.router_rerank_top10.append(
                RerankAdayi(
                    rerank_rank, rerank_skoru, dense_rank_by_id[id(aday)], r_skor,
                    r_dep_id, dep_adlari.get(r_dep_id), r_belge_id, r_dosya_adi, r_metin[:120],
                )
            )

    # --- FINAL RETRIEVAL (routed departman icinde) ---
    if departman_id is not None:
        final_dense_adaylar = final_adaylari_getir(
            profil.tenant_id, departman_id, soru_str, profil.kullanici_id, profil.rol, FINAL_ADAY_TOP_K
        )

        for i, (metin, skor, belge_id, dosya_adi) in enumerate(final_dense_adaylar, start=1):
            sonuc.final_dense_top10.append(AdayParca(i, skor, belge_id, dosya_adi, metin[:120]))

        if final_dense_adaylar:
            # LEGACY diagnostic only - ESIK production'da ARTIK KULLANILMIYOR
            # (bkz. sorgu.py RETIRED notu). Sadece tarihsel karsilastirma.
            sonuc.legacy_dense_top_skor = final_dense_adaylar[0][1]
            sonuc.legacy_esik_kabul_ederdi = sonuc.legacy_dense_top_skor >= ESIK

            # FINAL RERANKER TOP 10 - final_adaylari_getir'in AYNI (yukarida
            # zaten cekilmis) satirlari uzerinde, ikinci bir SQL YOK. Bu,
            # production'in final_baglam_sec'inin GERCEKTEN hesapladigi AYNI
            # siralamadir (AYNI paylasilan reranker_ile_sirala fonksiyonu).
            final_dense_rank_by_id = {id(a): i for i, a in enumerate(final_dense_adaylar, start=1)}
            rerank_basla = time.time()
            final_siralanmis = reranker_ile_sirala(soru, final_dense_adaylar, metin_al=lambda a: a[0])
            sonuc.final_rerank_sn = round(time.time() - rerank_basla, 2)
            for rerank_rank, (aday, rerank_skoru) in enumerate(final_siralanmis, start=1):
                metin, dense_skor, belge_id, dosya_adi = aday
                sonuc.final_rerank_top10.append(
                    RerankAdayi(
                        rerank_rank, rerank_skoru, final_dense_rank_by_id[id(aday)], dense_skor,
                        departman_id, sonuc.routed_departman_adi, belge_id, dosya_adi, metin[:120],
                    )
                )

            # NIHAI KANIT: production final_baglam_sec ile BIREBIR AYNI kural
            # - ilk FINAL_BAGLAM_K, reranker sirasinda, TEKILLESTIRME YOK.
            sonuc.final_kanit_parcalari = sonuc.final_rerank_top10[:FINAL_BAGLAM_K]

            # Provenance SADECE final_kanit_parcalari'ndan, belge_id'ye gore
            # TEKILLESTIRILEREK (goruntuleme icin) - baska hicbir aday
            # havuzundan (router, dense top-10'un reranker'da kaybeden geri
            # kalani) TURETILMEZ (bkz. gorev talimati "PROVENANCE - CRITICAL").
            gorulen = set()
            for a in sonuc.final_kanit_parcalari:
                if a.belge_id in gorulen:
                    continue
                gorulen.add(a.belge_id)
                sonuc.final_provenance_belgeleri.append({"belge_id": a.belge_id, "dosya_adi": a.dosya_adi})

    if cevap_uret:
        cevap, _skor, _dep, _kaynaklar = cevapla(
            soru, profil.tenant_id, None, profil.kullanici_id, profil.rol
        )
        sonuc.cevap = cevap

    sonuc.sure_sn = round(time.time() - basla, 2)
    return sonuc


def yazdir(sonuc: BenchmarkSonucu) -> None:
    print(f"\n=== {sonuc.soru}")
    print(f"    profil            : {sonuc.profil_adi} (tenant={sonuc.tenant_id}, kullanici_id={sonuc.kullanici_id}, rol={sonuc.rol})")

    print("\n    --- ROUTER ---")
    print(f"    routed departman  : {sonuc.routed_departman_adi or '-'} (id={sonuc.routed_departman_id})  reranker skoru={sonuc.router_skoru if sonuc.router_skoru is not None else '-'}")
    print(f"    router dense top-{TANI_TOP_K} (departman_adaylari_getir, chunk duzeyinde):")
    if sonuc.router_dense_top10:
        for a in sonuc.router_dense_top10:
            print(f"      {a.rank:2d}. skor={a.skor:.3f}  dep={a.departman_adi or '?'}(id={a.departman_id})  belge_id={a.belge_id}  {a.dosya_adi}  | {a.metin_onizleme}...")
    else:
        print("      (router adayi yok - tenant'in yetkili hicbir departman-etiketli parcasi yok)")
    print("    departman bazli router ozeti:")
    if sonuc.router_departman_ozet:
        for o in sonuc.router_departman_ozet:
            print(f"      {o.departman_adi or '?'} (id={o.departman_id}): en iyi skor={o.en_iyi_skor:.3f} (rank {o.en_iyi_rank}), top-{TANI_TOP_K} icinde {o.aday_sayisi} aday")
    else:
        print("      (yok)")
    print(f"    router reranker top-{TANI_TOP_K} (sure: {sonuc.router_rerank_sn} sn):")
    if sonuc.router_rerank_top10:
        for a in sonuc.router_rerank_top10:
            print(f"      {a.rerank_rank:2d}. rerank_skoru={a.rerank_skoru:.4f}  dense(rank={a.dense_rank}, skor={a.dense_skor:.3f})  dep={a.departman_adi or '?'}(id={a.departman_id})  belge_id={a.belge_id}  {a.dosya_adi}  | {a.metin_onizleme}...")
    else:
        print("      (yok)")

    print("\n    --- FINAL RETRIEVAL (routed departman icinde) ---")
    print(f"    final dense top-{FINAL_ADAY_TOP_K} (final_adaylari_getir):")
    if sonuc.final_dense_top10:
        for a in sonuc.final_dense_top10:
            print(f"      {a.rank:2d}. skor={a.skor:.3f}  belge_id={a.belge_id}  {a.dosya_adi}  | {a.metin_onizleme}...")
    else:
        print("      (aday yok - routed departman yok ya da bu departmanda yetkili parca yok)")

    print(f"\n    FINAL RERANKER TOP {FINAL_ADAY_TOP_K} (sure: {sonuc.final_rerank_sn} sn):")
    if sonuc.final_rerank_top10:
        for a in sonuc.final_rerank_top10:
            isaret = "*" if a.rerank_rank <= FINAL_BAGLAM_K else " "
            print(f"      {isaret}{a.rerank_rank:2d}. rerank_skoru={a.rerank_skoru:.4f}  dense(rank={a.dense_rank}, skor={a.dense_skor:.3f})  belge_id={a.belge_id}  {a.dosya_adi}  | {a.metin_onizleme}...")
    else:
        print("      (yok)")

    print(f"\n    NIHAI KANIT (ilk {FINAL_BAGLAM_K}, reranker sirasi - LLM'e giden AYNEN bu, production final_baglam_sec ile BIREBIR AYNI):")
    if sonuc.final_kanit_parcalari:
        for a in sonuc.final_kanit_parcalari:
            print(f"      {a.rerank_rank:2d}. rerank_skoru={a.rerank_skoru:.4f}  belge_id={a.belge_id}  {a.dosya_adi}")
    else:
        print("      (yok - LLM HIC CAGRILMAZDI, 'bilgi yok' donerdi)")

    print("    provenance (belge_id'ye gore TEKILLESTIRILMIS, SADECE nihai kanitten):")
    if sonuc.final_provenance_belgeleri:
        for b in sonuc.final_provenance_belgeleri:
            print(f"      belge_id={b['belge_id']}  {b['dosya_adi']}")
    else:
        print("      (yok)")

    print("\n    [LEGACY diagnostic only - ESIK production'da ARTIK KULLANILMIYOR]")
    print(f"    ESIK={ESIK} vs en iyi final dense skor={sonuc.legacy_dense_top_skor:.3f} -> eski kural {'KABUL ederdi' if sonuc.legacy_esik_kabul_ederdi else 'RED ederdi'}")

    if sonuc.cevap is not None:
        print(f"\n    cevap             : {sonuc.cevap}")

    print(f"\n    sure              : {sonuc.sure_sn} sn")


# Sorular UYDURULMADI - hepsi mevcut test dosyalarindan (cevap_test.py /
# benzerlik_test.py) BIREBIR alindi, artı gorev talimatinda acikca istenen
# iki gercek prob ("saat kacta acilir" / "magaza kac saat acik").
PROBLAR = [
    "saat kacta acilir",             # bilinen BASARILI prob (bkz. audit)
    "magaza kac saat acik",          # bilinen BASARISIZ prob (bkz. audit, skor~0.45)
    "en iyi pizza nerede",           # acikca alakasiz - bkz. benzerlik_test.py
    "kasa sayımını kim yapar",       # farkli departman ornegi - bkz. cevap_test.py (VAR)
    "yıllık zam oranı kaç",          # farkli departman ornegi - bkz. cevap_test.py (YOK)
]


if __name__ == "__main__":
    ayristirici = argparse.ArgumentParser(description="RAG V2 tani/benchmark araci")
    ayristirici.add_argument(
        "--eposta", required=True,
        help="Test profili olarak kullanilacak GERCEK kullanici e-postasi - "
             "kullanici_id/tenant_id/rol buradan (kullanicilar tablosundan) cozulur.",
    )
    ayristirici.add_argument(
        "--soru", default=None,
        help="Tek bir ozel soru calistir - verilmezse mevcut PROBLAR listesi calisir.",
    )
    ayristirici.add_argument(
        "--cevap-uret", action="store_true",
        help="Ayrica gercek LLM cevabini da uret (OpenRouter'a istek atar, varsayilan KAPALI).",
    )
    args = ayristirici.parse_args()

    profil = profil_coz(args.eposta)
    if profil is None:
        print(f"'{args.eposta}' icin kullanicilar tablosunda kayit bulunamadi.")
    else:
        toplam_basla = time.time()
        sorular = [args.soru] if args.soru else PROBLAR
        for soru in sorular:
            yazdir(calistir(soru, profil, cevap_uret=args.cevap_uret))
        print(f"\n=== toplam benchmark suresi: {round(time.time() - toplam_basla, 2)} sn ({len(sorular)} soru) ===")
