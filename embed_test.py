from sentence_transformers import SentenceTransformer

# modeli yükle (ilk çalıştırmada indirir)
print("Model yükleniyor... (ilk seferde indirme olur, bekle)")
model = SentenceTransformer("BAAI/bge-m3")
print("Model hazır.\n")

# tek bir cümleyi vektöre çevir
cumle = "Yıllık izin nasıl alınır?"
vektor = model.encode(cumle)

print(f"Cümle: {cumle}")
print(f"Vektör boyutu: {len(vektor)}")
print(f"İlk 10 sayı: {vektor[:10]}")