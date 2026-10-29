# Architecture — Grantha 3.5

| Layer | Technology | Responsibility |
| --- | --- | --- |
| Frontend | React, JavaScript, Vite | PDF reading, independent answer scrolling, citations and account notebook |
| Runtime API | Flask, Python | Retrieval, original page delivery, answer validation and authentication |
| User storage | Supabase PostgreSQL, SQLAlchemy, Psycopg | Private users, sessions, notebooks and auth limits |
| Book cache | SQLite by default | Rebuildable original-page records, separate from users |
| Local RAG | Multilingual E5, ONNX Runtime, NumPy, SQLite FTS5 | CPU query embeddings, BM25 and reciprocal-rank fusion |
| Generation | Gemini 3.8 Flash, generateContent REST | One short schema-bound explanation |
| Production | Gunicorn, Docker | Built frontend and API on one origin |

No Next.js, TypeScript or FastAPI. Node owns frontend tooling and startup; Flask owns the backend.

## Source fidelity and retrieval

Stable physical-page IDs include `gitaasitis:164`. Each edition has its original filename, SHA-256, languages, outline and page count. Each page has a text hash, extraction method and original-page URL. Startup rejects missing or changed PDFs and inconsistent text hashes. Exact verse/canto spans are resolved before ranked search. Missing explicit references do not silently substitute another verse or edition.

The pinned MIT-licensed multilingual E5 small model yields 384-dimensional normalized embeddings using query/passage prefixes and attention-mask mean pooling. Token windows have at most 224 tokens, with 24-token overlap and exact source character offsets. Chunks never cross a physical page or edition. The builder checkpoints a float16 memory-mapped matrix and resumes only when corpus/model/chunk signatures match. It does not run during questions.

Startup verifies corpus/model fingerprints, index hashes and dimensions. Explicit work names narrow an otherwise collection-wide search without overriding a user-selected book filter. Book-filtered cosine candidates and SQLite FTS5/BM25 candidates are combined with reciprocal-rank fusion. A conservative source-term coverage gate rejects many unrelated English queries. Hindi/Sanskrit queries may use semantic candidates without lexical overlap in an English edition; a low cosine-similarity floor excludes weak matches. Both gates are relevance heuristics, not proof of answerability. Results retain distinct physical-page IDs. The model loads lazily and query vectors use a bounded in-memory cache. There are no remote embedding/model-download calls. ONNX Runtime telemetry is disabled before inference sessions. If local inference or the index is unavailable, original lexical search remains available.

`data/models/` records revision, licence and SHA-256 hashes. `data/rag-prepared/` ships compressed precomputed vectors, exact chunk offsets and their checksums. `setup-rag` downloads the pinned model once, restores the vectors and builds FTS without recomputing embeddings. The resulting `data/rag/` contains the matrix, FTS database and manifest. Neither stores user notebooks. Legacy remote embedding indexing is an explicit `embed-remote` command, unused by the reader.

## Questions and generation

Page scope uses the current page and immediate neighbours from the same edition. Book/all scope searches the index. Selected text must occur on the current page. A short follow-up can use the previous user question for retrieval; generated answers are never treated as source evidence.

Strict mode returns stored excerpts without generated claims. AI mode supplies at most three source excerpts, at most 1,400 characters each and 3,600 total, plus the question, language and one prior question truncated to 400 characters. Unresolved glyphs and OCR confidence below 55 are excluded.

The default is one stateless `streamGenerateContent` request to `gemini-3.8-flash`, using low thinking, a small JSON schema and short-answer instructions. SSE is accumulated on the server; unverified partial text is not displayed. No tools, uploads or model-side conversation state. Keys stay in Flask and authenticated redirects are rejected. Only completed STOP output with valid JSON is accepted; thought parts are ignored.

Every claim needs a known citation and a 12–500-character exact quotation from its supplied excerpt. A bad claim rejects the whole answer. The UI exposes the supporting quotation and original page. This verifies textual provenance, not semantic entailment or OCR correctness. Zero hallucinations cannot be guaranteed. The prompt distinguishes verse, translation and commentary; generated translations are labelled interpretations.

