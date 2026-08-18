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
    # kullanici_id / rol: .NET'in kullanici_id claim'inden (bkz.
    # Giris.cshtml.cs) ve ClaimTypes.Role'den gonderdigi GUVENILIR kimlik -
    # ADIM C2'de SADECE tasiniyor, HENUZ hicbir SQL'de kullanilmiyor (bkz.
    # sorgu.py). Zorunlu alanlar - .NET bunlari her zaman gondermek zorunda
    # (eksik kullanici_id claim'i varsa .NET istegi HIC gondermez, bkz.
    # Index.cshtml.cs).
    kullanici_id: int
    rol: str

@app.post("/sor")
def sor_endpoint(istek: SoruIstegi):
    # departman_id: HANGI departmanda arandigi (elle secilmis ya da Genel
    # Asistan'in yonlendirdigi) - .NET tarafi bunu SADECE gorsel etiket icin
    # kullanir (bkz. Index.cshtml.cs), retrieval/skor/cevap akisini etkilemez.
    # kaynaklar: sadece LLM'e verilen (zaten yetkilendirme-filtreli) parcalarin
    # belgeleri - bkz. sorgu.py::cevapla. Ayri bir yetkilendirme sorgusu
    # BURADA calistirilmaz, cevapla'nin dondurdugu listeye DOKUNULMADAN
    # aktarilir.
    cevap, skor, departman_id, kaynaklar = cevapla(
        istek.soru, istek.tenant_id, istek.departman_id, istek.kullanici_id, istek.rol
    )
    return {"cevap": cevap, "skor": skor, "departman_id": departman_id, "kaynaklar": kaynaklar}

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