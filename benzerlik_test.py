from sentence_transformers import SentenceTransformer
import numpy as np
from parcala import parcalar

model = SentenceTransformer("BAAI/bge-m3")

metinler = [p["metin"] for p in parcalar]
vektorler = model.encode(metinler, normalize_embeddings=True)

soru = "en sevdiğim futbol takımı hangisi"
soru_v = model.encode(soru, normalize_embeddings=True)

skorlar = vektorler @ soru_v

sirali = np.argsort(skorlar)[::-1]

print(f"SORU: {soru}\n")
for i in sirali[:5]:
    print(f"{skorlar[i]:.3f} | {parcalar[i]['bolum'][:30]} | {parcalar[i]['metin'][:70]}")