import re
from pypdf import PdfReader

# --- PDF oku ve temizle ---
reader = PdfReader("data/kurallar.pdf")
metin = ""
for sayfa in reader.pages:
    metin += sayfa.extract_text()
metin = metin.replace("\n", " ")
metin = re.sub(r"\s+", " ", metin).strip()

# --- bölümlere ayır ---
bolumler = re.split(r"(?=BÖLÜM \d+)", metin)
bolumler = [b.strip() for b in bolumler if b.strip()]

# --- her bölümde maddelere ayır ---
parcalar = []
for bolum in bolumler:
    # başlık: "BÖLÜM sayı — BÜYÜK HARFLER", ilk "Madde"de dur
    baslik_eslesme = re.match(r"(BÖLÜM \d+ .+?)(?= Madde \d+\.)", bolum)
    baslik = baslik_eslesme.group(1).strip() if baslik_eslesme else "BAŞLIK YOK"

    maddeler = re.split(r"(?=Madde \d+\.)", bolum)
    for madde in maddeler:
        madde = madde.strip()
        if madde.startswith("Madde"):
            parcalar.append({
                "bolum": baslik,
                "metin": madde
            })

# --- kontrol ---
if __name__ == "__main__":
    print(f"Toplam {len(parcalar)} parça bulundu.\n")
    for i, p in enumerate(parcalar):
        print(f"--- Parça {i} | {p['bolum']} ---")
        print(p["metin"])
        print()