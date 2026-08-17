-- Erisim kontrolu (access control) - ADIM A: DB temeli.
--
-- RERUN-SAFE: her adim IF NOT EXISTS / conditional DO bloklariyla korunuyor,
-- 001_departmanlar.sql ile AYNI stil - bu script ayni Postgres/Supabase
-- veritabaninda birden fazla kez calistirilabilir.
--
-- Bu script sadece SEMAYI hazirlar - servis.py / sorgu.py / indeksle.py /
-- Razor sayfalari HENUZ bu kolonlari/tabloyu kullanmiyor (ayri bir
-- entegrasyon adiminda baglanacak). Mevcut belgeler/parcalar satirlari
-- erisim_seviyesi = NULL olarak KALIR, hicbir backfill yapilmaz - NULL
-- BILINCLI olarak "default-deny" anlamina gelir (erisim seviyesi
-- belirlenmemis bir satir, entegrasyon tamamlanana kadar HERKESE KAPALI
-- sayilacak). kullanici_departmanlari tablosuna da hicbir satir eklenmez -
-- kullanici-departman uyeligi TAHMIN EDILEREK atanmaz (departmanlar.ad
-- seed'i icin 001'deki ayni karar).

-- 1) kullanici_departmanlari: bir kullanicinin ACIKCA uye oldugu
--    departmanlar. Cok-cok iliski - bir kullanici birden fazla departmana
--    uye olabilir. id yok, dogal anahtar (kullanici_id, departman_id)
--    PRIMARY KEY olarak yeterli - departmanlar/tenantlar gibi ayri bir
--    surrogate id'ye ihtiyac yok, satirlarin kendisi referans edilmiyor.
create table if not exists kullanici_departmanlari (
    kullanici_id bigint not null references kullanicilar(id) on delete cascade,
    departman_id bigint not null references departmanlar(id) on delete cascade,
    olusturma_tarihi timestamptz not null default now(),
    primary key (kullanici_id, departman_id)
);

-- 2) belgeler.erisim_seviyesi: bu belgeyi KIMIN okuyabilecegi (departman_id
--    ise belgenin KONUSUNU/sahipligini belirtir - ikisi farkli eksenler).
--    Nullable - mevcut belgeler icin backfill YAPILMIYOR (yukaridaki NOT).
alter table belgeler
    add column if not exists erisim_seviyesi text;

-- 3) parcalar.erisim_seviyesi: departman_id/tenant_id ile AYNI gerekcede
--    BILINCLI denormalize edilmis kopya - retrieval sorgusu (sorgu.py::
--    cevapla) belgeler'e HIC JOIN yapmadan dogrudan parcalar'i filtreliyor,
--    erisim_seviyesi de bu yuzden parcalar'da ayrica (FK'siz) tutuluyor.
alter table parcalar
    add column if not exists erisim_seviyesi text;

-- 4) erisim_seviyesi icin izin verilen degerler: NULL (default-deny) veya
--    'sirket' (tum tenant calisanlari) / 'departman' (sadece
--    kullanici_departmanlari uzerinden uye oldugu departman(lar)).
--    Postgres'te ADD CONSTRAINT IF NOT EXISTS YOK - pg_constraint uzerinden
--    conditional DO blogu ile rerun-safe hale getiriliyor.
do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'belgeler_erisim_seviyesi_check'
    ) then
        alter table belgeler
            add constraint belgeler_erisim_seviyesi_check
            check (erisim_seviyesi is null or erisim_seviyesi in ('sirket', 'departman'));
    end if;
end $$;

do $$
begin
    if not exists (
        select 1 from pg_constraint where conname = 'parcalar_erisim_seviyesi_check'
    ) then
        alter table parcalar
            add constraint parcalar_erisim_seviyesi_check
            check (erisim_seviyesi is null or erisim_seviyesi in ('sirket', 'departman'));
    end if;
end $$;
