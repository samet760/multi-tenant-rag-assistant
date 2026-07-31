from llm import sor
import time



PARCALAR = [
    "BOLUM 2 CALISMA SAATLERI Madde 4. Haftalik calisma suresi 45 saattir.",
    "BOLUM 2 CALISMA SAATLERI Madde 5. Ogle molasi 1 saattir.",
    "BOLUM 3 IZINLER Madde 8. Yillik izin 14 gundur.",
]


SORULAR = [
    ("Yillik izin kac gun?", "VAR"),
    ("Ogle molasi ne kadar?", "VAR"),
    ("Sirketin yillik cirosu ne kadar?", "YOK"),
    ("Dogum izni kac gun?", "YOK"),
    ("Gunluk kac saat calisilir?", "YOK"),
    ("Ogle molasi ucretli mi?", "YOK"),
]





if __name__ == "__main__":
    for soru, beklenen in SORULAR:
        basla = time.time()
        cevap = sor(soru, PARCALAR)
        sure = round(time.time() - basla, 1)
        print(f"\n[{beklenen}] {soru}")
        print(f"      {cevap}")
        print(f"      ({sure} sn)")