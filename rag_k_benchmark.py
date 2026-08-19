"""RAG V2 K-azaltma diagnostik benchmark'i - CHECKPOINT: SADECE tani/olcum,
GENISLETILMIS (~30 soru) surum. Production K sabitlerini (sorgu.py::
ROUTER_TOP_K / FINAL_ADAY_TOP_K / FINAL_BAGLAM_K) DEGISTIRMEZ/yeniden ATAMAZ -
SADECE zaten authorized+dense-sirali cekilmis top-10'un ILK 10/8/6 satiri
diagnostik amacli KESILIR (slice). Bu, production'in "ORDER BY skor, LIMIT N"
ile AYNI semantik - K'yi kucultmek, SQL'in kendi LIMIT'ini kucultmus olmakla
ESDEGERDIR (ayni sirali listenin bir on-eki).

TEK-RERANK OPTIMIZASYONU (bu checkpoint'te eklendi): onceki surum HER K icin
(10/8/6) reranker'i AYRI AYRI cagiriyordu - ayni CrossEncoder(soru, parca)
ciftleri K=10 icin de K=8/K=6 icin de TEKRAR TEKRAR skorlaniyordu (K=6/K=8
kumeleri zaten K=10 kumesinin bir ALT KUMESI oldugu icin bu tamamen israf).
Simdi HER asama (router / final) icin authorized dense top-10 TEK SQL
cagrisiyla cekilir, reranker_ile_sirala TEK KEZ (tum 10 aday uzerinde)
cagirilir; K=10/8/6 sonuclari bu TEK siralanmis listeden dense_rank<=K
FILTRESIYLE turetilir. Bir listeyi zaten sirali bir alt kumeye filtrelemek
GORECELI sirayi degistirmez, o yuzden bu filtreleme "yeniden siralama"YA
DENK - reranker ikinci/ucuncu kez cagirilmadan AYNI sonuc elde edilir.

Bunun onemli bir yan-sonucu: bir K=10 nihai kanit ogesi, SADECE kendi
dense_rank'i > K oldugunda (yani K kesimiyle aday havuzundan TAMAMEN
dusurulmusse) K'nin kanitinden kaybolabilir - reranker'in kendi "yeniden
siralamasi" bunu ASLA yapamaz (filtrelenmis bir alt kumede bir ogenin
pozisyonu, tam listedeki pozisyonundan ASLA daha kotu olamaz, sadece
esit/daha iyi olabilir - once gelen elemanlar cikarilinca oge yukari kayar).
Bu yuzden asagidaki regresyon teshisi HER ZAMAN "dense_rank(X) > K" bicimini
alir - kod bunu dogrudan gosterir (bkz. kayip_k10_kanitlari).

Yetkilendirme/SQL TEKRARI YOK: bu script kendi SQL'ini/kendi rol simulasyonunu
YAZMAZ - sorgu.py'nin authorized fonksiyonlarini (departman_adaylari_getir,
final_adaylari_getir, reranker_ile_sirala) HIC DEGISTIRMEDEN cagirir; profil
cozumleme (kullanici_id/tenant_id/rol) rag_benchmark.py::profil_coz'den AYNEN
yeniden kullanilir - sahte bir rol/erisim seviyesi UYDURULMAZ.

ROUTER REGRESYONU VARSA FINAL ATLANIR: K=8/K=6 router'i K=10'dan FARKLI bir
departmana yonlendirirse, o soru icin final karsilastirmasi (ikinci pahali
SQL+rerank asamasi) HIC CALISTIRILMAZ - router farki zaten K azaltmayi
guvensiz isaretlemeye YETERLI (gorev talimati "do not perform redundant
expensive final comparisons merely for timing purposes").

Model isinma (warm-up): reranker_al() burada K karsilastirmalarina
BASLAMADAN ONCE, BIR KEZ, ayri/etiketlenmis bir cagriyla yuklenir - asagidaki
TUM router/final rerank sureleri SICAK/karsilastirilabilir olur.

Kullanim (elle, CLI):
    python rag_k_benchmark.py --eposta test2@gmail.com
    python rag_k_benchmark.py --eposta test2@gmail.com --soru "magaza kac saat acik"
    python rag_k_benchmark.py --eposta test2@gmail.com --detay
"""

import argparse
import time
from dataclasses import dataclass, field
from typing import Optional

