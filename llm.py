import os
import requests
from dotenv import load_dotenv

load_dotenv()
ANAHTAR = os.getenv("OPENROUTER_API_KEY")

MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
URL = "https://openrouter.ai/api/v1/chat/completions"

SISTEM = (
    "You are a document lookup assistant. Follow these rules exactly.\n"
    "1. Answer ONLY with facts written literally in the CONTEXT.\n"
    "2. Do NOT calculate, estimate, infer, derive, or combine facts. "
    "If a number is not written in the context, it does not exist.\n"
    "3. If the answer is not literally stated, output EXACTLY this and nothing else: "
    "Bu bilgi dokümanlarda yer almıyor.\n"
    "4. Do NOT give advice or suggest other sources.\n"
    "5. Do NOT describe what the document contains. Answer or refuse.\n"
    "6. Answer in Turkish, maximum 2 sentences."
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
    return veri["choices"][0]["message"]["content"]