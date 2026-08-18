import os
import requests
from dotenv import load_dotenv

load_dotenv()
ANAHTAR = os.getenv("OPENROUTER_API_KEY")

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
URL = "https://openrouter.ai/api/v1/chat/completions"

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


def sor(soru, parcalar):
    kullanici = "BAGLAM:\n" + "\n\n".join(parcalar) + "\n\nSORU: " + soru

    yanit = requests.post(
        URL,
        headers={
            "Authorization": f"Bearer {ANAHTAR}",
            "Content-Type": "application/json",
        },
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SISTEM},
                {"role": "user", "content": kullanici},
            ],
            "temperature": 0,
            "max_tokens": 1000,
            "reasoning": {"enabled": False},
        },
    )

    veri = yanit.json()

    if "choices" not in veri:
        return f"[HATA {yanit.status_code}] {yanit.text[:200]}"

    return veri["choices"][0]["message"]["content"]