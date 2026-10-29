from pathlib import Path
import hashlib
import json
import os
from sqlalchemy import create_engine, MetaData, Table, Column, String, Integer, JSON, select, func, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
metadata = MetaData()
books = Table("books", metadata, Column("id", String, primary_key=True), Column("payload", JSON, nullable=False))
sources = Table("sources", metadata, Column("id", String, primary_key=True), Column("payload", JSON, nullable=False))
passages = Table("passages", metadata,
    Column("id", String, primary_key=True), Column("book_id", String, nullable=False, index=True),
    Column("section", String, nullable=False, index=True), Column("ordinal", Integer, nullable=False),
    Column("payload", JSON, nullable=False))
refs = Table("passage_refs", metadata, Column("key", String, primary_key=True), Column("passage_id", String, nullable=False))
rate_limits = Table("rate_limits", metadata, Column("key", String, primary_key=True), Column("count", Integer, nullable=False))

def engine_for(url=None):
    (ROOT / "instance").mkdir(exist_ok=True)
    url = url or os.getenv("DATABASE_URL") or f"sqlite:///{ROOT / 'instance/grantha-books.db'}"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return create_engine(url, poolclass=NullPool, connect_args={"timeout": 30} if url.startswith("sqlite") else {})

def read_corpus(path=None):
    data = json.loads(Path(path or ROOT / "data/corpus.json").read_text(encoding="utf-8"))
    if data.get("schema_version") != 2 or data.get("source_type") != "uploaded_pdf":
        raise ValueError("This release requires the PDF book corpus. Run scripts/import_pdfs.py first.")
    source_ids = {s["id"] for s in data["sources"]}
    book_ids = {b["id"] for b in data["books"]}
    seen, aliases = set(), set()
    for p in data["passages"]:
        if p["id"] in seen or p["source_id"] not in source_ids or p["book_id"] not in book_ids:
            raise ValueError("Invalid corpus identity or provenance")
        seen.add(p["id"])
        for r in p["refs"]:
            key = p["book_id"] + ":" + r
            if key in aliases:
                raise ValueError(f"Ambiguous reference {key}")
            aliases.add(key)
        if not isinstance(p.get("page"), int) or p["page"] < 1 or p["id"] != f"{p['book_id']}:{p['page']}":
            raise ValueError("Invalid PDF page identity")
        actual = hashlib.sha256(p["text"].encode()).hexdigest()
        if actual != p["text_sha256"]:
            raise ValueError(f"Source integrity check failed: {p['id']}")
    for b in data['books']:
        ps=[p for p in data['passages'] if p['book_id']==b['id']]
        if sorted(p['page'] for p in ps)!=list(range(1,b['page_count']+1)):
            raise ValueError("Missing or duplicated PDF pages")
        if Path(b['stored_filename']).name!=b['stored_filename'] or not b['stored_filename'].endswith('.pdf'):
            raise ValueError("Invalid source filename")
    return data

def initialize(engine, corpus_path=None, replace=False):
    data = read_corpus(corpus_path)
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(774021)"))
        else:
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        metadata.create_all(conn)
        present = conn.scalar(select(func.count()).select_from(books))
        if present and not replace:
            existing=[r[0] for r in conn.execute(select(books.c.payload))]
            if {(b['id'], b.get('pdf_sha256')) for b in existing}!={(b['id'],b['pdf_sha256']) for b in data['books']}:
                raise ValueError("Database uses another corpus. Run python -m backend.manage reload-corpus, then restart.")
            return
        if replace:
            for table in (refs, passages, sources, books):
                conn.execute(table.delete())
            if engine.dialect.name == "postgresql":
                conn.execute(text("DROP TABLE IF EXISTS passage_embeddings"))
                conn.execute(text("DROP TABLE IF EXISTS embedding_config"))
        conn.execute(books.insert(), [{"id": b["id"], "payload": b} for b in data["books"]])
        conn.execute(sources.insert(), [{"id": s["id"], "payload": s} for s in data["sources"]])
        conn.execute(passages.insert(), [{"id": p["id"], "book_id": p["book_id"], "section": p["section"], "ordinal": p["ordinal"], "payload": p} for p in data["passages"]])
        conn.execute(refs.insert(), [{"key": p["book_id"] + ":" + r, "passage_id": p["id"]} for p in data["passages"] for r in p["refs"]])

class Store:
    def __init__(self, engine):
        self.engine = engine
        with engine.connect() as conn:
            self.books = [r[0] for r in conn.execute(select(books.c.payload))]
            self.sources = [r[0] for r in conn.execute(select(sources.c.payload))]
            self.passages = [r[0] for r in conn.execute(select(passages.c.payload).order_by(passages.c.book_id, passages.c.ordinal))]
        self.by_id = {p["id"]: p for p in self.passages}
        self.books.sort(key=lambda b: b.get('sort_order',99))
        # Original ordering is supplied by the edition manifest.
        self.by_ref = {p["book_id"] + ":" + ref: p for p in self.passages for ref in p["refs"]}
        self.by_book = {b["id"]: sorted((p for p in self.passages if p["book_id"] == b["id"]), key=lambda p: p["ordinal"]) for b in self.books}
        self.fingerprint = hashlib.sha256(json.dumps(self.passages, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def consume_ai_budget(self, limit):
        import time
        bucket = str(int(time.time() // 60))
        with self.engine.begin() as conn:
            row = conn.execute(text("INSERT INTO rate_limits (key, count) VALUES (:key, 1) ON CONFLICT (key) DO UPDATE SET count = rate_limits.count + 1 WHERE rate_limits.count < :limit RETURNING count"), {"key": bucket, "limit": limit}).first()
            conn.execute(rate_limits.delete().where(rate_limits.c.key < str(int(bucket)-2)))
            return row is not None
