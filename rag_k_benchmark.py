"""RAG V2 K-azaltma diagnostik benchmark'i - CHECKPOINT: SADECE tani/olcum.

Amac: router/final reranker'a giden authorized dense aday sayisini (K)
10 -> 8 -> 6 azaltmanin ROUTER SECIMINI ve FINAL KANITI nasil etkiledigini
GERCEK, yetkilendirilmis verilerle olcmek - production K sabitlerini
DEGISTIRMEDEN. sorgu.py::ROUTER_TOP_K / FINAL_ADAY_TOP_K / FINAL_BAGLAM_K bu
dosyanin HICBIR YERINDE modifiye edilmez/yeniden atanmaz - SADECE zaten
authorized+dense-sirali olarak cekilmis top-10'un ILK 10/8/6 satiri
diagnostik amacli KESILIR (slice). Bu, production'in bugun zaten yaptigi
"ORDER BY skor, LIMIT N" ile AYNI semantik - K'yi kucultmek, SQL'in kendi
LIMIT'ini kucultmus olmakla ESDEGERDIR (ayni sirali listenin bir on-eki).

Yetkilendirme/SQL TEKRARI YOK: bu script kendi SQL'ini/kendi rol simulasyonunu
YAZMAZ - sorgu.py'nin authorized fonksiyonlarini (departman_adaylari_getir,
final_adaylari_getir, reranker_ile_sirala) HIC DEGISTIRMEDEN cagirir; profil
cozumleme (kullanici_id/tenant_id/rol) rag_benchmark.py::profil_coz'den AYNEN
yeniden kullanilir - sahte bir rol/erisim seviyesi UYDURULMAZ, yetkilendirme
HER ZAMAN reranking'den ONCE, SQL'in kendisinde tamamlanir (production ile
BIREBIR AYNI sira).

KRITIK_SORULAR listesindeki notlar SADECE bu script'in kendi ciktisinda
gosterilen diagnostik METADATA'dir - production kodunun/sorgu.py'nin
HICBIR YERINE yazilmaz/import edilmez, hicbir departman/belge eslemesi
hardcode EDILMEZ. "Beklenen kanit" kavrami da UYDURULMUS bir cevap DEGIL -
K=10'un (BUGUNKU production davranisi) GERCEKTEN urettigi nihai kanit,
SADECE K=8/K=6 ile karsilastirma REFERANSI olarak kullanilir.

Model isinma (warm-up): CrossEncoder (bkz. reranker.py::reranker_al) tembel
tekil - AYNI Python surecinde ilk cagrida yuklenir. Bu script, K
karsilastirmalarina BASLAMADAN ONCE, BIR KEZ, ayri/etiketlenmis bir isinma
cagrisi yapar (reranker_al() dogrudan) - boylece asagidaki TUM K=10/8/6
zamanlamalari (router VE final, TUM sorular icin) SICAK/karsilastirilabilir
olur; model yukleme suresi ayri satirda raporlanir, hicbir K'ye KARISTIRILMAZ.

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
    ayni_mi_k10: bool = True
    rerank_sn: float = 0.0


@dataclass
class FinalKSonucu:
    k: int
    aday_sayisi: int
    kanit_belgeleri: list = field(default_factory=list)  # [(belge_id, dosya_adi, rerank_skoru), ...]
    beklenen_kanit_mevcut: Optional[bool] = None  # None: K=10 (referansin kendisi) icin tanimsiz
    kanit_farkli_mi_k10: bool = False
    rerank_sn: float = 0.0


@dataclass
class KKarsilastirmaSonucu:
    soru: str
    not_: Optional[str]
    router: list = field(default_factory=list)     # list[RouterKSonucu], K_DEGERLERI sirasinda
    routed_departman_id_k10: Optional[int] = None
    final: list = field(default_factory=list)       # list[FinalKSonucu], K_DEGERLERI sirasinda


def router_k_karsilastir(soru: str, soru_str: str, profil: TestProfili) -> list:
    """Authorized dense top-K_MAKS aday havuzunu TEK SQL cagrisiyla ceker
    (sorgu.py::departman_adaylari_getir - production'daki AYNI fonksiyon,
    AYNI yetkilendirme predikati), sonra bu TEK sirali listenin ilk
    K_DEGERLERI satirini diagnostik amacli KESER ve HER K icin reranker'i
    (sorgu.py::reranker_ile_sirala - production ile PAYLASILAN AYNI kod)
    AYRI AYRI calistirir. Ikinci/ucuncu bir SQL cagrisi YOK - sadece bellek
    icinde slice."""
    dense_k_maks = departman_adaylari_getir(
        profil.tenant_id, soru_str, profil.kullanici_id, profil.rol, K_MAKS
    )

    sonuclar = []
    k10_departman_id = None
    for k in K_DEGERLERI:
        adaylar_k = dense_k_maks[:k]
        if not adaylar_k:
            sonuclar.append(RouterKSonucu(k, 0, None, ayni_mi_k10=(k10_departman_id is None)))
            continue

        t0 = time.perf_counter()
        siralanmis = reranker_ile_sirala(soru, adaylar_k, metin_al=lambda a: a[4])
        sure = time.perf_counter() - t0

        en_iyi_aday, en_iyi_skor = siralanmis[0]
        dep_id, _skor, belge_id, dosya_adi, _metin = en_iyi_aday

        if k == K_DEGERLERI[0]:
            k10_departman_id = dep_id

        sonuclar.append(RouterKSonucu(
            k=k, aday_sayisi=len(adaylar_k), departman_id=dep_id,
            belge_id=belge_id, dosya_adi=dosya_adi, rerank_skoru=en_iyi_skor,
            ayni_mi_k10=(dep_id == k10_departman_id), rerank_sn=round(sure, 4),
        ))

    dep_idler = {s.departman_id for s in sonuclar if s.departman_id is not None}
    adlar = _departman_adlari(profil.tenant_id, dep_idler)
    for s in sonuclar:
        if s.departman_id is not None:
            s.departman_adi = adlar.get(s.departman_id)

    return sonuclar


def final_k_karsilastir(soru: str, soru_str: str, profil: TestProfili, departman_id: Optional[int]) -> list:
    """AYNI mantik, final asamasi icin: sorgu.py::final_adaylari_getir ile
    TEK SQL cagrisinda authorized dense top-K_MAKS ceker (routed departman
    K=10 router sonucuna gore SABIT tutulur - final K'nin duyarliligini
    router K'den AYRISTIRMAK icin, bkz. gorev talimati "After determining
    the expected/correct routed department, compare K=10/8/6"), sonra ilk
    K_DEGERLERI satirini keser ve HER K icin ayri reranker cagirir.

    "beklenen kanit": K=10'un (bugunku production davranisi) GERCEKTEN
    urettigi nihai FINAL_BAGLAM_K kanitindaki belge_id kumesi - SADECE
    karsilastirma REFERANSI, hicbir sekilde retrieval/yetkilendirme
    mantigini ETKILEMEZ. K=8/K=6 icin iki ayri sey raporlanir:
      - dense asamada (reranktan ONCE) o referans belge_id'lerden en az
        biri hala K'nin dense aday havuzunda mi (yoksa K KESIMI onu
        BASTAN elemis mi)
      - final kanit (reranktan SONRA, ilk FINAL_BAGLAM_K) K=10'unkinden
        FARKLI mi (belge_id kumesi karsilastirmasi)."""
    if departman_id is None:
        return [FinalKSonucu(k=k, aday_sayisi=0) for k in K_DEGERLERI]

    dense_k_maks = final_adaylari_getir(
        profil.tenant_id, departman_id, soru_str, profil.kullanici_id, profil.rol, K_MAKS
    )

    sonuclar = []
    k10_kanit_belge_idler = None
    for k in K_DEGERLERI:
        adaylar_k = dense_k_maks[:k]
        if not adaylar_k:
            sonuclar.append(FinalKSonucu(k=k, aday_sayisi=0, beklenen_kanit_mevcut=False, kanit_farkli_mi_k10=True))
            continue

        t0 = time.perf_counter()
        siralanmis = reranker_ile_sirala(soru, adaylar_k, metin_al=lambda a: a[0])
        sure = time.perf_counter() - t0

        # final_baglam_sec ile BIREBIR AYNI kural: ilk FINAL_BAGLAM_K,
        # reranker sirasinda, TEKILLESTIRME YOK.
        kanit = siralanmis[:FINAL_BAGLAM_K]
        kanit_belgeleri = [(aday[2], aday[3], round(skoru, 4)) for aday, skoru in kanit]
        kanit_belge_idler = {aday[2] for aday, _skoru in kanit}

        if k == K_DEGERLERI[0]:
            k10_kanit_belge_idler = kanit_belge_idler
            beklenen_mevcut = None  # referansin kendisi - "farkli mi" anlamsiz
            farkli_mi = False
        else:
            dense_k_belge_idler = {a[2] for a in adaylar_k}
            beklenen_mevcut = bool(k10_kanit_belge_idler & dense_k_belge_idler) if k10_kanit_belge_idler else False
            farkli_mi = kanit_belge_idler != k10_kanit_belge_idler

        sonuclar.append(FinalKSonucu(
            k=k, aday_sayisi=len(adaylar_k), kanit_belgeleri=kanit_belgeleri,
            beklenen_kanit_mevcut=beklenen_mevcut, kanit_farkli_mi_k10=farkli_mi,
            rerank_sn=round(sure, 4),
        ))

    return sonuclar


def k_karsilastir(soru: str, not_: Optional[str], profil: TestProfili) -> KKarsilastirmaSonucu:
    """TEK giris noktasi - bir soru icin router VE final K karsilastirmasini
    baştan sona calistirir. Embedding TEK KEZ hesaplanir (router ve final
    icin AYNI soru_str kullanilir - production cevapla() ile AYNI desen)."""
    soru_v = model.encode(soru, normalize_embeddings=True)
    soru_str = str(soru_v.tolist())

    router_sonuclari = router_k_karsilastir(soru, soru_str, profil)
    routed_k10 = router_sonuclari[0].departman_id if router_sonuclari else None

    final_sonuclari = final_k_karsilastir(soru, soru_str, profil, routed_k10)

    return KKarsilastirmaSonucu(
        soru=soru, not_=not_, router=router_sonuclari,
        routed_departman_id_k10=routed_k10, final=final_sonuclari,
    )


def yazdir(sonuc: KKarsilastirmaSonucu, detay: bool = False) -> None:
    print(f"\nSORU: {sonuc.soru}")
    if sonuc.not_:
        print(f"  not: {sonuc.not_}")

    print("  ROUTER")
    for r in sonuc.router:
        if r.departman_id is None:
            print(f"    K={r.k:2d}  aday yok (authorized departman-etiketli parca yok)")
            continue
        etiket = "" if r.ayni_mi_k10 else "  <-- FARKLI (K=10'dan sapiyor)"
        print(
            f"    K={r.k:2d}  aday={r.aday_sayisi:2d}  secilen={r.departman_adi or '?'}(id={r.departman_id})"
            f"  rerank_skoru={r.rerank_skoru:.4f}  sure={r.rerank_sn:.3f}s"
            f"  {'SAME' if r.ayni_mi_k10 else 'DIFFERENT'}{etiket}"
        )

    routed_adi = sonuc.router[0].departman_adi if sonuc.router else None
    print(f"  FINAL (routed departman - K=10 router sonucu SABIT tutuldu: {routed_adi or '-'} id={sonuc.routed_departman_id_k10})")
    for f in sonuc.final:
        if f.aday_sayisi == 0:
            print(f"    K={f.k:2d}  aday yok")
            continue
        if f.k == K_DEGERLERI[0]:
            mevcut_metni = "- (referans)"
        else:
            mevcut_metni = "EVET" if f.beklenen_kanit_mevcut else "HAYIR  <-- kesildi!"
        farkli_metni = "-" if f.k == K_DEGERLERI[0] else ("EVET  <-- degisti" if f.kanit_farkli_mi_k10 else "HAYIR")
        print(
            f"    K={f.k:2d}  aday={f.aday_sayisi:2d}  beklenen_kanit_mevcut={mevcut_metni}"
            f"  final_kanit_farkli_mi_k10={farkli_metni}  sure={f.rerank_sn:.3f}s"
        )
        if detay:
            for belge_id, dosya_adi, skor in f.kanit_belgeleri:
                print(f"        belge_id={belge_id}  {dosya_adi}  rerank_skoru={skor}")


# --- KRITIK REGRESYON SORULARI ---
# Bu liste ve icindeki notlar SADECE bu diagnostik script'in kendi
# ciktisinda gosterilir - production kodunun (sorgu.py, servis.py,
# Index.cshtml.cs) HICBIR YERINE yazilmaz/import edilmez. Hicbir departman/
# belge_id/dosya_adi eslemesi burada hardcode EDILMEZ - notlar SADECE
# insan-okunur hatirlatmalardir, retrieval/yetkilendirme kararini
# ETKILEMEZ (bkz. modul docstring'i).
KRITIK_SORULAR = [
    (
        "magaza kac saat acik",
        "Bilinen onceki bulgu: dogru Magaza Operasyonlari parcasi dense "
        "rank 1 DEGILDI (bkz. audit) - K azaltma bu parcayi router/final "
        "dense havuzundan TAMAMEN kesebilir, asagidaki 'beklenen_kanit_"
        "mevcut'/'FARKLI' alanlarina dikkat.",
    ),
    ("mağaza saat kacta acilir", None),
    ("Hasarlı koli gelirse ne yapmamız gerekiyor?", None),
    (
        "Mars'taki English Home mağazası saat kaçta açılıyor?",
        "Desteklenmeyen/niteleyici soru - dogru davranis 'yeterli kanit "
        "yok'. K azaltmanin bunu YANLISLIKLA degistirip degistirmedigini "
        "kontrol et (final kanit kumesi degisirse cevaplanabilirlik "
        "davranisi da degisebilir - LLM cagrisi bu script'te YAPILMAZ, "
        "SADECE kanit kumesi karsilastirilir).",
    ),
    (
        "Mağaza sabah kaçta açılıyor ve personelin açılıştan kaç dakika önce mağazada olması gerekiyor?",
        "Coklu-gercek soru (acilis saati + varis suresi) - final K azaltma "
        "iki AYRI parcaya ihtiyac duyan bu soru icin ikinci gercegi kanit "
        "disi birakabilir mi kontrol et.",
    ),
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
             "verilmezse mevcut KRITIK_SORULAR listesi calisir.",
    )
    ayristirici.add_argument(
        "--detay", action="store_true",
        help="Her K icin final kanit belgelerinin (belge_id/dosya_adi/rerank_skoru) tam listesini de yazdir.",
    )
    args = ayristirici.parse_args()

    profil = profil_coz(args.eposta)
    if profil is None:
        print(f"'{args.eposta}' icin kullanicilar tablosunda kayit bulunamadi.")
        raise SystemExit(1)

    # MODEL ISINMASI: K karsilastirmalarina baslamadan ONCE, BIR KEZ, AYRI
    # etiketlenmis bir cagri - reranker_al() tembel tekili burada yukler,
    # asagidaki TUM K=10/8/6 zamanlamalari (router+final, TUM sorular) SICAK
    # olur. Bu sure asagidaki hicbir K karsilastirmasina KARISTIRILMAZ.
    isinma_basla = time.perf_counter()
    reranker_al()
    isinma_sn = time.perf_counter() - isinma_basla
    print(f"[warm-up] reranker modeli yuklendi: {isinma_sn:.2f}s (asagidaki K sureleri buna DAHIL DEGIL, hepsi SICAK)")

    sorular = [(s, None) for s in args.soru] if args.soru else KRITIK_SORULAR

    toplam_basla = time.perf_counter()
    tum_sonuclar = []
    for soru, not_ in sorular:
        sonuc = k_karsilastir(soru, not_, profil)
        tum_sonuclar.append(sonuc)
        yazdir(sonuc, detay=args.detay)

    # --- OZET: K basina ORTALAMA rerank suresi (router + final, TUM sorular) ---
    print("\n=== OZET: K basina ortalama SICAK rerank suresi ===")
    for i, k in enumerate(K_DEGERLERI):
        router_sureler = [s.router[i].rerank_sn for s in tum_sonuclar if s.router[i].aday_sayisi > 0]
        final_sureler = [s.final[i].rerank_sn for s in tum_sonuclar if s.final[i].aday_sayisi > 0]
        r_ort = sum(router_sureler) / len(router_sureler) if router_sureler else 0.0
        f_ort = sum(final_sureler) / len(final_sureler) if final_sureler else 0.0
        print(f"  K={k:2d}  router_rerank_ort={r_ort:.3f}s ({len(router_sureler)} soru)  final_rerank_ort={f_ort:.3f}s ({len(final_sureler)} soru)")

    print(f"\n=== toplam benchmark suresi: {time.perf_counter() - toplam_basla:.2f} sn ({len(sorular)} soru, warm-up haric) ===")