from embed import model
from reranker import reranker_al
from sorgu import (
    FINAL_BAGLAM_K,
    departman_adaylari_getir,
    final_adaylari_getir,
    reranker_ile_sirala,
)
from rag_benchmark import TestProfili, profil_coz, _departman_adlari

# Karsilastirilacak K degerleri - production sabitleri (ROUTER_TOP_K=10,
# FINAL_ADAY_TOP_K=10) DEGISTIRILMEDEN, SADECE bu script'in kendi dense
# top-10 cekiminden diagnostik amacli KESILIR (bkz. modul docstring'i).
K_DEGERLERI = (10, 8, 6)
K_MAKS = max(K_DEGERLERI)


@dataclass
class RouterKSonucu:
    k: int
    aday_sayisi: int
    departman_id: Optional[int]
    departman_adi: Optional[str] = None
    belge_id: Optional[int] = None
    dosya_adi: Optional[str] = None
    rerank_skoru: Optional[float] = None
    dense_rank: Optional[int] = None  # kazanan adayin ORIJINAL dense sirasi (K_MAKS havuzu icinde)
    ayni_mi_k10: bool = True


@dataclass
class FinalKanitOgesi:
    belge_id: int
    dosya_adi: str
    dense_rank: int
    rerank_skoru: float


@dataclass
class FinalKSonucu:
    k: int
    aday_sayisi: int
    kanit: list = field(default_factory=list)               # list[FinalKanitOgesi], reranker sirasinda ilk FINAL_BAGLAM_K
    farkli_mi_k10: bool = False
    kayip_k10_kanitlari: list = field(default_factory=list)  # K=10 kanitinde olup burada OLMAYAN ogeler (sadece k!=10)


@dataclass
class KKarsilastirmaSonucu:
    soru: str
    kategori: str
    not_: Optional[str]
    router: list = field(default_factory=list)          # list[RouterKSonucu], K_DEGERLERI sirasinda
    router_rerank_sn: Optional[float] = None             # TEK rerank cagrisi - K basina DEGIL
    routed_departman_id_k10: Optional[int] = None
    router_ayni_mi_tum_k: bool = True
    final: list = field(default_factory=list)            # list[FinalKSonucu], K_DEGERLERI sirasinda (bos = atlandi)
    final_rerank_sn: Optional[float] = None               # TEK rerank cagrisi - K basina DEGIL; None = hic calismadi
    final_atlanma_nedeni: Optional[str] = None


def router_k_karsilastir(soru: str, soru_str: str, profil: TestProfili):
    """Authorized dense top-K_MAKS aday havuzunu TEK SQL cagrisiyla ceker,
    reranker'i TEK KEZ (K_MAKS aday uzerinde) calistirir, sonra bu TEK
    siralanmis listeden K_DEGERLERI icin dense_rank<=K FILTRESIYLE (reranker
    tekrar CAGRILMADAN) K basina kazanani turetir."""
    dense_k_maks = departman_adaylari_getir(
        profil.tenant_id, soru_str, profil.kullanici_id, profil.rol, K_MAKS
    )

    if not dense_k_maks:
        return [RouterKSonucu(k=k, aday_sayisi=0, departman_id=None) for k in K_DEGERLERI], None

    dense_rank_by_id = {id(aday): i for i, aday in enumerate(dense_k_maks, start=1)}
    t0 = time.perf_counter()
    siralanmis_maks = reranker_ile_sirala(soru, dense_k_maks, metin_al=lambda a: a[4])
    rerank_sn = time.perf_counter() - t0

    sonuclar = []
    k10_departman_id = None
    for k in K_DEGERLERI:
        alt_kume = [cift for cift in siralanmis_maks if dense_rank_by_id[id(cift[0])] <= k]
        if not alt_kume:
            sonuclar.append(RouterKSonucu(k=k, aday_sayisi=0, departman_id=None,
                                           ayni_mi_k10=(k10_departman_id is None)))
            continue

        en_iyi_aday, en_iyi_skor = alt_kume[0]
        dep_id, _skor, belge_id, dosya_adi, _metin = en_iyi_aday

        if k == K_DEGERLERI[0]:
            k10_departman_id = dep_id

        sonuclar.append(RouterKSonucu(
            k=k, aday_sayisi=len(alt_kume), departman_id=dep_id,
            belge_id=belge_id, dosya_adi=dosya_adi, rerank_skoru=round(en_iyi_skor, 4),
            dense_rank=dense_rank_by_id[id(en_iyi_aday)],
            ayni_mi_k10=(dep_id == k10_departman_id),
        ))

    dep_idler = {s.departman_id for s in sonuclar if s.departman_id is not None}
    adlar = _departman_adlari(profil.tenant_id, dep_idler)
    for s in sonuclar:
        if s.departman_id is not None:
            s.departman_adi = adlar.get(s.departman_id)

    return sonuclar, rerank_sn


