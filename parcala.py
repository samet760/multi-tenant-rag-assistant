from pdf_oku import pdf_oku

BOYUT = 300
ORTUSME = 50


def parcalar_uret(pdf_yolu):
    metin = pdf_oku(pdf_yolu)
    parcalar = []
    bas = 0

    while bas < len(metin):
        if bas > 0:
            ileri = metin.find(" ", bas)
            if ileri != -1:
                bas = ileri + 1
        son = bas + BOYUT

        if son < len(metin):
            bosluk = metin.rfind(" ", bas, son)
            if bosluk > bas:
                son = bosluk

        parca = metin[bas:son].strip()
        if parca:
            parcalar.append({"bolum": None, "metin": parca})

        bas = son - ORTUSME

    return parcalar