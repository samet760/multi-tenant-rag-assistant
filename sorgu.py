from sentence_transformers import SentenceTransformer
import numpy as np
from parcala import parcalar
from llm import sor

ESIK = 0.55

model = SentenceTransformer("BAAI/bge-m3")
metinler = [p["metin"] for p in parcalar]
vektorler = model.encode(metinler, normalize_embeddings=True)


def cevapla(soru):
    soru_v = model.encode(soru, normalize_embeddings=True)
    skorlar = vektorler @ soru_v

    if skorlar.max() < ESIK:
        return f"[ESIK {skorlar.max():.3f}] Bu bilgi dokümanlarda yer almıyor."
    
    ilk3 = np.argsort(skorlar)[::-1][:3]
    secilen = [metinler[i] for i in ilk3]
    return sor(soru, secilen)


if __name__ == "__main__":
    testler = [
        "mağaza kaçta açılıyor",
        "geç kalırsam ne olur",
        "kasa sayımını kim yapar",
        "doğum izni kaç gün",
        "python nasıl öğrenilir",
    ]
    for s in testler:
        print(f"\n=== {s}")
        print(cevapla(s))