def final_k_karsilastir(soru: str, soru_str: str, profil: TestProfili, departman_id: Optional[int]):
    """AYNI mantik, final asamasi icin: routed departman (K=10 router
    sonucuna gore SABIT) icinde authorized dense top-K_MAKS TEK SQL
    cagrisinda cekilir, reranker TEK KEZ calistirilir, K basina nihai kanit
    (ilk FINAL_BAGLAM_K) dense_rank<=K filtresiyle turetilir.

    Kayip kanit teshisi NESNE KIMLIGI (id()) ile yapilir - AYNI (aday, skoru)
    ciftleri K=10/K=8/K=6 arasinda PAYLASILIR (kopyalanmaz), o yuzden "K=10
    kanitindeki bir oge, bu K'nin kanitinde var mi" sorusu tam chunk
    duzeyinde (belge_id'ye indirgemeden) cevaplanabilir."""
    if departman_id is None:
        return [FinalKSonucu(k=k, aday_sayisi=0) for k in K_DEGERLERI], None

    dense_k_maks = final_adaylari_getir(
        profil.tenant_id, departman_id, soru_str, profil.kullanici_id, profil.rol, K_MAKS
    )
    if not dense_k_maks:
        sonuclar = [
            FinalKSonucu(k=k, aday_sayisi=0, farkli_mi_k10=(k != K_DEGERLERI[0]))
            for k in K_DEGERLERI
        ]
        return sonuclar, None

    dense_rank_by_id = {id(aday): i for i, aday in enumerate(dense_k_maks, start=1)}
    t0 = time.perf_counter()
    siralanmis_maks = reranker_ile_sirala(soru, dense_k_maks, metin_al=lambda a: a[0])
    rerank_sn = time.perf_counter() - t0

    sonuclar = []
    k10_kanit_ciftleri = None
    for k in K_DEGERLERI:
        alt_kume = [cift for cift in siralanmis_maks if dense_rank_by_id[id(cift[0])] <= k]
        # final_baglam_sec ile BIREBIR AYNI kural: ilk FINAL_BAGLAM_K,
        # reranker sirasinda (burada: filtrelenmis alt kumenin sirasinda -
        # GORECELI sira reranker'in tam listedeki sirasiyla AYNI), TEKILLESTIRME YOK.
        kanit_ciftleri = alt_kume[:FINAL_BAGLAM_K]
        kanit_ogeleri = [
            FinalKanitOgesi(aday[2], aday[3], dense_rank_by_id[id(aday)], round(skoru, 4))
            for aday, skoru in kanit_ciftleri
        ]

        if k == K_DEGERLERI[0]:
            k10_kanit_ciftleri = kanit_ciftleri
            farkli_mi = False
            kayip = []
        else:
            simdiki_idler = {id(aday) for aday, _s in kanit_ciftleri}
            kayip_ciftleri = [c for c in (k10_kanit_ciftleri or []) if id(c[0]) not in simdiki_idler]
            farkli_mi = bool(kayip_ciftleri)
            kayip = [
                FinalKanitOgesi(aday[2], aday[3], dense_rank_by_id[id(aday)], round(skoru, 4))
                for aday, skoru in kayip_ciftleri
            ]

        sonuclar.append(FinalKSonucu(
            k=k, aday_sayisi=len(alt_kume), kanit=kanit_ogeleri,
            farkli_mi_k10=farkli_mi, kayip_k10_kanitlari=kayip,
        ))

    return sonuclar, rerank_sn


