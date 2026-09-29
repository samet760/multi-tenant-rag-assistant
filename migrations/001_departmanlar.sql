-- Departman (department) veritabani temeli.
--
-- RERUN-SAFE: her adim IF NOT EXISTS / ON CONFLICT ile korunuyor, bu script
-- ayni Postgres/Supabase veritabaninda birden fazla kez calistirilabilir.
--
-- Bu script sadece SEMAYI hazirlar - indeksle.py / servis.py / sorgu.py /
-- Razor sayfalari HENUZ departman_id kolonlarini kullanmiyor (ayri bir
-- entegrasyon adiminda baglanacak). Mevcut belgeler/parcalar satirlari
-- departman_id = NULL olarak KALIR, hicbir backfill yapilmaz (bilincli
-- urun karari - departmanlar tahmin edilerek atanmaz).

-- 1) departmanlar: her tenant'in kendi departman listesi.
--    id: projedeki diger tum tablolarla (sohbetler, mesajlar, belgeler,
--    parcalar) AYNI desen (bigserial) - tenantlar.id (text slug, orn.
--    "ornek-firma") ile KARISTIRILMASIN; departmanlar admin tarafindan
--    CRUD edilecek normal satirlar, tenant'in kendisi degil.
create table if not exists departmanlar (
    id bigserial primary key,
    tenant_id text not null references tenantlar(id),
    ad text not null,
    olusturma_tarihi timestamptz not null default now(),
    unique (tenant_id, ad)
);

-- 2) belgeler.departman_id: hangi departmana ait oldugu. Nullable - mevcut
--    belgeler icin backfill YAPILMIYOR (yukaridaki NOT).
alter table belgeler
    add column if not exists departman_id bigint references departmanlar(id);

-- 3) parcalar.departman_id: BILINCLI olarak denormalize edilmis kopya,
--    FK'siz - tam olarak parcalar.tenant_id ile AYNI gerekcede: retrieval
--    sorgusu (sorgu.py::cevapla) belgeler'e HIC JOIN yapmadan dogrudan
--    parcalar'i filtreliyor, tenant_id de bu yuzden parcalar'da ayrica
--    (FK'siz) tutuluyor - departman_id ayni deseni izliyor.
alter table parcalar
    add column if not exists departman_id bigint;

-- 4) Ornek tenant icin baslangic departmanlari. Idempotent:
--    UNIQUE(tenant_id, ad) constraint'i uzerinden ON CONFLICT DO NOTHING -
--    script tekrar calistirilirsa yeni satir eklenmez.
--    "Genel Asistan" BURADA YOK - bu bir departman degil, ileride ayri bir
--    yonlendirme modu olacak (bkz. PROJECT_MAP.md). Bu dort isim uygulama
--    kodunda hardcode EDILMEYECEK - sadece bu tenant icin baslangic verisi.
insert into departmanlar (tenant_id, ad) values
    ('ornek-firma', 'Mağaza Operasyonları'),
    ('ornek-firma', 'İnsan Kaynakları'),
    ('ornek-firma', 'IT Destek'),
    ('ornek-firma', 'Ürün & Lojistik')
on conflict (tenant_id, ad) do nothing;
