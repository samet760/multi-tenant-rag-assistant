import os
import requests
from dotenv import load_dotenv

load_dotenv()
ANAHTAR = os.getenv("OPENROUTER_API_KEY")

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMServisHatasi(Exception):
    """RAG V2 GUVENILIRLIK CHECKPOINT: saglayici (OpenRouter) hatasini
    normal bir cevap METNINDEN AYRISTIRAN tipli istisna - onceki denetimde
    bulunan ana kusuru (saglayici hatasi "[HATA 429] ..." gibi duz bir
    METIN olarak donup sorgu.py::cevapla tarafindan NORMAL, KAYNAKLI bir
    cevap gibi ele alinmasi) giderir. SADECE GUVENLI/kucuk metadata tasir -
    HAM saglayici govdesi/stack trace/prompt/soru/parca metni/API anahtari
    BURADA HICBIR ZAMAN saklanmaz (bkz. gorev talimati "Do NOT carry or
    expose raw API response bodies unnecessarily").

    kategori: kisa, sabit bir metin etiketi (orn. "kota", "yogunluk") -
    servis.py'nin FastAPI govdesine AYNEN yazdigi deger.
    http_durum: FastAPI'nin /sor uzerinden DISARI verecegi HTTP durumu.
    kullanici_mesaji: UI'da GOSTERILECEK, tamamen guvenli/onceden yazilmis
    Turkce cumle - saglayicinin HAM metnini ASLA icermez.
    ust_durum: OpenRouter'in kendi HTTP durumu (varsa) - SADECE sunucu
    tarafi tanı loguna yazilir (bkz. _hata_logla), kullaniciya asla
    gosterilmez."""

    def __init__(self, kategori, http_durum, kullanici_mesaji, ust_durum=None):
        self.kategori = kategori
        self.http_durum = http_durum
        self.kullanici_mesaji = kullanici_mesaji
        self.ust_durum = ust_durum
        super().__init__(f"LLMServisHatasi: kategori={kategori} ust_durum={ust_durum}")


# Deterministik "yetersiz kanit" sozlesmesi - sorgu.py::cevapla ile
# PAYLASILIR (bkz. gorev talimati "Use a deterministic contract... one or
# more canonical exact refusal responses/constants"). SISTEM promptu
# asagida LLM'i bu IKI cumleyi HARFIYEN/SADECE bu haliyle uretmeye
# ZORLAR - sorgu.py fuzzy bir substring/regex TAHMINI yapmaz, sadece bu
# SABIT kumeye TAM ESITLIK kontrolu yapar. Tek kaynak: bu iki sabit HEM
# SISTEM promptunun icine gomulur HEM sorgu.py'ye import edilir - iki
# yerde ayri ayri yazilmis bir metin ASLA olmaz, o yuzden sessizce
# SAPAMAZLAR.
YETERSIZ_KANIT_CEVABI = "Bu bilgi dokümanlarda yer almıyor."
YETERSIZ_KANIT_NITELEYICI_CEVABI = "Bu özel durumla ilgili elimde yeterli şirket bilgisi bulunmuyor."
YETERSIZ_KANIT_CEVAPLARI = frozenset({YETERSIZ_KANIT_CEVABI, YETERSIZ_KANIT_NITELEYICI_CEVABI})