def k_karsilastir(soru: str, kategori: str, not_: Optional[str], profil: TestProfili) -> KKarsilastirmaSonucu:
    """TEK giris noktasi - bir soru icin router VE final K karsilastirmasini
    baştan sona calistirir. Embedding TEK KEZ hesaplanir (production cevapla()
    ile AYNI desen)."""
    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    router_sonuclari, router_rerank_sn = router_k_karsilastir(soru, soru_str, profil)
    routed_k10 = router_sonuclari[0].departman_id if router_sonuclari else None
    router_ayni_mi_tum_k = all(r.ayni_mi_k10 for r in router_sonuclari)

    if routed_k10 is None:
        final_sonuclari = [FinalKSonucu(k=k, aday_sayisi=0) for k in K_DEGERLERI]
        final_rerank_sn = None
        final_atlanma_nedeni = "K=10 icin de hicbir departmana yonlendirilemedi - final karsilastirma anlamsiz."
    elif not router_ayni_mi_tum_k:
        # Gorev talimati: router K=8/K=6'da FARKLIYSA, final karsilastirmasi
        # GEREKSIZ pahali ikinci SQL+rerank asamasini calistirmadan atlanir -
        # router farki zaten bu soru icin K azaltmayi REGRESYON olarak
        # isaretlemeye YETERLI.
        final_sonuclari = []
        final_rerank_sn = None
        final_atlanma_nedeni = "ROUTER REGRESYONU: K=8 ve/veya K=6, K=10'dan FARKLI departmana yonlendirdi - final karsilastirma atlandi."
    else:
        final_sonuclari, final_rerank_sn = final_k_karsilastir(soru, soru_str, profil, routed_k10)
        final_atlanma_nedeni = None

    return KKarsilastirmaSonucu(
        soru=soru, kategori=kategori, not_=not_,
        router=router_sonuclari, router_rerank_sn=router_rerank_sn,
        routed_departman_id_k10=routed_k10, router_ayni_mi_tum_k=router_ayni_mi_tum_k,
        final=final_sonuclari, final_rerank_sn=final_rerank_sn,
        final_atlanma_nedeni=final_atlanma_nedeni,
    )


def yazdir(sonuc: KKarsilastirmaSonucu, detay: bool = False) -> None:
    print(f"\nSORU [{sonuc.kategori}]: {sonuc.soru}")
    if sonuc.not_:
        print(f"  not: {sonuc.not_}")

    print(f"  ROUTER (tek rerank cagrisi: {sonuc.router_rerank_sn:.3f}s)" if sonuc.router_rerank_sn is not None
          else "  ROUTER (aday yok - reranker hic cagrilmadi)")
    for r in sonuc.router:
        if r.departman_id is None:
            print(f"    K={r.k:2d}  aday yok")
            continue
        etiket = "" if r.ayni_mi_k10 else f"  <-- FARKLI (K=10'dan sapiyor, K=10 kazanani dense_rank={sonuc.router[0].dense_rank} idi)"
        print(
            f"    K={r.k:2d}  aday={r.aday_sayisi:2d}  secilen={r.departman_adi or '?'}(id={r.departman_id})"
            f"  dense_rank={r.dense_rank}  rerank_skoru={r.rerank_skoru:.4f}"
            f"  {'SAME' if r.ayni_mi_k10 else 'DIFFERENT'}{etiket}"
        )

    routed_adi = sonuc.router[0].departman_adi if sonuc.router else None
    if sonuc.final_atlanma_nedeni:
        print(f"  FINAL: ATLANDI - {sonuc.final_atlanma_nedeni}")
        return

    print(f"  FINAL (routed departman: {routed_adi or '-'} id={sonuc.routed_departman_id_k10}, "
          f"tek rerank cagrisi: {sonuc.final_rerank_sn:.3f}s)" if sonuc.final_rerank_sn is not None
          else "  FINAL (aday yok - reranker hic cagrilmadi)")
    for f in sonuc.final:
        if f.aday_sayisi == 0:
            print(f"    K={f.k:2d}  aday yok")
            continue
        farkli_metni = "-" if f.k == K_DEGERLERI[0] else ("EVET  <-- degisti" if f.farkli_mi_k10 else "HAYIR")
        print(f"    K={f.k:2d}  aday={f.aday_sayisi:2d}  final_kanit_farkli_mi_k10={farkli_metni}")
        if detay:
            for o in f.kanit:
                print(f"        belge_id={o.belge_id}  {o.dosya_adi}  dense_rank={o.dense_rank}  rerank_skoru={o.rerank_skoru}")
        if f.kayip_k10_kanitlari:
            for o in f.kayip_k10_kanitlari:
                print(f"        KAYIP (K=10'da vardi): belge_id={o.belge_id}  {o.dosya_adi}  "
                      f"dense_rank={o.dense_rank} (>K={f.k} oldugu icin K={f.k} havuzundan kesildi)  rerank_skoru={o.rerank_skoru}")


