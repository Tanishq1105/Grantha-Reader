# Grantha Reader: 512 MiB Render update

This ZIP contains replacement code files, not a second full book collection.
It targets Tanishq1105/Grantha-Reader at commit 72332903aa3e1cbf24be85810b5f0ab5e2b0d334.

1. Back up your project folder.
2. Copy the ZIP contents into C:\Projects\Grantha and replace matching files.
   Keep your .env, PDFs, models metadata and data/rag-prepared folder.
3. Run these commands from that folder:

```bash
git add Dockerfile requirements.txt backend/app.py backend/db.py backend/book_storage.py backend/low_memory_rag.py backend/setup_rag.py tests/test_low_memory.py tests/test_setup_rag.py RENDER_512MB_FIX.md
git commit -m "Reduce memory for Render deployment"
git push origin main
```

4. In Render Environment, add LOW_MEMORY_MODE=true. Keep RAG_ENABLED=true
   and your existing Gemini, Supabase and production settings.
5. Deploy the latest commit. Leave the Docker Command override empty.
6. Visit /api/health after deployment. Expect rag.backend=sqlite_bm25,
   rag.ready=true and rag.semantic_enabled=false.

## What changed

- Stream corpus imports in small batches; verify original page hashes.
- Store pages in SQLite and load only requested pages. User accounts and
  notebooks remain in Supabase.
- Prepare the book cache during Docker build and reuse it at startup.
- Read PDFs incrementally when checking integrity.
- Use the prepared SQLite BM25 chunk index in low-memory mode; no E5 model
  downloads or inference. Gemini still receives retrieved original excerpts.
- Preserve exact verse lookup, existing citation validation, and Gemini code.
- Limit cached page images and cap low-memory raster output at four million
  pixels. Reader zoom remains available; extreme zoom has less detail.
- Sample practice pages without retaining a whole book in memory.

## Tradeoff

BM25 matches words and the existing Hindi/Sanskrit synonym mappings. It is
still retrieval-augmented generation, but it is not embedding-based semantic
search. Paraphrases and cross-language questions may retrieve less effectively.
Unsupported questions still produce no grounded answer. To restore local E5
on a larger server, set LOW_MEMORY_MODE=false and rerun setup-rag during build.
Do not use that setting on the 512 MiB instance.

## Validation

79 tests passed: account/auth/notebook, reader/API, low-memory regression and
prepared-index setup checks. Real books: 17 PDFs, 23,348 pages, 73,819 chunks.
A local Python-process test measured about 197 MiB at startup and 290 MiB peak
while searching, loading all covers, rendering several large pages, and
running a practice exercise. These are process RSS measurements, not a Render
container limit test; concurrent load and platform overhead can increase usage.
Live Gemini requests and production Supabase were not tested with your keys.

Local use after copying this update:

```bash
python -m pip install -r requirements.txt
```

Set LOW_MEMORY_MODE=true in your local .env only if you want the same profile.
Your normal local embedding mode remains available otherwise.
