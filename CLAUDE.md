# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Multi-tenant RAG (retrieval-augmented generation) chatbot. Companies upload PDF policy/rule documents; employees ask questions in Turkish and get answers grounded strictly in the uploaded documents. Everything is `tenant_id`-scoped — this was generalized from a single-company tool (originally "English Home"), so no code should assume a single tenant.

The codebase and all identifiers (variable/function/table names, UI text) are in **Turkish**. Keep new code consistent with this — don't switch to English names in Python/C# identifiers.

Two independent services that talk over HTTP:

- **Python/FastAPI backend** (repo root) — embeds PDFs, stores/queries vectors in Postgres, calls an LLM to produce answers.
- **ASP.NET Core Razor Pages frontend** (`arayuz/`) — login, user/role management, document upload, and the chat UI. Calls the Python API at `http://127.0.0.1:8000`.

Both services read `SUPABASE_DB_URL` from the same root-level `.env` (Postgres/Supabase with pgvector). The .NET side loads it via `DotNetEnv.Env.Load("../.env")` in `Program.cs`.

## Commands

### Python backend
```bash
python -m venv .venv                 # already present as .venv/
.venv/Scripts/activate                # Windows
pip install -r requirements.txt
uvicorn servis:app --reload           # run the API (must be on 127.0.0.1:8000 for arayuz to reach it)
```

Ad-hoc test/debug scripts (not a pytest suite — run directly, read printed output):
```bash
python cevap_test.py        # runs a fixed list of Q/A pairs through cevapla(), checks VAR/YOK expectations by eye
python benzerlik_test.py    # prints top-3 similarity scores per test question, for tuning ESIK (the retrieval threshold)
python db_test.py           # sanity-checks the DB connection and row count
python tani.py               # sanity-checks that OPENROUTER_API_KEY loaded correctly
python indeksle.py --tenant <id> --pdf <path>   # index a PDF from the CLI (defaults: tenant=english-home, data/kurallar.pdf)
```

### .NET frontend (`arayuz/`)
```bash
cd arayuz
dotnet run                  # dev server (needs the Python API already running for chat/upload to work)
dotnet build
```

## Architecture

### RAG pipeline (Python)
`pdf_oku.py` (extract text) → `parcala.py` (fixed-size chunking: 300 chars, 50-char overlap, `parcalar_uret`) → `embed.py` (loads `BAAI/bge-m3` via `sentence-transformers`, shared singleton `model`) → `indeksle.py` (embeds chunks, inserts into `belgeler` + `parcalar` tables, both keyed by `tenant_id`).

Query path: `sorgu.py::cevapla(soru, tenant_id)` embeds the question, runs a pgvector cosine-distance `ORDER BY ... LIMIT 3` query **filtered by `tenant_id`**, and refuses to answer if the top score is below `ESIK` (0.54). If above threshold, the top-3 chunks are passed to `llm.py::sor()`, which calls OpenRouter (`nvidia/nemotron-3-ultra-550b-a55b:free`) with a strict system prompt: answer only from literal context, refuse otherwise, Turkish, max 2 sentences, no calculation/inference.

`servis.py` exposes this as FastAPI:
- `POST /sor` — `{soru, tenant_id}` → `{cevap, skor}`
- `POST /indeksle` — multipart form (`tenant_id`, `dosya_adi`, `dosya`) → writes a temp file, runs `indeksle()`, then deletes the temp file

Any change to chunking/embedding must stay tenant-isolated — check `where tenant_id = %s` is present in new queries.

### Frontend (`arayuz/`)
Cookie auth (`"Cerez"` scheme) set up in `Program.cs`. On login (`Pages/Giris.cshtml.cs`), the user's `tenant_id`, `rol` (role), `firma_adi` (company name), and optional `logo_url` are looked up by joining `kullanicilar` → `tenantlar` and stored as claims — every subsequent page reads tenant scoping from `User.FindFirst("tenant_id")`, not from route/query params.

Two roles: `kullanici` (regular) and `yonetici` (admin/manager), enforced via `[Authorize(Roles = "yonetici")]` on page models (e.g. `Yukle`, `Logo`, `Kullanicilar`, and the delete handler in `Belgeler`). Each tenant additionally has a `sahip_eposta` (owner email) in the `tenantlar` table — only the owner can demote another admin back to `kullanici` (see `Kullanicilar.cshtml.cs::OnPostDusur`); any admin can promote (`OnPostYukselt`).

`Db.cs::Baglan()` parses `SUPABASE_DB_URL` into an `NpgsqlConnection` manually (splits user/pass out of the URI) rather than using a standard Npgsql connection string directly.

Passwords are hashed with PBKDF2-SHA256 (100k iterations, random 16-byte salt) in `Sifre.cs`; format is `base64(salt):base64(hash)`.

Pages call the Python API directly with a hardcoded `http://127.0.0.1:8000` base URL (see `Index.cshtml.cs` for `/sor`, `Yukle.cshtml.cs` for `/indeksle`) — both services are expected to run together locally.

### Database (Postgres/Supabase + pgvector)
Tables referenced across the codebase (no migrations dir in the repo — schema lives in Supabase):
- `tenantlar` (id, ad, sahip_eposta, logo_url)
- `kullanicilar` (id, eposta, sifre_ozeti, tenant_id, rol)
- `belgeler` (id, tenant_id, dosya_adi, yukleme_tarihi)
- `parcalar` (tenant_id, bolum, metin, vektor, belge_id) — `vektor` is a pgvector column queried with `<=>` (cosine distance)

## Notes

- No automated test framework (pytest/xunit) is configured — the `*_test.py` files at the repo root are manual scripts, not a CI suite.
- The retrieval threshold `ESIK` in `sorgu.py` (0.54) was empirically tuned; use `benzerlik_test.py` output before changing it.
- Uploaded PDFs are processed via temp files and not retained on disk by the Python service; document/tenant records live only in Postgres. Logos, however, are persisted to `arayuz/wwwroot/logolar/` on the .NET host.