SISTEM = (
    "You are a document lookup assistant for a company's internal Turkish "
    "corporate documents. Follow these rules exactly.\n"
    "1. Every corporate factual claim in your answer must come ONLY from "
    "facts written literally in the CONTEXT. Never invent a corporate rule, "
    "number, date, name, or policy that is not present in the CONTEXT.\n"
    "2. QUALIFIER CHECK: identify any important qualifier in the user's "
    "question - for example a location, a specific date/time period, an "
    "employee role, a department, a specific product, a system/application, "
    "an exception or condition, a specific branch/store, or a numeric "
    "condition. Before applying a CONTEXT fact to answer, check whether the "
    "CONTEXT actually supports that SPECIFIC qualifier, not just a "
    "generally related topic. Never guess, reinterpret, or substitute an "
    "unfamiliar or unsupported qualifier with something else it superficially "
    "resembles (for example, do not treat an unrecognized place name as a "
    "month, a code, or any other reinterpretation) - treat it exactly as "
    "written and only ask whether the CONTEXT supports it as such. If the "
    "CONTEXT only contains a general rule and does NOT specifically support "
    "the qualifier asked about, output EXACTLY this and nothing else: "
    + YETERSIZ_KANIT_NITELEYICI_CEVABI + " "
    "Do NOT also state the general/unqualified fact in the same answer, even "
    "as background, context, or a partial answer, and do NOT add any other "
    "sentence before or after it.\n"
    "3. If the CONTEXT contains NO relevant information at all for the "
    "question, output EXACTLY this and nothing else: "
    + YETERSIZ_KANIT_CEVABI + "\n"
    "4. SYNTHESIS IS ALLOWED: if the CONTEXT explicitly states multiple "
    "complementary facts that together answer the question, you MAY "
    "combine them into one coherent answer. This is allowed only when "
    "every individual fact you use is literally present in the CONTEXT - "
    "do not calculate, estimate, or derive a NEW fact that is not itself "
    "stated (no inventing a number, deadline, or rule that only follows "
    "from your own reasoning).\n"
    "5. Still always forbidden: inventing a missing corporate rule; making "
    "an unsupported assumption; presenting an unsupported calculation or "
    "estimate as if it were company policy; extending a general rule to a "
    "specific case the CONTEXT does not support; and mentioning or "
    "inventing a source, article, section number, or document name, even "
    "a real one from the CONTEXT - state only the fact itself.\n"
    "6. A concrete example is allowed only if it uses facts already "
    "present in the CONTEXT - never introduce a new corporate fact through "
    "an example.\n"
    "7. Do NOT give advice or suggest other sources. Do NOT describe what "
    "the documents contain in general - answer the question or state that "
    "you lack sufficient information.\n"
    "8. Answer in Turkish. Be direct and concise - use as few sentences as "
    "the question genuinely needs. Do not pad a simple answer, but do not "
    "compress a legitimate multi-fact answer below what it needs either.\n"
    "9. Never use internal technical terms in your answer (e.g. chunk, "
    "embedding, context window, retrieval score, similarity, database). "
    "Speak only in plain, natural Turkish as a company assistant would."
)

# RAG V2 CHECKPOINT 3 (kisa konusma hafizasi): bir takip sorusunu ("Peki
# hafta sonu?" gibi), SADECE hemen onceki 1-2 mesaji kullanarak BAGIMSIZ/
# standalone bir retrieval sorusuna donusturur. Bu SISTEM promptu KASITLI
# olarak dar/kisitli - cevaplamaz, yeni bir sirket gercegi EKLEMEZ, SADECE
# zamir/eksik ozne/atif/konusma eliptigini cozer. Onceki asistan cevabi
# SADECE referans cozmek icin kullanilir - otorite bir kanit DEGILDIR (bkz.
# sorgu.py::cevapla - nihai cevap HALA SADECE final RAG kanitindan gelir,
# bu adim SADECE retrieval sorgusunu iyilestirir).
BAGLAMSALLASTIRMA_SISTEM = (
    "You rewrite a short Turkish follow-up question into a standalone "
    "question, using ONLY the immediately preceding conversation turn as "
    "context. Follow these rules exactly.\n"
    "1. Do NOT answer the question.\n"
    "2. Do NOT invent, add, or assume any corporate fact, number, policy, "
    "date, location, role, product, or condition that is not ALREADY "
    "explicitly present in the CURRENT question or the PREVIOUS turn.\n"
    "3. The PREVIOUS assistant answer is conversational context only, NOT "
    "an authoritative source - use it ONLY to resolve what a pronoun, "
    "reference, or omitted subject in the CURRENT question refers to, "
    "never to add a new fact into the rewritten question.\n"
    "4. Only resolve pronouns, omitted subjects, references, and "
    "conversational ellipsis (for example 'bunu', 'peki ya X', 'ne "
    "zaman', 'onu').\n"
    "5. This also covers a short elliptical hypothetical/numeric follow-up "
    "that supplies its OWN new number, duration, or condition but omits "
    "the subject entirely (for example a bare 'X dakika/saat olsa?', "
    "'daha geç/erken yapsak?', 'peki X?'). In that case attach ONLY the "
    "missing subject/action noun phrase from the immediately preceding "
    "turn so the question becomes grammatically standalone - keep the "
    "user's own new number/value/condition EXACTLY as they typed it, "
    "never replace it with a number from the PREVIOUS turn, and never "
    "add any other qualifier the user did not type themselves.\n"
    "6. If the CURRENT question is already self-contained/standalone, "
    "return it UNCHANGED, verbatim.\n"
    "7. If you cannot safely determine what a reference points to, return "
    "the CURRENT question UNCHANGED rather than guessing.\n"
    "8. Output ONLY the rewritten (or unchanged) question, in Turkish, "
    "nothing else - no explanation, no quotes, no prefix, no labels."
)


