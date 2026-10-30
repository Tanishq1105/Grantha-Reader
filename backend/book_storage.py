"""Bounded-memory book import and lazy page access. User data stays in Supabase."""
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
from sqlalchemy import Table, Column, String, select, func, text
from .db import metadata, books, sources, passages, refs, ROOT

cache_meta = Table('book_cache_meta', metadata, Column('key', String, primary_key=True), Column('value', String, nullable=False))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def items(path, prefix):
    import ijson
    with Path(path).open('rb') as f:
        yield from ijson.items(f, prefix, use_float=True)


def fingerprint(conn):
    # Same bytes as json.dumps(ordered_passages, sort_keys=True, ensure_ascii=False).
    h = hashlib.sha256(b'[')
    first = True
    for row in conn.execute(select(passages.c.payload).order_by(passages.c.book_id, passages.c.ordinal)).yield_per(32):
        if not first: h.update(b', ')
        first = False
        h.update(json.dumps(row[0], sort_keys=True, ensure_ascii=False).encode())
    h.update(b']')
    return h.hexdigest()


def initialize(engine, corpus_path=None, replace=False):
    path = Path(corpus_path or ROOT / 'data/corpus.json')
    checksum = digest(path)
    with engine.begin() as c:
        if engine.dialect.name == 'postgresql': c.execute(text('SELECT pg_advisory_xact_lock(774021)'))
        else: c.exec_driver_sql('BEGIN IMMEDIATE')
        metadata.create_all(c)
        cached = {r[0]: r[1] for r in c.execute(select(cache_meta))}
        if not replace and cached.get('corpus_sha256') == checksum: return
        bs, ss = list(items(path, 'books.item')), list(items(path, 'sources.item'))
        if next(items(path, 'schema_version'), None) != 2 or next(items(path, 'source_type'), None) != 'uploaded_pdf':
            raise ValueError('This release requires the PDF book corpus.')
        existing = [r[0] for r in c.execute(select(books.c.payload))]
        if existing and not replace and {(b['id'], b.get('pdf_sha256')) for b in existing} != {(b['id'], b['pdf_sha256']) for b in bs}:
            raise ValueError('Database uses another corpus. Run python -m backend.manage reload-corpus, then restart.')
        for table in (refs, passages, sources, books, cache_meta): c.execute(table.delete())
        if replace and engine.dialect.name == 'postgresql':
            c.execute(text('DROP TABLE IF EXISTS passage_embeddings'))
            c.execute(text('DROP TABLE IF EXISTS embedding_config'))
        c.execute(books.insert(), [{'id': b['id'], 'payload': b} for b in bs])
        c.execute(sources.insert(), [{'id': s['id'], 'payload': s} for s in ss])
        bids, sids = {b['id'] for b in bs}, {s['id'] for s in ss}
        seen, aliases = set(), set()
        page_numbers = {bid: set() for bid in bids}
        batch = []
        def flush():
            if not batch: return
            c.execute(passages.insert(), [{'id': p['id'], 'book_id': p['book_id'], 'section': p['section'], 'ordinal': p['ordinal'], 'payload': p} for p in batch])
            links = [{'key': p['book_id'] + ':' + r, 'passage_id': p['id']} for p in batch for r in p['refs']]
            if links: c.execute(refs.insert(), links)
            batch.clear()
        for p in items(path, 'passages.item'):
            if p['id'] in seen or p['source_id'] not in sids or p['book_id'] not in bids:
                raise ValueError('Invalid corpus identity or provenance')
            if type(p.get('page')) is not int or p['page'] < 1 or p['id'] != f"{p['book_id']}:{p['page']}":
                raise ValueError('Invalid PDF page identity')
            if hashlib.sha256(p['text'].encode()).hexdigest() != p['text_sha256']:
                raise ValueError('Source integrity check failed: ' + p['id'])
            for r in p['refs']:
                key = p['book_id'] + ':' + r
                if key in aliases: raise ValueError('Ambiguous reference ' + key)
                aliases.add(key)
            seen.add(p['id']); page_numbers[p['book_id']].add(p['page']); batch.append(p)
            if len(batch) == 32: flush()
        flush()
        for b in bs:
            if page_numbers[b['id']] != set(range(1, b['page_count'] + 1)):
                raise ValueError('Missing or duplicated PDF pages')
            if Path(b['stored_filename']).name != b['stored_filename'] or not b['stored_filename'].endswith('.pdf'):
                raise ValueError('Invalid source filename')
        values = {'corpus_sha256': checksum, 'fingerprint': fingerprint(c)}
        c.execute(cache_meta.insert(), [{'key': k, 'value': v} for k, v in values.items()])


class PageSequence(Sequence):
    def __init__(self, engine, book_id=None, section=None):
        self.engine, self.book_id, self.section = engine, book_id, section
    def query(self, col):
        q = select(col).select_from(passages)
        if self.book_id is not None: q = q.where(passages.c.book_id == self.book_id)
        if self.section is not None: q = q.where(passages.c.section == self.section)
        return q
    def __len__(self):
        with self.engine.connect() as c: return c.scalar(self.query(func.count()))
    def __iter__(self):
        with self.engine.connect() as c:
            for row in c.execute(self.query(passages.c.payload).order_by(passages.c.book_id, passages.c.ordinal)).yield_per(32): yield row[0]
    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(len(self))
            if step != 1: return [self[i] for i in range(start, stop, step)]
            with self.engine.connect() as c:
                return [r[0] for r in c.execute(self.query(passages.c.payload).order_by(passages.c.book_id, passages.c.ordinal).offset(start).limit(max(0, stop-start)))]
        if key < 0: key += len(self)
        if key < 0: raise IndexError(key)
        with self.engine.connect() as c:
            row = c.execute(self.query(passages.c.payload).order_by(passages.c.book_id, passages.c.ordinal).offset(key).limit(1)).first()
        if row is None: raise IndexError(key)
        return row[0]


class PageMap(Mapping):
    def __init__(self, engine, aliases=False): self.engine, self.aliases = engine, aliases
    def __getitem__(self, key):
        q = select(passages.c.payload)
        if self.aliases: q = q.join(refs, refs.c.passage_id == passages.c.id).where(refs.c.key == key)
        else: q = q.where(passages.c.id == key)
        with self.engine.connect() as c: row = c.execute(q).first()
        if row is None: raise KeyError(key)
        return row[0]
    def __iter__(self):
        with self.engine.connect() as c:
            for row in c.execute(select(refs.c.key if self.aliases else passages.c.id)).yield_per(32): yield row[0]
    def __len__(self):
        with self.engine.connect() as c: return c.scalar(select(func.count()).select_from(refs if self.aliases else passages))
