import os
import time
import requests
from dotenv import load_dotenv

load_dotenv()

ANAHTAR = os.getenv("OPENROUTER_API_KEY")
if not ANAHTAR:
    raise SystemExit(".env icinde OPENROUTER_API_KEY yok.")

MODEL ="nvidia/nemotron-3-ultra-550b-a55b:free"

basla = time.time()

yanit = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {ANAHTAR}",
        "Content-Type": "application/json",
    },
    json={
        "model": MODEL,
        "messages": [
            {"role": "user", "content": "Tek cumleyle cevap ver: Turkiye'nin baskenti neresi?"}
        ],
        "max_tokens": 1000,
        # "reasoning": {"enabled": False},
    },
    timeout=60,
)

sure = round(time.time() - basla, 1)

veri = yanit.json()
print("SURE:", sure, "sn")
print("CEVAP:", veri["choices"][0]["message"]["content"])
print("DUSUNME TOKEN:", veri["usage"]["completion_tokens_details"]["reasoning_tokens"])