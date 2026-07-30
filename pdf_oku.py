

from pypdf import PdfReader

reader = PdfReader("data/ENGLISH HOME MAĞAZA ÇALIŞMA YÖNETMELİĞİ.pdf")

metin = ""
for sayfa in reader.pages:
    metin += sayfa.extract_text()

# --- temizleme ---
# alt satıra geçişleri boşluğa çevir
metin = metin.replace("\n", " ")
# birden fazla boşluğu tek boşluğa indir
import re
metin = re.sub(r"\s+", " ", metin)
metin = metin.strip()

print(metin[:500])