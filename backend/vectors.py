import json
from sqlalchemy import text
from .providers import embeddings, embeddings_ready, embedding_settings

def config(store):
    return {**embedding_settings(), "fingerprint": store.fingerprint}

def is_ready(store):
    if store.engine.dialect.name != "postgresql" or not embeddings_ready():
        return False
    try:
        with store.engine.connect() as c:
            value = c.execute(text("SELECT payload FROM embedding_config WHERE id = 1")).scalar()
            return value == config(store)
    except Exception:
        return False

def index(store):
    if store.engine.dialect.name != "postgresql":
        raise ValueError("Semantic indexing requires PostgreSQL with pgvector.")
    cfg = config(store)
    dim = cfg["dimensions"]
    if not 1 <= dim <= 2000:
        raise ValueError("Use 1–2000 embedding dimensions for this vector index.")
    # Publish vectors atomically; failed calls leave no partially ready index.
    rows = []
    pages = [p for p in store.passages if len(p["text"].strip()) >= 60]
    for offset in range(0, len(pages), 16):
        batch = pages[offset:offset+16]
        contents = [(p.get("heading","")+"\n"+p["text"])[:6000] or "Image-only PDF page" for p in batch]
        for p, v in zip(batch, embeddings(contents)):
            rows.append({"id": p["id"], "book": p["book_id"], "v": json.dumps(v)})
        print(f"Embedded {min(offset + 16, len(pages))}/{len(pages)}", flush=True)
    with store.engine.begin() as c:
        c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        c.execute(text("DROP TABLE IF EXISTS passage_embeddings"))
        c.execute(text(f"CREATE TABLE passage_embeddings (id TEXT PRIMARY KEY, book_id TEXT NOT NULL, embedding vector({dim}) NOT NULL)"))
        c.execute(text("INSERT INTO passage_embeddings VALUES (:id, :book, CAST(:v AS vector))"), rows)
        c.execute(text("CREATE INDEX passage_embeddings_hnsw ON passage_embeddings USING hnsw (embedding vector_cosine_ops)"))
        c.execute(text("CREATE TABLE IF NOT EXISTS embedding_config (id INTEGER PRIMARY KEY, payload JSON NOT NULL)"))
        c.execute(text("INSERT INTO embedding_config VALUES (1, CAST(:p AS json)) ON CONFLICT (id) DO UPDATE SET payload=EXCLUDED.payload"), {"p": json.dumps(cfg)})

def hybrid(store, query, lexical, book_ids, limit=8):
    if not is_ready(store):
        return lexical[:limit], "lexical"
    v = embeddings([query], task="query")[0]
    with store.engine.connect() as c:
        sql = "SELECT id, embedding <=> CAST(:v AS vector) AS distance FROM passage_embeddings"
        params = {"v": json.dumps(v), "lim": 24}
        if book_ids:
            sql += " WHERE book_id = ANY(:books)"
            params["books"] = book_ids
        sql += " ORDER BY distance LIMIT :lim"
        semantic = [r[0] for r in c.execute(text(sql), params)]
    scores = {}
    for sequence in ([r["passage"]["id"] for r in lexical], semantic):
        for rank, pid in enumerate(sequence):
            scores[pid] = scores.get(pid, 0) + 1 / (60 + rank + 1)
    return [{"passage": store.by_id[pid], "score": round(score, 6), "match": "hybrid"} for pid, score in sorted(scores.items(), key=lambda r: r[1], reverse=True)[:limit]], "hybrid"