# --- SORU SETI (~30 soru, gercek korpustan/departman uyeliginden dogrulandi) ---
# Hicbir sirket gercegi UYDURULMADI. Magaza Operasyonlari (departman_id=1) ve
# Urun & Lojistik (departman_id=4) parcalari 'sirket' erisim_seviyesi ile
# authorized/retrieved - icerikleri bu dosyayi hazirlarken DB'den okundu
# (ENGLISH HOME MAGAZA CALISMA YONETMELIGI + urun_lojjistik_test.pdf).
# BULGU (uydurulmadi, DB'den dogrulandi): IT Destek (departman_id=3, 332
# parca) parcalarinin erisim_seviyesi kolonu NULL - sorgu.py'nin WHERE
# predikati ('sirket' VEYA 'departman') NULL ile HICBIR ZAMAN eslesmez, o
# yuzden bu 332 parca su an production'da HICBIR kullanici/rol icin
# CEKILEMEZ (yonetici dahil) - bu MEVCUT production davranisidir, bu script
# TARAFINDAN degistirilmez/duzeltilmez, sadece asagidaki IT sorularinin
# NEDEN kanitsiz/yanlis-yonlendirilmis cikabilecegini ACIKLAR.
# Insan Kaynaklari (departman_id=2) ve Test Departmani Yeni (id=5) icin hic
# parca YOK - HR sorulari bilerek "kapsam disi" olarak etiketlendi (bkz.
# cevap_test.py'deki mevcut YOK ornekleri).
SORU_SETI = [
    # --- Bilinen regresyon sorulari (gorev talimatinda BIREBIR istendi) ---
    ("magaza kac saat acik", "Magaza Operasyonlari / kisa-anahtar-kelime",
     "Bilinen onceki bulgu: dogru parca dense rank 1 DEGILDI (bkz. audit) - "
     "K kesimi bu parcayi havuzdan TAMAMEN dusurebilir."),
    ("mağaza saat kacta acilir", "Magaza Operasyonlari / paraphrase", None),
    ("Hasarlı koli gelirse ne yapmamız gerekiyor?", "Urun & Lojistik", None),
    ("Mars'taki English Home mağazası saat kaçta açılıyor?",
     "Desteklenmeyen nitelik",
     "Dogru davranis 'yeterli kanit yok' (LLM cagrisi burada YAPILMAZ - "
     "sadece kanit kumesi karsilastirilir)."),
    ("Mağaza sabah kaçta açılıyor ve personelin açılıştan kaç dakika önce mağazada olması gerekiyor?",
     "Magaza Operasyonlari / cok-gercek",
     "Iki AYRI gercek (acilis saati + varis suresi, Madde 1 + Madde 2) - "
     "final K azaltma ikinci gercegi kanit disi birakabilir mi kontrol et."),

    # --- Magaza Operasyonlari - genisletilmis ---
    ("mağaza kaçta kapanıyor", "Magaza Operasyonlari / paraphrase", None),
    ("öğle molası kaç dakika sürüyor", "Magaza Operasyonlari / sayisal-kosul", None),
    ("yıllık izin talebi kaç gün önceden yapılmalı", "Magaza Operasyonlari / sayisal-kosul", None),
    ("mazeret izni nasıl alınır", "Magaza Operasyonlari", None),
    ("raporlu personel rapor belgesini ne zaman teslim eder", "Magaza Operasyonlari", None),
    ("ürün iade süresi kaç gün", "Magaza Operasyonlari / sayisal-kosul", None),
    ("yıkanmış ürün iade edilebilir mi", "Magaza Operasyonlari", None),
    ("5000 TL üzerindeki nakit ödemelerde ne istenir", "Magaza Operasyonlari / sayisal-kosul", None),
    ("kasa açığı çıkarsa ne yapılmalı", "Magaza Operasyonlari", None),
    ("müşteri bilgileri üçüncü kişilerle paylaşılabilir mi", "Magaza Operasyonlari", None),
    ("mesai saatinde özel telefon kullanabilir miyim", "Magaza Operasyonlari / paraphrase", None),
    ("tekrar tekrar geç kalırsam ne olur", "Magaza Operasyonlari", None),

    # --- Urun & Lojistik - genisletilmis ---
    ("mal kabul saatleri kaçta", "Urun & Lojistik / sayisal-kosul", None),
    ("kritik stok seviyesi kaç adet", "Urun & Lojistik / sayisal-kosul", None),
    ("mağazalar arası ürün transferi için onay gerekir mi", "Urun & Lojistik", None),
    ("sevkiyat geldiğinde koli sayısı nasıl kontrol edilir", "Urun & Lojistik", None),
    ("hasar kaydı en geç kaç dakika içinde açılmalı", "Urun & Lojistik / sayisal-kosul", None),

    # --- IT - korpusta VAR ama erisim_seviyesi NULL oldugu icin CEKILEMEZ ---
    ("yazıcı çalışmıyor ne yapmalıyım", "IT (korpusta var, erisilemez)",
     "IT Destek'in 332 parcasi erisim_seviyesi=NULL - production WHERE'i "
     "bunlari HICBIR rol icin dondurmez (bkz. modul docstring'i)."),
    ("şifremi unuttum ne yapmalıyım", "IT (korpusta var, erisilemez)", None),

    # --- HR - korpusta hic parca yok (kapsam disi) ---
    ("doğum izni kaç gün", "HR / kapsam-disi", "cevap_test.py'de mevcut YOK ornegi."),
    ("maaşım ne zaman yatar", "HR / kapsam-disi", "cevap_test.py'de mevcut YOK ornegi."),
    ("yıllık zam oranı kaç", "HR / kapsam-disi", "cevap_test.py'de mevcut YOK ornegi."),

    # --- Belirsiz / departmanlar-arasi ---
    ("hasarlı ürün müşteriye nasıl açıklanır", "Belirsiz/departmanlar-arasi",
     "Hem Magaza Operasyonlari (musteri iliskileri) hem Urun & Lojistik "
     "(hasar prosedur) ile kesisebilir."),

    # --- Tamamen alakasiz / cevaplanamaz ---
    ("en iyi pizza nerede", "Cevaplanamaz/alakasiz", None),
    ("python nasıl öğrenilir", "Cevaplanamaz/alakasiz", None),

    # --- Desteklenmeyen sube-ozel nitelik (Mars ornegine benzer) ---
    ("İstanbul Kadıköy şubesi cumartesi günleri kaçta açılıyor?",
     "Desteklenmeyen nitelik",
     "Yonetmelik sube-ozel saat ayrimi ICERMIYOR - dogru davranis genel "
     "kuraldan 'sube-ozel' bir istisna UYDURMAMAK."),
]