A successful answer cache is keyed by user, corpus, model, endpoint, question/language/history, source excerpts and verification mode. It retains at most 100 entries for 15 minutes. Errors and insufficient evidence are not cached.

The old Interactions transport and two-call checker remain opt-in via `GEMINI_API_MODE=interactions` and `GEMINI_SECOND_PASS=true`. `GEMINI_STREAMING` affects Interactions; `GEMINI_RESPONSE_MODE` selects GenerateContent stream or JSON. The default path has no second model call.

## Jobs, errors and deployment

The bounded two-thread queue permits one active question per user. Jobs use owner-checked opaque IDs, idempotent request IDs, cancellation, reconnection and 15-minute completed-result expiry. Browser polling is separate from generation and does not repeat it. Switching reader panels keeps jobs and conversation state mounted.

Defaults: 180-second response/socket wait, 360-second scheduling budget, and no automatic reader reposts. The legacy adapter alone retains optional bounded retries. GenerateContent timeout settings are independent of old Interactions timeout values. Ambiguous timeouts, quota/auth/billing errors and incomplete answers are not automatically repeated. Cancellation cannot retract work already accepted by Google; OS DNS/read delays can exceed scheduling estimates. The context-free connection check is authenticated, CSRF protected, rate limited, and subject to a per-account cooldown. Attempt diagnostics expose model/transport, counts, elapsed time and whether the stall preceded headers or occurred while reading. Provider logs contain safe error categories and attempt counts, not keys, prompts or raw responses.

Use one Gunicorn worker until a shared queue is added. Jobs, conversations and caches do not survive a restart/reload. Supabase availability and Google capacity/quota cannot be guaranteed locally. Docker copies all PDFs, the corpus and prepared vectors, then downloads the pinned model and prepares local FTS during the build. Runtime does not need OCR or model downloads. No deployment was performed.

## Reading and user state

CSS grid resizes or swaps the mounted book/assistant panes. Pointer capture, arrow keys, Home/End and double-click reset are supported. Side-by-side views need 820px content width; stacked views need 820px content height. Smaller views switch between full-height book and answer, retaining drafts. The conversation is a scrolling flex child with `min-height:0`; the compact composer is outside that scroll area. Themes are root-level CSS variables applied to all app surfaces. Scan filters affect display only. A measured scroll canvas supports 25–400% page zoom, fit modes, pointer panning and +/-/0 keys. Scaling preserves the viewed center; navigation resets panning. Higher zoom requests 2400/3600px images. Fullscreen keeps the reader mounted across page changes, with an expanded-view fallback.

Supabase private-schema tables hold scrypt password hashes, hashed session tokens, user notebooks and login limits. Flask enforces authorization, CSRF and session ownership. Notebook writes use revisions. Bookmark clicks save immediately; independent edits rebase, conflicting note edits retain a local draft, and lost acknowledgements reconcile. Legacy notebooks import only on explicit user action. Supabase Auth, email recovery and email verification are not implemented. See SUPABASE.md.

MuPDF rendering is serialized within each worker, with a bounded image cache. Original PDFs support byte-range downloads. Book reloading does not touch Supabase users; stop the app before rebuilding the local RAG index, then restart.

## API entry points

| Endpoint | Purpose |
| --- | --- |
| `/api/health` | Counts, corpus fingerprint, configured provider and local index readiness |
| `/api/auth/session`, `/api/auth/signup`, `/api/auth/login`, `/api/auth/logout` | Account/session management |
| `/api/me/notebook`, `/api/me/password` | Owner-only notebook and password operations |
| `/api/books`, `/api/sources`, `/api/passages/<id>` | Editions, provenance and original-page text |
| `/api/books/<id>/pdf`, `/api/books/<id>/pages/<page>/image` | Original PDF and actual rendered page |
| `/api/search` | Exact references or local hybrid retrieval |
| `/api/ask` | Strict sources or explanation; async requests create private jobs |
| `/api/ask/jobs/<id>`, `/api/ask/requests/<id>` | Job progress and lost-acknowledgement recovery |
| `/api/ask/jobs/<id>/cancel` | Discard a running answer |
| `/api/practice` | Source recognition exercise for self-study |
