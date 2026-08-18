"""Reranker (BAAI/bge-reranker-v2-m3) - SADECE tani/benchmark modulu.

Production kodu (servis.py, sorgu.py) bu dosyayi HICBIR YERDE import ETMEZ -
bu modulun var olmasi/degismesi production RAG davranisini hicbir sekilde
ETKILEMEZ. SADECE rag_benchmark.py --rerank bayragiyla kullanir.

Neden CrossEncoder: sentence-transformers zaten requirements.txt'te
(embed.py::model bunu kullaniyor) - CrossEncoder sinifi AYNI paketin icinde
gelir, bge-reranker-v2-m3 bir cross-encoder oldugu icin dogrudan
yuklenebilir. YENI bir ust-duzey bagimlilik EKLENMEDI (transformers/torch
zaten sentence-transformers'in gecisli bagimliligi).

Tembel (lazy) tekil (singleton): ilk cagrida yuklenir, sonraki tum
cagrilarda AYNI ornek yeniden kullanilir - model ASLA aday basina/soru
basina yeniden YUKLENMEZ (bkz. gorev talimati).
"""

from sentence_transformers import CrossEncoder

MODEL_ADI = "BAAI/bge-reranker-v2-m3"

_model = None


def reranker_al() -> CrossEncoder:
    """Tekil CrossEncoder ornegini dondurur - ilk cagrida yukler, sonraki
    cagrilarda ayni ornegi (yeniden yuklemeden) dondurur."""
    global _model
    if _model is None:
        _model = CrossEncoder(MODEL_ADI)
    return _model
