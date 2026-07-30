from sentence_transformers import SentenceTransformer
import numpy as np
from parcala import parcalar

# --- bir kez yükle, bir kez embed et ---
model = SentenceTransformer("BAAI/bge-m3")

metinler = [p["metin"] for p in parcalar]
vektorler = model.encode(metinler, normalize_embeddings=True)

# --- test soruları ---
sorular = [
    "kasa sayımını kim yapar",
    "mesaide telefon kullanabilir miyim",
    "müşteri bilgisi paylaşılır mı",
    "mağaza kaçta açılıyor",
    "geç kalırsam ne olur",
    "hava nasıl olacak",
    "python nasıl öğrenilir",
    "en iyi pizza nerede",
    "kedim hasta",
    "dolar kaç lira",
    "maaşım ne zaman yatar",
    "yıllık zam oranı kaç",
    "doğum izni kaç gün",
]

for soru in sorular:
    soru_v = model.encode(soru, normalize_embeddings=True)
    skorlar = vektorler @ soru_v
    en_iyi = skorlar.max()
    en_iyi_i = skorlar.argmax()
    print(f"{en_iyi:.3f} | {soru:35} | {parcalar[en_iyi_i]['metin'][:100]}")