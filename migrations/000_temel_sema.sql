-- Temel sema: 001/002/003'ten ONCE calistirilir.
--
-- Orijinal sema Supabase uzerinde elle olusturulmustu, repoda yoktu. Bu
-- dosya, uygulama kodundaki sorgulardan (servis.py / sorgu.py / indeksle.py /
-- arayuz/Pages/*.cs) geri cikarildi - bos bir Postgres'te projeyi yeniden
-- ayaga kaldirmak icin yeterli.
--
-- RERUN-SAFE: 001/002/003 ile AYNI stil (IF NOT EXISTS / ON CONFLICT).
--
-- Calistirma sirasi:
--   000_temel_sema.sql -> 001_departmanlar.sql -> 002_erisim_kontrolu.sql
--   -> 003_mesaj_kaynaklari.sql

create extension if not exists vector;

-- tenantlar.id bir text slug ("ornek-firma"), numeric surrogate degil.
-- Uygulamada tenant olusturma ekrani YOK - yeni tenant buradan (SQL ile) eklenir.
create table if not exists tenantlar (
    id text primary key,
    ad text not null,
    sahip_eposta text,
    logo_url text
);

-- rol: 'kullanici' | 'yonetici'. Kayit ekrani rol yazmaz, default devreye girer;
-- ilk yonetici elle yukseltilir (bkz. README).
create table if not exists kullanicilar (
    id bigserial primary key,
    eposta text not null unique,
    sifre_ozeti text not null,
    tenant_id text not null references tenantlar(id),
    rol text not null default 'kullanici' check (rol in ('kullanici', 'yonetici'))
);

-- departman_id / erisim_seviyesi kolonlari 001 ve 002'de eklenir.
create table if not exists belgeler (
    id bigserial primary key,
    tenant_id text not null references tenantlar(id),
    dosya_adi text not null,
    dosya_yolu text,
    yukleme_tarihi timestamptz not null default now()
);

-- tenant_id BILINCLI olarak FK'siz denormalize (bkz. PROJECT_MAP.md) -
-- retrieval sorgusu belgeler'e JOIN yapmadan dogrudan parcalar'i filtreler.
-- vector(1024): BAAI/bge-m3 embedding boyutu.
create table if not exists parcalar (
    id bigserial primary key,
    tenant_id text not null,
    bolum text,
    metin text not null,
    vektor vector(1024) not null,
    belge_id bigint not null references belgeler(id) on delete cascade
);

create table if not exists sohbetler (
    id bigserial primary key,
    tenant_id text not null references tenantlar(id),
    eposta text not null,
    baslik text,
    olusturma_tarihi timestamptz not null default now()
);

create table if not exists mesajlar (
    id bigserial primary key,
    sohbet_id bigint not null references sohbetler(id) on delete cascade,
    rol text not null,
    metin text not null,
    skor double precision,
    olusturma_tarihi timestamptz not null default now()
);

-- Ornek tenant. Idempotent.
insert into tenantlar (id, ad) values ('ornek-firma', 'Örnek Firma')
on conflict (id) do nothing;