if __name__ == "__main__":
    ayristirici = argparse.ArgumentParser(description="RAG V2 K-azaltma (10/8/6) diagnostik benchmark'i")
    ayristirici.add_argument(
        "--eposta", required=True,
        help="Test profili olarak kullanilacak GERCEK kullanici e-postasi - "
             "kullanici_id/tenant_id/rol buradan (kullanicilar tablosundan) cozulur.",
    )
    ayristirici.add_argument(
        "--soru", action="append", default=None,
        help="Ozel bir soru calistir (birden fazla kez verilebilir) - "
             "verilmezse mevcut SORU_SETI listesi calisir.",
    )
    ayristirici.add_argument(
        "--detay", action="store_true",
        help="Her K icin final kanit belgelerinin tam listesini de yazdir.",
    )
    args = ayristirici.parse_args()

    profil = profil_coz(args.eposta)
    if profil is None:
        print(f"'{args.eposta}' icin kullanicilar tablosunda kayit bulunamadi.")
        raise SystemExit(1)

    isinma_basla = time.perf_counter()
    reranker_al()
    isinma_sn = time.perf_counter() - isinma_basla
    print(f"[warm-up] reranker modeli yuklendi: {isinma_sn:.2f}s (asagidaki sureler buna DAHIL DEGIL, hepsi SICAK)")
    print("[not] Bu checkpoint HER asama (router/final) icin adaylari TEK SQL "
          "cagrisiyla ceker ve reranker'i TEK KEZ calistirir; K=10/8/6 "
          "dense_rank filtresiyle TUREVLENIR - reranker K basina TEKRAR CAGRILMAZ.")

    sorular = [(s, "ozel (--soru)", None) for s in args.soru] if args.soru else SORU_SETI

    toplam_basla = time.perf_counter()
    tum_sonuclar = []
    for soru, kategori, not_ in sorular:
        sonuc = k_karsilastir(soru, kategori, not_, profil)
        tum_sonuclar.append(sonuc)
        yazdir(sonuc, detay=args.detay)
    toplam_sn = time.perf_counter() - toplam_basla

    # --- OZET ---
    n = len(sorular)
    router_batch_sureler = [s.router_rerank_sn for s in tum_sonuclar if s.router_rerank_sn is not None]
    final_batch_sureler = [s.final_rerank_sn for s in tum_sonuclar if s.final_rerank_sn is not None]

    router_k8_farkli = [s for s in tum_sonuclar if len(s.router) > 1 and not s.router[1].ayni_mi_k10]
    router_k6_farkli = [s for s in tum_sonuclar if len(s.router) > 2 and not s.router[2].ayni_mi_k10]
    final_k8_farkli = [s for s in tum_sonuclar if len(s.final) > 1 and s.final[1].farkli_mi_k10]
    final_k6_farkli = [s for s in tum_sonuclar if len(s.final) > 2 and s.final[2].farkli_mi_k10]

    print("\n" + "=" * 70)
    print(f"QUESTIONS: {n}")
    print("\nROUTER")
    print(f"K8 vs K10 differences: {len(router_k8_farkli)}")
    print(f"K6 vs K10 differences: {len(router_k6_farkli)}")
    print("\nFINAL EVIDENCE")
    print(f"K8 vs K10 material differences: {len(final_k8_farkli)}")
    print(f"K6 vs K10 material differences: {len(final_k6_farkli)}")

    tum_regresyonlar = sorted({s.soru for s in (router_k8_farkli + router_k6_farkli + final_k8_farkli + final_k6_farkli)})
    print("\nREGRESSIONS:")
    if not tum_regresyonlar:
        print("none")
    else:
        for soru in tum_regresyonlar:
            s = next(x for x in tum_sonuclar if x.soru == soru)
            print(f"  - [{s.kategori}] {soru}")
            if not s.router_ayni_mi_tum_k:
                k10 = s.router[0]
                for r in s.router[1:]:
                    if not r.ayni_mi_k10:
                        print(f"      ROUTER K={r.k}: {k10.departman_adi}(id={k10.departman_id}, dense_rank={k10.dense_rank}) "
                              f"-> {r.departman_adi}(id={r.departman_id}) "
                              f"| K=10 kazanani dense_rank={k10.dense_rank} > K={r.k} oldugu icin havuzdan dustu")
            for f in s.final:
                if f.farkli_mi_k10:
                    for o in f.kayip_k10_kanitlari:
                        print(f"      FINAL K={f.k}: kaybedilen kanit belge_id={o.belge_id} ({o.dosya_adi}) "
                              f"-> orijinal dense rank {o.dense_rank} idi (>K={f.k}) -> K={f.k} bu adayi dusurdu")

    print("\n=== SICAK rerank sureleri (K basina DEGIL - stage basina TEK cagri) ===")
    if router_batch_sureler:
        print(f"  router: {len(router_batch_sureler)} batch, ortalama={sum(router_batch_sureler)/len(router_batch_sureler):.3f}s")
    else:
        print("  router: hic batch calismadi")
    if final_batch_sureler:
        print(f"  final : {len(final_batch_sureler)} batch, ortalama={sum(final_batch_sureler)/len(final_batch_sureler):.3f}s")
    else:
        print("  final : hic batch calismadi (tum sorularda router regresyonu/aday yoktu)")

    print("\n=== Aday-hesabi azalmasi (KAVRAMSAL - OLCULMUS gecikme DEGIL) ===")
    print("  K=10 -> baseline (10 (soru, parca) cifti reranker'a gider)")
    print("  K=8  -> %20 daha az aday cifti")
    print("  K=6  -> %40 daha az aday cifti")
    print("  (Gercek CrossEncoder gecikmesi input uzunluguna/batch'e/donanima "
          "bagli olarak DOGRUSAL OLMAYABILIR - bu satirlar SADECE aday sayisi "
          "azalmasini gosterir, olculmus bir hiz artisi IDDIA ETMEZ.)")

    if not router_k6_farkli and not final_k6_farkli:
        karar = "K=6 SAFE ENOUGH FOR PRODUCTION CHECKPOINT"
    elif not router_k8_farkli and not final_k8_farkli:
        karar = "TRY K=8"
    else:
        karar = "KEEP K=10"
    print(f"\n=== PRODUCTION KARARI: {karar} ===")
    print("=== (production sabitleri bu script tarafindan DEGISTIRILMEDI) ===")

    print(f"\n=== toplam benchmark suresi: {toplam_sn:.2f} sn ({n} soru, warm-up haric) ===")