def _saglayici_hatasi(ust_durum):
    """OpenRouter'in HTTP durum kodunu (varsa - agdaki bir hata icin None
    olabilir) GUVENLI, sabit bir LLMServisHatasi kategorisine esler. HAM
    saglayici govdesi/metni BURADA HICBIR YERE tasinmaz - SADECE sayisal
    durum kodu okunur (bkz. gorev talimati "Do NOT expose ... full
    OpenRouter error bodies"). Listelenmemis/beklenmeyen HER durum (400,
    500, veya baska herhangi biri) GENEL "gecersiz_yanit" kovasina duser -
    "internal'i ifsa etme" kurali BOYLECE otomatik saglanir, yeni bir
    durum kodu icin ozel kod YAZILMASI GEREKMEZ."""
    if ust_durum == 401:
        return LLMServisHatasi("kimlik_dogrulama", 401,
                                "AI servisi kimlik doğrulama hatası verdi.", ust_durum)
    if ust_durum == 402:
        return LLMServisHatasi("kota", 402,
                                "AI servis kullanım limiti doldu. Lütfen daha sonra tekrar deneyin.", ust_durum)
    if ust_durum == 429:
        return LLMServisHatasi("yogunluk", 429,
                                "AI servisi şu anda yoğun. Lütfen kısa süre sonra tekrar deneyin.", ust_durum)
    if ust_durum in (502, 503):
        return LLMServisHatasi("saglayici_erisilemez", ust_durum,
                                "AI servisine geçici olarak ulaşılamıyor. Lütfen tekrar deneyin.", ust_durum)
    if ust_durum == 504:
        return LLMServisHatasi("zaman_asimi", 504,
                                "AI servisi yanıt vermekte gecikti. Lütfen tekrar deneyin.", ust_durum)
    # 200 (choices eksik/bozuk), 400, 500, veya baska her sey - hicbiri
    # kullanicinin YAPABILECEGI/BILMESI GEREKEN bir sey degil, o yuzden TEK
    # bir genel "gecersiz yanit" mesajina duser (bkz. gorev talimati
    # "Unexpected failures should not expose internals").
    return LLMServisHatasi("gecersiz_yanit", 502,
                            "AI servisinden geçerli bir yanıt alınamadı. Lütfen tekrar deneyin.", ust_durum)


