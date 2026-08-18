"""RAG V2 tani/benchmark araci - CHECKPOINT: SADECE tani altyapisi.

Bu script PRODUCTION RAG davranisini DEGISTIRMEZ. Yetkilendirme kararini
VEREN tek yer sorgu.py (departman_yonlendir + final_adaylari_getir) olarak
KALIR - bu script kendi SQL'ini/kendi yetkilendirme predikatini ASLA yazmaz,
sadece sorgu.py'nin AYNI, tek yerde tanimli fonksiyonlarini (daha genis bir
LIMIT ile) cagirir. Boylece "yetkisiz bir parcayi gosterebilecek, zamanla
production predikatinden sessizce sapabilecek ikinci bir sorgu" riski hic
OLUSMAZ.

DUZELTME 1 (tani semantigi): CURRENT LLM baglami, TEKILLESTIRME OLMADAN ilk
SON_K parcadir (bkz. sorgu.py::cevapla - secilen = [s[0] for s in satirlar],
satirlar zaten LIMIT SON_K). Provenance ("kaynaklar") ise bu AYNI SON_K
parcanin belge_id'ye gore SONRADAN tekillestirilmis hali - IKISI FARKLI
seyler. Bu script artik ikisini AYRI alanlarda raporluyor, tekillestirilmis
belge listesini "baglam" olarak GOSTERMIYOR.

DUZELTME 2 (profil cozumleme): kullanici_id/tenant_id/rol artik PROFILLER
sozlugune elle YAZILMIYOR - "--eposta" ile verilen bir e-posta, SALT-OKUNUR
tek bir SELECT ile mevcut kullanicilar tablosundan cozuluyor (bkz.
profil_coz). rol HER ZAMAN bu sorgudan gelir, CLI'dan asla ezilemez/uydurulamaz.
sifre_ozeti (hash) dahil hicbir sir okunmaz/yazdirilmaz.

DUZELTME 3 (router aday gorunurlugu): sorgu.py::departman_yonlendir'in SADECE
kazananini degil, TUM yetkili router adaylarini (departman_adaylari_getir,
bkz. sorgu.py) gormek icin eklendi. Bu fonksiyon departman_yonlendir'in
ONCEKI inline sorgusuyla BIREBIR AYNI WHERE/ORDER BY metnini kullanir -
SADECE LIMIT parametrik hale getirildi ve departman_yonlendir artik bu
fonksiyonu limit=1 ile cagirip ilk satiri donduruyor (davranis DEGISMEDI,
kazanan HER ZAMAN aynen ONCEKI gibi secilir - bkz. sorgu.py docstring'i).

Kullanim (elle, CLI):
    python rag_benchmark.py --eposta test2@gmail.com
    python rag_benchmark.py --eposta test2@gmail.com --soru "magaza kac saat acik"
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
    SON_K,
    cevapla,
    departman_adaylari_getir,
    departman_yonlendir,
    final_adaylari_getir,
)

load_dotenv()
URL = os.getenv("SUPABASE_DB_URL")

# Tani amacli aday havuzu genisligi - production'in SON_K'sindan (3) BUYUK,
# "esigi gecemeyen ama aslinda dogru olan" veya "top-3'e bile girmeyen"
# adaylari GOREBILMEK icin (bkz. RAG V2 audit "retrieval recall failure").
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
class BenchmarkSonucu:
    soru: str
    profil_adi: str
    tenant_id: str
    kullanici_id: int
    rol: str
    routed_departman_id: Optional[int]
    routed_departman_adi: Optional[str]
    router_skoru: Optional[float]
    # Router'in TUM yetkili adaylari (kazanan DAHIL) + departman bazli ozet -
    # bkz. DUZELTME 3. Ikisi de departman_adaylari_getir'in TEK sorgusundan
    # gelir, ekstra per-aday/per-departman sorgu YOK (departman adlari toplu
    # cozulur, bkz. _departman_adlari).
    router_top10: list = field(default_factory=list)
    router_departman_ozet: list = field(default_factory=list)
    ilk_10_aday: list = field(default_factory=list)
    esik_kabul_etti: bool = False
    top_skor: float = 0.0
    # DUZELTME 1: ikisi ARTIK AYRI. mevcut_llm_baglam_parcalari = production
    # cevapla()'nin GERCEKTEN LLM'e verdigi ilk SON_K parca (TEKILLESTIRME
    # YOK - ayni belgeden 2 parca gelmisse ikisi de burada gorunur).
    # mevcut_provenance_belgeleri = bu AYNI parcalarin belge_id'ye gore
    # SONRADAN tekillestirilmis hali (production'in "kaynaklar" ile AYNI
    # mantik). Biri digerinin YERINE GECEMEZ/ADI OLARAK KULLANILAMAZ.
    mevcut_llm_baglam_parcalari: list = field(default_factory=list)
    mevcut_provenance_belgeleri: list = field(default_factory=list)
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
    """TEK giris noktasi: sorgu.py::departman_yonlendir + sorgu.py::
    final_adaylari_getir'i HIC DEGISTIRMEDEN, sadece daha genis bir LIMIT
    ile cagirir - kendi SQL'ini ASLA yazmaz. cevap_uret=True verilirse,
    AYRICA production cevapla()'yi (gercek LLM cevabi icin) de cagirir -
    varsayilan False, boylece gunluk tani calistirmalari OpenRouter'a istek
    ATMAZ/ucret DOGURMAZ; router+retrieval tanisi icin buna gerek yok."""
    basla = time.time()

    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    departman_id, router_skoru = departman_yonlendir(
        profil.tenant_id, soru_str, profil.kullanici_id, profil.rol
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

    # DUZELTME 3: departman_yonlendir'in (yukarida) sectigi TEK kazananin
    # OTESINDE, AYNI yetkilendirme-filtreli predikatle TUM router adaylarini
    # (ilk TANI_TOP_K) getirir - sorgu.py::departman_adaylari_getir, kendi
    # SQL'i YOK. Departman_id None ise (hic yetkili aday yoksa) bu da bos
    # kalir - departman_yonlendir zaten ayni sebepten None dondurmus olur.
    router_adaylari = departman_adaylari_getir(
        profil.tenant_id, soru_str, profil.kullanici_id, profil.rol, TANI_TOP_K
    )
    if router_adaylari:
        dep_adlari = _departman_adlari(
            profil.tenant_id, (r[0] for r in router_adaylari)
        )
        ozet_by_dep: dict = {}
        for i, (r_dep_id, r_skor, r_belge_id, r_dosya_adi, r_metin) in enumerate(
            router_adaylari, start=1
        ):
            sonuc.router_top10.append(
                RouterAdayi(
                    i, r_skor, r_dep_id, dep_adlari.get(r_dep_id),
                    r_belge_id, r_dosya_adi, r_metin[:120],
                )
            )
            # Satirlar zaten skor ORDER BY'a gore siralanmis geldigi icin
            # bir departmanin ILK GORULDUGU satir otomatik olarak onun EN
            # IYI adayi/rank'i olur - ayrica karsilastirma GEREKMEZ.
            if r_dep_id not in ozet_by_dep:
                ozet_by_dep[r_dep_id] = DepartmanOzeti(
                    r_dep_id, dep_adlari.get(r_dep_id), r_skor, i, 1
                )
            else:
                ozet_by_dep[r_dep_id].aday_sayisi += 1
        sonuc.router_departman_ozet = list(ozet_by_dep.values())

    if departman_id is not None:
        satirlar = final_adaylari_getir(
            profil.tenant_id, departman_id, soru_str, profil.kullanici_id, profil.rol, TANI_TOP_K
        )

        for i, (metin, skor, belge_id, dosya_adi) in enumerate(satirlar, start=1):
            sonuc.ilk_10_aday.append(
                AdayParca(i, skor, belge_id, dosya_adi, metin[:120])
            )

        if satirlar:
            sonuc.top_skor = satirlar[0][1]
            sonuc.esik_kabul_etti = sonuc.top_skor >= ESIK

        # DUZELTME 1: sorgu.py::cevapla ESIK'i KABUL ederse, satirlar'in
        # (burada TANI_TOP_K=10 ile cekilmis olsa da, siralama/ilk SON_K
        # AYNI) ilk SON_K'si HICBIR TEKILLESTIRME olmadan LLM baglamina
        # girer - production'daki "secilen" degiskeninin BIREBIR karsiligi.
        # Provenance ("kaynaklar") ise bu AYNI SON_K parcanin belge_id'ye
        # gore SONRADAN tekillestirilmis hali - ayri, ikincil bir gorunum.
        if sonuc.esik_kabul_etti:
            sonuc.mevcut_llm_baglam_parcalari = sonuc.ilk_10_aday[:SON_K]

            gorulen = set()
            for aday in sonuc.mevcut_llm_baglam_parcalari:
                if aday.belge_id in gorulen:
                    continue
                gorulen.add(aday.belge_id)
                sonuc.mevcut_provenance_belgeleri.append(
                    {"belge_id": aday.belge_id, "dosya_adi": aday.dosya_adi}
                )

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

    # 1. Router kazanani (production departman_yonlendir'in DONDURDUGU deger).
    print(f"    [1] router kazanani: {sonuc.routed_departman_adi or '-'} (id={sonuc.routed_departman_id}), skor={sonuc.router_skoru if sonuc.router_skoru is not None else '-'}")

    # 2. Router'in ilk TANI_TOP_K adayi - CHUNK duzeyinde, TEKILLESTIRME YOK.
    print(f"    [2] router adaylari (ilk {TANI_TOP_K}, chunk duzeyinde):")
    if sonuc.router_top10:
        for a in sonuc.router_top10:
            isaret = "*" if a.departman_id == sonuc.routed_departman_id and a.rank == 1 else " "
            print(f"      {isaret}{a.rank:2d}. skor={a.skor:.3f}  dep={a.departman_adi or '?'}(id={a.departman_id})  belge_id={a.belge_id}  {a.dosya_adi}  | {a.metin_onizleme}...")
    else:
        print("      (router adayi yok - tenant'in yetkili hicbir departman-etiketli parcasi yok)")

    # 3. Departman bazli ozet - HER departmanin router top-10 icindeki en
    # iyi skoru/rank'i + kac aday getirdigi.
    print(f"    [3] departman bazli router ozeti:")
    if sonuc.router_departman_ozet:
        for o in sonuc.router_departman_ozet:
            print(f"      {o.departman_adi or '?'} (id={o.departman_id}): en iyi skor={o.en_iyi_skor:.3f} (rank {o.en_iyi_rank}), top-{TANI_TOP_K} icinde {o.aday_sayisi} aday")
    else:
        print("      (yok)")

    # 4. Mevcut (production) final getirme - ESIK karari + LLM baglami/
    # provenance + tani icin genisletilmis top-10.
    print(f"    [4] ESIK={ESIK}, SON_K={SON_K} -> {'KABUL' if sonuc.esik_kabul_etti else 'RED'} (en iyi skor={sonuc.top_skor:.3f})")

    print(f"    mevcut LLM baglami (ilk {SON_K} parca, TEKILLESTIRME YOK):")
    if sonuc.mevcut_llm_baglam_parcalari:
        for a in sonuc.mevcut_llm_baglam_parcalari:
            print(f"      {a.rank:2d}. skor={a.skor:.3f}  belge_id={a.belge_id}  {a.dosya_adi}  | {a.metin_onizleme}...")
    else:
        print("      (yok - ESIK reddetti ya da aday bulunamadi)")

    print(f"    mevcut provenance (belge_id'ye gore TEKILLESTIRILMIS):")
    if sonuc.mevcut_provenance_belgeleri:
        for b in sonuc.mevcut_provenance_belgeleri:
            print(f"      belge_id={b['belge_id']}  {b['dosya_adi']}")
    else:
        print("      (yok)")

    if sonuc.cevap is not None:
        print(f"    cevap             : {sonuc.cevap}")

    print(f"    ilk {TANI_TOP_K} aday (tani icin, SON_K sinirini asan diagnostik havuz):")
    for a in sonuc.ilk_10_aday:
        isaret = "*" if a.rank <= SON_K else " "
        print(f"      {isaret}{a.rank:2d}. skor={a.skor:.3f}  {a.dosya_adi}  | {a.metin_onizleme}...")
    if not sonuc.ilk_10_aday:
        print("      (aday yok - routed_departman_id None ya da bu departmanda yetkili parca yok)")

    print(f"    sure              : {sonuc.sure_sn} sn")


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
        sorular = [args.soru] if args.soru else PROBLAR
        for soru in sorular:
            yazdir(calistir(soru, profil, cevap_uret=args.cevap_uret))
