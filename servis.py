import os
import tempfile
from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
from sorgu import cevapla
from indeksle import indeksle
app = FastAPI()

class SoruIstegi(BaseModel):
    soru: str
    tenant_id: str
    # Opsiyonel - None = "Genel Asistan" (sohbet tarafinda departman
    # secilmemis/acikca "Genel Asistan" secilmis). cevapla() bu durumda
    # departmani soru embedding'inden OTOMATIK yonlendirir (bkz.
    # sorgu.py::departman_yonlendir) - filtreyi ATLAMAZ, TUM departmanlarda
    # aramaz.
    departman_id: int | None = None

@app.post("/sor")
def sor_endpoint(istek: SoruIstegi):
    cevap, skor = cevapla(istek.soru, istek.tenant_id, istek.departman_id)
    return {"cevap": cevap, "skor": skor}

@app.post("/indeksle")
def indeksle_endpoint(
    tenant_id: str = Form(...),
    dosya_adi: str = Form(...),
    departman_id: int = Form(...),
    dosya: UploadFile = File(...),
):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as gecici:
        gecici.write(dosya.file.read())
        yol = gecici.name

    try:
        belge_id = indeksle(tenant_id, yol, dosya_adi, departman_id)
    finally:
        os.remove(yol)

    return {"durum": "tamam", "belge_id": belge_id}