def _hata_logla(asama, hata):
    """GUVENLI, tek-satirlik sunucu-tarafi tani logu - SADECE genis
    kategori/hedef HTTP durumu/saglayicinin KENDI HTTP durumu/asama adi
    (bkz. gorev talimati "Allowed: broad category, upstream status,
    stage"). API anahtari/HAM saglayici govdesi/prompt/soru/parca metni/
    baglanti dizesi BURADA HICBIR ZAMAN yazilmaz - LLMServisHatasi zaten
    bunlari TASIMIYOR (bkz. sinif docstring'i), o yuzden burada YANLISLIKLA
    da sizamaz. Ayri bir logging framework EKLENMEDI (bkz. gorev talimati
    "Do not introduce a logging framework if current simple logging is
    sufficient") - mevcut RAG_TIMING/CHAT_TIMING ile AYNI duz print()
    deseni."""
    print(f"[LLM_HATA] asama={asama} kategori={hata.kategori} "
          f"http_durum={hata.http_durum} ust_durum={hata.ust_durum}")


def _openrouter_tamamla(sistem_metni, kullanici_metni, max_tokens):
    """OpenRouter'a TEK bir sohbet-tamamlama istegi atan KUCUK paylasilan
    yardimci - sor() VE baglamsallastir() arasinda PAYLASILAN tek HTTP/
    hata-yonetim kodu (gereksiz tekrar OLMASIN diye). AYNI provider/model
    kullanilir - yeni bir saglayici/bagimlilik EKLENMEDI (bkz. gorev
    talimati "Prefer reusing the CURRENT LLM/provider infrastructure").

    BASARILI olursa (HTTP 2xx + gecerli JSON + kullanilabilir "choices")
    cevap METNINI DOGRUDAN dondurur - onceki davranisla AYNI. BASARISIZ
    olursa (non-2xx, 2xx ama choices eksik/bozuk, JSON-olmayan govde,
    istek zaman asimi, aglati/baglanti hatasi) ARTIK bir metin DEGIL,
    LLMServisHatasi FIRLATIR - cagiran (sor()/baglamsallastir()) bunu
    KENDI dusme davranisina gore ele alir. Onceki "duz metin hata dondur"
    deseni TAMAMEN KALDIRILDI - bir saglayici hatasi artik hicbir sekilde
    normal bir cevap METNIYLE KARISTIRILAMAZ (bkz. gorev talimati "must
    NEVER become cevap / be treated as grounded output").

    GUVENILIRLIK CHECKPOINT-SONRASI DUZELTME: bu istek BILINCLI olarak
    HALA bir timeout= parametresi TASIMIYOR (bkz. gorev talimati "Restore
    the previous requests.post timeout behavior only" - mevcut model daha
    yavas ureteflerde 30 saniyeye yakin surebiliyor, bu checkpoint zaman
    asimi DAVRANISINI degistirmeye YONELIK degildi). requests.exceptions.
    Timeout yakalamasi ASAGIDA yine de KALIR (siniflandirma/LLMServisHatasi
    sozlesmesi geri ALINMADI) - SADECE artik bu kod yolunu TETIKLEYECEK
    yerel bir sure siniri YOK; saglayici GERCEKTEN hic yanit vermezse istek
    (onceki davranisla AYNI sekilde) sinirsiz surebilir."""
    try:
        yanit = requests.post(
            URL,
            headers={
                "Authorization": f"Bearer {ANAHTAR}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": sistem_metni},
                    {"role": "user", "content": kullanici_metni},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
                "reasoning": {"enabled": False},
            },
        )
    except requests.exceptions.Timeout:
        raise LLMServisHatasi("zaman_asimi", 504,
                               "AI servisi yanıt vermekte gecikti. Lütfen tekrar deneyin.")
    except requests.exceptions.RequestException:
        # DNS/baglanti reddedildi/TLS/vs - saglayiciya HIC ulasilamadi, bu
        # yuzden ust_durum YOK (None) - sadece agdaki bir sorun oldugu
        # BILINIR, saglayicinin KENDI durum kodu hicbir zaman ALINAMADI.
        raise LLMServisHatasi("saglayici_erisilemez", 503,
                               "AI servisine geçici olarak ulaşılamıyor. Lütfen tekrar deneyin.")

    try:
        veri = yanit.json()
    except ValueError:
        # Govde JSON DEGIL (orn. bir ara proxy'den duz metin/HTML 502) -
        # durum kodu YINE DE gecerli (HTTP yaniti GELDI, sadece govdesi
        # ayristirilamadi) - ayni durum-koduna-gore-esleme kullanilir,
        # generic bir JSONDecodeError cagirana ASLA SIZMAZ.
        raise _saglayici_hatasi(yanit.status_code)

    if yanit.status_code // 100 == 2 and "choices" in veri:
        try:
            return veri["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            # 2xx ama "choices" bos/beklenmeyen sekilde - BASARI DEGIL,
            # asagidaki AYNI genel eslemeye duser.
            pass

    raise _saglayici_hatasi(yanit.status_code)


def sor(soru, parcalar):
    kullanici = "BAGLAM:\n" + "\n\n".join(parcalar) + "\n\nSORU: " + soru
    try:
        return _openrouter_tamamla(SISTEM, kullanici, 1000)
    except LLMServisHatasi as hata:
        # Nihai KANITLI cevap asamasi - bir saglayici hatasi burada ASLA
        # yutulmaz/normal bir cevap metnine DONUSTURULMEZ, SADECE tani
        # icin GUVENLI sekilde loglanir ve OLDUGU GIBI yukari (sorgu.py::
        # cevapla -> servis.py sinirina) firlatilmaya devam eder (bkz.
        # gorev talimati "Let the typed exception propagate through
        # sorgu.py::cevapla() to the FastAPI boundary").
        _hata_logla("answer", hata)
        raise


def baglamsallastir(soru, gecmis):
    """RAG V2 CHECKPOINT 3: kisa bir takip sorusunu, SADECE hemen onceki
    1-2 mesaji (gecmis) BAGLAM olarak kullanarak, BAGIMSIZ/standalone bir
    retrieval sorusuna donusturur. gecmis her ogesinde .mesaj_rolu ("soru"
    ya da "cevap") ve .metin bulunan herhangi bir nesne olabilir (Pydantic
    modeli dahil - duck typing, ozel bir tip import EDILMEZ).

    cagiran (sorgu.py::cevapla) gecmis BOSSA/None ise bu fonksiyonu HIC
    CAGIRMAZ - ekstra saglayici istegi SADECE gercek bir takip sorusunda
    atilir (bkz. gorev talimati "Do not make this call when there is no
    previous history").

    Saglayici basarisiz olursa (agdaki/API'deki bir sorun) GUVENLI dusme:
    soru DEGISTIRILMEDEN, oldugu gibi doner - takip cozumlemesinin
    basarisiz olmasi normal soru-cevap akisini KIRMAZ, sadece o soru
    Genel Asistan/router icin biraz daha az baglamli kalir."""
    baglam_satirlari = []
    for mesaj in gecmis:
        etiket = "ONCEKI SORU" if mesaj.mesaj_rolu == "soru" else "ONCEKI CEVAP"
        baglam_satirlari.append(f"{etiket}: {mesaj.metin}")

    kullanici = "\n".join(baglam_satirlari) + f"\n\nSU ANKI SORU: {soru}"

    try:
        icerik = _openrouter_tamamla(BAGLAMSALLASTIRMA_SISTEM, kullanici, 120)
    except LLMServisHatasi as hata:
        # Bu asamanin GUVENLI dusme davranisi DEGISMEDI (bkz. gorev
        # talimati "Do NOT change ... contextualization semantics") -
        # SADECE onceki (icerik, hata) ikilisi yerine artik bir istisna
        # YAKALANIYOR; sonuc AYNI: soru DEGISTIRILMEDEN doner, hata
        # yukari asla firlatilmaz. Tek eklenen sey guvenli tani logu.
        _hata_logla("contextualize", hata)
        return soru

    yeniden_yazilan = icerik.strip()
    return yeniden_yazilan if yeniden_yazilan else soru
