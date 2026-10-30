"""SQLite BM25 RAG for small servers; no local embedding model is loaded."""
from contextlib import closing
import json
import os
import sqlite3
from .book_storage import digest
from .db import ROOT
from .retrieval import Retriever, tokenize, SYNONYMS, normalize


class LexicalIndex:
    def __init__(self, store, directory=None):
        self.store = store
        self.directory = directory or ROOT / 'data/rag'
        self.ready, self.reason, self.count = False, 'index_missing', 0
        if os.getenv('RAG_ENABLED', 'true').lower() != 'true':
            self.reason = 'disabled'; return
        try:
            manifest = json.loads((self.directory / 'manifest.json').read_text())
            if manifest['corpus'] != store.fingerprint:
                self.reason = 'index_outdated'; return
            if digest(self.directory / 'chunks.sqlite') != manifest['files']['chunks.sqlite']:
                self.reason = 'index_invalid'; return
            with self.connection() as c:
                self.count = c.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
            if self.count != manifest['count']: raise ValueError('Invalid chunk count')
            self.ready, self.reason = True, None
        except (OSError, ValueError, KeyError, sqlite3.Error):
            self.reason = 'index_missing_or_invalid'
    def connection(self):
        return closing(sqlite3.connect((self.directory / 'chunks.sqlite').resolve().as_uri() + '?mode=ro', uri=True))
    def status(self):
        return {'ready': self.ready, 'backend': 'sqlite_bm25', 'chunks': self.count,
                'reason': self.reason, 'embedding_api_calls': 0, 'semantic_enabled': False}
    def search(self, query, book_ids=None, limit=6):
        if not self.ready: return [], 'unavailable'
        base = list(dict.fromkeys(tokenize(query)))[:32]
        if not base: return [], 'local_bm25'
        expansions = {t: list(dict.fromkeys([t] + [normalize(s) for s in SYNONYMS.get(t, [])])) for t in base}
        scope = ' AND c.book_id IN (' + ','.join('?' for _ in book_ids) + ')' if book_ids else ''
        def expr(terms): return ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
        with self.connection() as c:
            supported = sum(bool(c.execute('SELECT 1 FROM chunk_search s JOIN chunks c ON c.idx=s.rowid WHERE chunk_search MATCH ?' + scope + ' LIMIT 1', [expr(ts)] + list(book_ids or [])).fetchone()) for ts in expansions.values())
            if supported / len(base) < .75: return [], 'local_bm25'
            terms = list(dict.fromkeys(t for ts in expansions.values() for t in ts))[:80]
            rows = c.execute('SELECT c.page_id,c.start,c.end,bm25(chunk_search) FROM chunk_search s JOIN chunks c ON c.idx=s.rowid WHERE chunk_search MATCH ?' + scope + ' ORDER BY bm25(chunk_search),c.idx LIMIT 80', [expr(terms)] + list(book_ids or [])).fetchall()
        result, seen = [], set()
        for pid, start, end, score in rows:
            if pid in seen: continue
            p = self.store.by_id[pid]
            while start > 0 and not p['text'][start-1].isspace(): start -= 1
            while end < len(p['text']) and not p['text'][end].isspace(): end += 1
            excerpt = {**p, 'reference_excerpt': p['text'][start:end], 'chunk_id': f'{pid}@{start}-{end}', 'excerpt_start': start, 'excerpt_end': end}
            result.append({'passage': excerpt, 'score': round(-score, 6), 'match': 'local_bm25'})
            seen.add(pid)
            if len(result) == limit: break
        return result, 'local_bm25'


class LowMemoryRetriever(Retriever):
    def __init__(self, store, index): self.store, self.index = store, index
    def search(self, query, book_ids=None, limit=8):
        exact = self.exact(query, book_ids)
        if exact is not None:
            return [{'passage': p, 'score': 1., 'match': 'exact_reference'} for p in exact[:limit]], 'exact'
        return self.index.search(query, book_ids, limit)
