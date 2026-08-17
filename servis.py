import os
import tempfile
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sorgu import cevapla
from indeksle import indeksle
app = FastAPI()

# migrations/002_erisim_kontrolu.sql'deki CHECK ile AYNI kisitlama - .NET
# tarafi zaten dogruluyor ama Python bu istege DOGRUDAN guvenmez.
GECERLI_ERISIM_SEVIYELERI = {"sirket", "departman"}

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
    # departman_id: HANGI departmanda arandigi (elle secilmis ya da Genel
    # Asistan'in yonlendirdigi) - .NET tarafi bunu SADECE gorsel etiket icin
    # kullanir (bkz. Index.cshtml.cs), retrieval/skor/cevap akisini etkilemez.
    cevap, skor, departman_id = cevapla(istek.soru, istek.tenant_id, istek.departman_id)
    return {"cevap": cevap, "skor": skor, "departman_id": departman_id}

@app.post("/indeksle")
def indeksle_endpoint(
    tenant_id: str = Form(...),
    dosya_adi: str = Form(...),
    departman_id: int = Form(...),
    erisim_seviyesi: str = Form(...),
    dosya: UploadFile = File(...),
):
    if erisim_seviyesi not in GECERLI_ERISIM_SEVIYELERI:
        raise HTTPException(status_code=400, detail="Gecersiz erisim_seviyesi")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as gecici:
        gecici.write(dosya.file.read())
        yol = gecici.name

    try:
        belge_id = indeksle(tenant_id, yol, dosya_adi, departman_id, erisim_seviyesi)
    finally:
        os.remove(yol)

    return {"durum": "tamam", "belge_id": belge_id}