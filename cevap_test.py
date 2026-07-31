import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()
ANAHTAR = os.getenv("OPENROUTER_API_KEY")
MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

PARCALAR = [
    "BOLUM 2 CALISMA SAATLERI Madde 4. Haftalik calisma suresi 45 saattir.",
    "BOLUM 2 CALISMA SAATLERI Madde 5. Ogle molasi 1 saattir.",
    "BOLUM 3 IZINLER Madde 8. Yillik izin 14 gundur.",
]

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

SORULAR = [
    ("Yillik izin kac gun?", "VAR"),
    ("Ogle molasi ne kadar?", "VAR"),
    ("Sirketin yillik cirosu ne kadar?", "YOK"),
    ("Dogum izni kac gun?", "YOK"),
    ("Gunluk kac saat calisilir?", "YOK"),
    ("Ogle molasi ucretli mi?", "YOK"),
]


def sor(soru):
    kullanici = "BAGLAM:\n" + "\n\n".join(PARCALAR) + "\n\nSORU: " + soru
    yanit = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {ANAHTAR}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SISTEM},
                {"role": "user", "content": kullanici},
            ],
            "max_tokens": 1000,
            "reasoning": {"enabled": False},
            "temperature": 0,
        },
        timeout=60,
    )
    return yanit.json()["choices"][0]["message"]["content"].strip()


for soru, beklenen in SORULAR:
    basla = time.time()
    cevap = sor(soru)
    sure = round(time.time() - basla, 1)
    print(f"\n[{beklenen}] {soru}")
    print(f"      {cevap}")
    print(f"      ({sure} sn)")