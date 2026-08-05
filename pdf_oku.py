import re
from pypdf import PdfReader


def pdf_oku(pdf_yolu):
    reader = PdfReader(pdf_yolu)

    metin = ""
    for sayfa in reader.pages:
        metin += sayfa.extract_text()

    metin = metin.replace("\n", " ")
    metin = re.sub(r"\s+", " ", metin)
    return metin.strip()