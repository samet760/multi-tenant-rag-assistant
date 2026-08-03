# servis.py
from fastapi import FastAPI
from pydantic import BaseModel
from sorgu import cevapla

app = FastAPI()

class SoruIstegi(BaseModel):
    soru: str
    tenant_id: str

@app.post("/sor")
def sor_endpoint(istek: SoruIstegi):
    cevap = cevapla(istek.soru, istek.tenant_id)
    return {"cevap": cevap}