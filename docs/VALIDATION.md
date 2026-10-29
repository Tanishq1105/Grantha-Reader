# Validation — Grantha 3.5.0

Checked on 2026-10-26. No real Gemini API key or Supabase credentials were available; no deployment was performed. Live provider capacity, quota, latency and account connectivity remain unverified.

## Release checks

| Check | Result |
| --- | --- |
| Python regression tests | 224 passed; 1 optional PostgreSQL integration test skipped |
| JavaScript utilities / React | 3 / 26 tests passed |
| Production frontend | Vite build passed |
| Browser checks | Chromium at 1440×900, 1024×768 and 390×844 |
| Original books | All 17 PDFs preserved from the verified 3.4 package |
| Prepared retrieval index | Unchanged 73,819 chunks, 384-dimensional local embeddings |

The Python suite covers authentication/CSRF, private notebooks, lost save acknowledgements, bookmark merging, source integrity, reference lookup, queue ownership, idempotency, cancellation and safe provider diagnostics. New tests exercise streamed Unicode JSON, ignored thought parts, explicit completion, malformed/truncated SSE, token/safety finishes, forged quotations, one-call 503 and timeout behavior, request/body timing phases, context-free connection checks, account cooldowns, sharper 3600-pixel page images and noisy OCR filtering.

Real pinned E5 inference is tested on synthetic documents with English, Hindi and Sanskrit questions, including Hindi phrasing with no lexical overlap. Book filtering, unrelated English questions, stale fingerprints and Unicode source offsets are checked. The entire Python suite runs with kernel restrictions denying network socket creation and sends. These tests do not contact Gemini or Supabase.

JavaScript utility and React tests cover bookmarks, drafts, resizable panels, fullscreen, root-level theme persistence, small-screen view switching, home questions, zoom bounds, keyboard zoom, retained zoom after fullscreen changes and explicit connection diagnostics.

Browser checks use the production frontend with a real Gita PDF page image and simulated account/API/AI responses. At all three viewports, Fit page had no page overflow, 400% zoom could scroll in both axes, dragging panned the image, native fullscreen retained zoom, and resetting to Fit page worked. Long answers scrolled independently of the composer; no horizontal document overflow or JavaScript errors occurred. The explicit connection-check button made one simulated request, then a retry displayed a simulated long answer. Desktop and mobile screenshots were visually reviewed. These checks do not establish live Gemini success.

Prepared-index installation tests cover restored vectors/FTS, repeat setup, changed corpus, tampered data, verified public downloads, checksum failures and safe replacement. The unchanged collection index retains the prior 3.4 baseline of 14 collection retrieval smoke checks in `RETRIEVAL_SMOKE.json`; those collection-wide checks were not rerun for this release. The 3.4 baseline verified all original PDF SHA-256 hashes. The 3.5 archive preserves the same PDF entries and validates the archive CRCs.

## Limits

A correct quotation does not prove an AI claim follows from it. Retrieval scores, OCR and interpretation can be wrong. Hindi/Sanskrit retrieval quality varies, especially for rare compounds and poor scans. No complete semantic-quality evaluation over all 23,348 pages was performed.

Provider failures are simulated in tests. The new single-request transport, smaller context and diagnostics cannot guarantee provider availability or repair a project quota or network problem. Use **Test Gemini connection** after a failure to test the same server key and transport without books, and copy its safe diagnostic result.

Account tests use temporary SQLite injection; production user storage remains Supabase PostgreSQL. No native Windows, Docker deployment, optional remote pgvector, comprehensive accessibility or cross-browser audit was performed.

Use one production worker with the current in-process queue. Restarts lose active jobs/cache, and cancellation cannot retract a provider request already accepted. Keep existing account configuration and notebooks when updating. The full ZIP includes compressed precomputed vectors and source offsets. One-time `setup-rag` downloads the pinned public model and builds local FTS; no embedding build is needed for the unchanged books. Model downloads are simulated in tests; successful live download from the user's network is unverified.
