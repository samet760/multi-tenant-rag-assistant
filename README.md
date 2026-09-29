# Belge Asistanı

Şirketlerin kendi PDF belgelerinden (yönetmelik, prosedür, politika) çalışanlarına Türkçe cevap veren **çok kiracılı (multi-tenant) RAG chatbot**.

Çalışan soruyu sorar, sistem sadece o şirketin ve o kullanıcının erişim yetkisi olan belgelerde arar, cevabı **yalnızca belgede yazanlara dayanarak** verir ve hangi belgeden geldiğini gösterir. Belgede cevap yoksa uydurmaz, "bilgi yok" der.

> Ekran görüntüleri: `docs/` klasörüne ekleyip buraya bağlayabilirsin.

## Özellikler

- **Çok kiracılı yapı:** Her şirketin belgeleri, kullanıcıları ve sohbetleri `tenant_id` ile tamamen ayrı tutulur.
- **Departman bazlı erişim kontrolü:** Belgeler `sirket` (herkes) veya `departman` (sadece üyeler) seviyesinde paylaşılır. Yetki kontrolü, vektör aramasından *önce* SQL içinde uygulanır, yani yetkisiz parçalar aday havuzuna hiç girmez.
- **Otomatik departman yönlendirme ("Genel Asistan"):** Soru, en alakalı departmana embedding benzerliğine göre yönlendirilir.
- **İki aşamalı arama:** `bge-m3` ile dense retrieval, ardından `bge-reranker-v2-m3` cross-encoder ile yeniden sıralama.
- **Sohbet bağlamı:** Takip soruları ("peki kaç gün?") önceki mesajlara göre bağımsız bir soruya dönüştürülür.
- **Kaynak gösterme:** Her cevabın hangi belgelerden üretildiği saklanır ve gösterilirken güncel yetkiye göre tekrar kontrol edilir.
- **Yönetim paneli:** Belge yükleme/düzenleme, departman yönetimi, kullanıcı rolleri, departman yetkileri, firma logosu.

## Mimari

```
                ┌──────────────────────────────┐
 Tarayıcı ────▶ │ ASP.NET Core Razor Pages     │  giriş, roller, yönetim, sohbet arayüzü
                │ (arayuz/)                    │
                └──────────────┬───────────────┘
                               │ HTTP (127.0.0.1:8000)
                ┌──────────────▼───────────────┐
                │ FastAPI (servis.py)          │
                │  /indeksle  PDF → parça → embedding
                │  /sor       yönlendir → ara → rerank → LLM
                └──────────────┬───────────────┘
                               │
                ┌──────────────▼───────────────┐      ┌──────────────┐
                │ Postgres + pgvector          │      │ OpenRouter   │
                │ (Supabase)                   │      │ (LLM)        │
                └──────────────────────────────┘      └──────────────┘
```

**İndeksleme:** `pdf_oku.py` → `parcala.py` (300 karakter, 50 örtüşme) → `embed.py` (`BAAI/bge-m3`, 1024 boyut) → `indeksle.py` (`belgeler` + `parcalar` tabloları)

**Sorgu:** `sorgu.py::cevapla` → departman yönlendirme → yetki filtreli pgvector araması → reranker → `llm.py::sor` (katı sistem promptu: sadece bağlamdan, Türkçe, kısa)

## Teknolojiler

Python · FastAPI · sentence-transformers · PostgreSQL + pgvector · ASP.NET Core (.NET 10) Razor Pages · Npgsql · OpenRouter

## Kurulum

### 1. Veritabanı

pgvector destekli bir Postgres gerekir (Supabase ücretsiz planı yeterli). `migrations/` altındaki dosyaları sırayla çalıştır:

```
000_temel_sema.sql → 001_departmanlar.sql → 002_erisim_kontrolu.sql → 003_mesaj_kaynaklari.sql
```

Bu dosyalar `ornek-firma` adında bir örnek tenant ve 4 departman oluşturur.

### 2. Ortam değişkenleri

```bash
cp .env.example .env
# SUPABASE_DB_URL ve OPENROUTER_API_KEY değerlerini doldur
```

### 3. Python servisi

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
uvicorn servis:app              # 127.0.0.1:8000
```

İlk çalıştırmada `bge-m3` ve reranker modelleri indirilir (~4 GB).

### 4. Arayüz

```bash
cd arayuz
dotnet run
```

### 5. İlk yönetici

`/Kayit` sayfasından kayıt olan kullanıcı `kullanici` rolüyle başlar. İlk yöneticiyi SQL ile ata:

```sql
update kullanicilar set rol = 'yonetici' where eposta = 'sen@ornek.com';
update tenantlar set sahip_eposta = 'sen@ornek.com' where id = 'ornek-firma';
```

Sonrasında belge yükleme, departman ve kullanıcı yönetimi uygulama içinden yapılır.

## Notlar

- `*_test.py` ve `rag_*benchmark.py` dosyaları manuel test/ayar scriptleridir, otomatik test paketi değildir.
- Proje yerel kullanım için tasarlandı. İki servis aynı makinede çalışır ve Python servisi, .NET tarafından gelen kimlik bilgisine güvenir.
