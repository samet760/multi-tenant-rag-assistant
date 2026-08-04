import time
from sorgu import cevapla

SORULAR = [
    ("kasa sayımını kim yapar", "VAR"),
    ("mesaide telefon kullanabilir miyim", "VAR"),
    ("müşteri bilgisi paylaşılır mı", "VAR"),
    ("mağaza kaçta açılıyor", "VAR"),
    ("geç kalırsam ne olur", "VAR"),
    ("doğum izni kaç gün", "YOK"),
    ("maaşım ne zaman yatar", "YOK"),
    ("yıllık zam oranı kaç", "YOK"),
    ("python nasıl öğrenilir", "YOK"),
]

if __name__ == "__main__":
    for soru, beklenen in SORULAR:
        basla = time.time()
        cevap,skor = cevapla(soru, "english-home")
        sure = round(time.time() - basla, 1)
        print(f"\n[{beklenen}] {soru}")
        print(f"      {cevap}")
        print(f"      ({sure} sn | skor {skor:.3f})")