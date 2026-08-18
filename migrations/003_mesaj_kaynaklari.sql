-- RAG kaynak izlenebilirligi (source / provenance) - P1: veritabani temeli.
--
-- RERUN-SAFE: 001/002 ile AYNI stil - bu script ayni Postgres/Supabase
-- veritabaninda birden fazla kez calistirilabilir.
--
-- Bu script sadece SEMAYI hazirlar - sorgu.py / servis.py / Index.cshtml(.cs)
-- HENUZ bu tabloyu kullanmiyor (ayri bir entegrasyon adiminda baglanacak).
-- Mevcut mesajlar icin hicbir satir eklenmez (backfill YAPILMAZ) - eski
-- cevaplar sadece SIFIR kaynak satirina sahip olur.
--
-- BILINCLI TASARIM KARARI: dosya_adi/dosya_yolu BURADA TUTULMAZ, sadece
-- mesaj<->belge iliskisi id ile saklanir. Kullanicinin departman uyeligi
-- sohbetten SONRA degisebilir - eger dosya adi burada "donuk" bir kopya
-- olarak saklansaydi, eski bir sohbet acildiginda kullanici ARTIK erisim
-- yetkisi olmayan bir belgenin adini gorebilirdi (yetkilendirmeden BAGIMSIZ
-- bir sizinti). Bunun yerine SADECE belge_id saklanir - dosya adi/
-- erisilebilirlik HER SEFERINDE render aninda GUNCEL yetkilendirme
-- kurallariyla (bkz. migrations/002_erisim_kontrolu.sql) cozulur; erisim
-- sonradan iptal edilmisse kaynak o an gosterilmez.

-- 1) mesaj_kaynaklari: bir asistan mesajina RAG baglaminda hangi belge(ler)in
--    saglandigini tutar, cok-cok. id yok, dogal anahtar (mesaj_id, belge_id)
--    PRIMARY KEY olarak yeterli - kullanici_departmanlari (bkz. migrations/
--    002) ile AYNI desen: ayni belgeden birden fazla parca getirilse bile
--    TEK bir satir olusur (composite PK yinelenen ciftleri kendiliginden
--    engeller).
--    - mesaj_id -> mesajlar.id ON DELETE CASCADE: bir mesaj silinince kaynak
--      satirlari yetim KALMAZ.
--    - belge_id -> belgeler.id ON DELETE CASCADE: bir belge silinince o
--      belgeye ait kaynak satirlari da silinir - gecmis provenance'da
--      "donuk isim/stale link" olarak KALMAZ, sadece o mesajin kaynak
--      listesinden dusuk (mesajin kendisi/metni ETKILENMEZ).
create table if not exists mesaj_kaynaklari (
    mesaj_id bigint not null references mesajlar(id) on delete cascade,
    belge_id bigint not null references belgeler(id) on delete cascade,
    olusturma_tarihi timestamptz not null default now(),
    primary key (mesaj_id, belge_id)
);
