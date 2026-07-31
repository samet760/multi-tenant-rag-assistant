import os
from dotenv import load_dotenv

load_dotenv()
a = os.getenv("OPENROUTER_API_KEY")

print("uzunluk:", len(a) if a else "YOK")
print("ilk 8:", a[:8] if a else "-")
print("son 4:", repr(a[-4:]) if a else "-")
print("bosluk/CR:", any(c in a for c in " \r\n\t") if a else "-")