"""Offline multilingual E5 embeddings and BM25 retrieval over original book excerpts."""
from pathlib import Path
from functools import lru_cache
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import numpy as np
from .db import ROOT
from .retrieval import tokenize, SYNONYMS, normalize

MODEL_DIR=ROOT/'data/models/multilingual-e5-small'
INDEX_DIR=ROOT/'data/rag'
VERSION=1
MAX_TOKENS=224
OVERLAP_TOKENS=24

def usable(p):
    return len(p['text'].strip())>=60 and not p.get('unresolved_glyphs',0) and not (p.get('extraction')=='ocr' and (p.get('ocr_confidence') or 0)<55)

class Encoder:
    def __init__(self,directory=MODEL_DIR):
        import onnxruntime as ort
        # Disable platform telemetry before creating any inference session.
        # Retrieval is entirely local; no analytics or embedding API is used.
        ort.disable_telemetry_events()
        from tokenizers import Tokenizer
        manifest=json.loads((directory/'manifest.json').read_text())
        for name in ['model.onnx','tokenizer.json']:
            if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=manifest['files'][name]['sha256']:
                raise ValueError('The local embedding model has changed. Restore it from the full release.')
        self.tokenizer=Tokenizer.from_file(str(directory/'tokenizer.json'))
        self.tokenizer.enable_padding(pad_id=1,pad_token='<pad>')
        self.tokenizer.enable_truncation(max_length=256)
        options=ort.SessionOptions()
        options.intra_op_num_threads=max(1,min(8,int(os.getenv('RAG_CPU_THREADS','2'))))
        options.inter_op_num_threads=1
        try:self.session=ort.InferenceSession(str(directory/'model.onnx'),options,providers=['CPUExecutionProvider'])
        except Exception:raise RuntimeError('The local embedding model could not be loaded.') from None
        self.inputs={x.name for x in self.session.get_inputs()};self.lock=threading.Lock()

    def encode(self,texts,query=False):
        with self.lock:
            encoded=self.tokenizer.encode_batch([('query: ' if query else 'passage: ')+t for t in texts])
            feed={'input_ids':np.asarray([e.ids for e in encoded],dtype=np.int64),
                  'attention_mask':np.asarray([e.attention_mask for e in encoded],dtype=np.int64)}
            if 'token_type_ids' in self.inputs:feed['token_type_ids']=np.zeros_like(feed['input_ids'])
            try:output=self.session.run(None,{k:v for k,v in feed.items() if k in self.inputs})[0]
            except Exception:raise RuntimeError('Local embedding inference failed.') from None
        mask=feed['attention_mask'][...,None]
        vectors=((output*mask).sum(axis=1)/mask.sum(axis=1).clip(min=1)).astype(np.float32)
        vectors/=np.linalg.norm(vectors,axis=1,keepdims=True).clip(min=1e-12)
        if vectors.shape!=(len(texts),384) or not np.isfinite(vectors).all():raise ValueError('Invalid local embedding')
        return vectors

def chunks_for(p,tokenizer):
    if not usable(p):return
    text=p['text'];offsets=[o for o in tokenizer.encode(text,add_special_tokens=False).offsets if o[1]>o[0]];pos=0
    while pos<len(offsets):
        stop=min(pos+MAX_TOKENS,len(offsets))
        if stop<len(offsets):
            for candidate in range(stop,pos+MAX_TOKENS*3//4,-1):
                end=offsets[candidate-1][1]
                if text[end-1:end] in '.!?।॥\n' or '\n' in text[end:offsets[candidate][0]]:
                    stop=candidate;break
        start,end=offsets[pos][0],offsets[stop-1][1]
        if len(text[start:end].strip())>=40:yield {'page_id':p['id'],'book_id':p['book_id'],'start':start,'end':end}
        if stop==len(offsets):break
        pos=max(pos+1,stop-OVERLAP_TOKENS)

def build(store,directory=INDEX_DIR,batch_size=32):
    from tokenizers import Tokenizer
    directory.mkdir(parents=True,exist_ok=True)
    model=json.loads((MODEL_DIR/'manifest.json').read_text())
    tok=Tokenizer.from_file(str(MODEL_DIR/'tokenizer.json'));tok.no_truncation();tok.no_padding()
    rows=[c for p in store.passages for c in chunks_for(p,tok)]
    signature={'version':VERSION,'corpus':store.fingerprint,'model_sha256':model['files']['model.onnx']['sha256'],
        'tokenizer_sha256':model['files']['tokenizer.json']['sha256'],'tokens':MAX_TOKENS,'overlap':OVERLAP_TOKENS,'count':len(rows),'dimensions':384}
    checkpoint=directory/'build-progress.json';start=0
    if checkpoint.exists():
        previous=json.loads(checkpoint.read_text())
        if previous.get('signature')==signature and (directory/'vectors.build.npy').exists():start=previous['completed']
    (directory/'rows.build.json').write_text(json.dumps(rows))
    matrix=np.lib.format.open_memmap(directory/'vectors.build.npy',mode='r+' if start else 'w+',dtype=np.float16,shape=(len(rows),384))
    encoder=Encoder();began=time.monotonic();print(f'{len(rows)} chunks; continuing at {start}',flush=True)
    for offset in range(start,len(rows),batch_size):
        batch=rows[offset:offset+batch_size]
        matrix[offset:offset+len(batch)]=encoder.encode([store.by_id[c['page_id']]['text'][c['start']:c['end']] for c in batch])
        if offset%(batch_size*20)==0 or offset+len(batch)==len(rows):
            matrix.flush();temp=directory/'progress.tmp';temp.write_text(json.dumps({'signature':signature,'completed':offset+len(batch)}));temp.replace(checkpoint)
            print(f'Embedded {offset+len(batch)}/{len(rows)} ({time.monotonic()-began:.0f}s)',flush=True)
    matrix.flush();del matrix
    database=directory/'chunks.build.sqlite';database.unlink(missing_ok=True)
    with sqlite3.connect(database) as c:
        c.execute('CREATE TABLE chunks (idx INTEGER PRIMARY KEY,page_id TEXT,book_id TEXT,start INTEGER,end INTEGER)')
        c.execute("CREATE VIRTUAL TABLE chunk_search USING fts5(terms, tokenize='unicode61 remove_diacritics 0')")
        c.executemany('INSERT INTO chunks VALUES (?,?,?,?,?)',[(i,r['page_id'],r['book_id'],r['start'],r['end']) for i,r in enumerate(rows)])
        c.executemany('INSERT INTO chunk_search(rowid,terms) VALUES (?,?)',[(i,' '.join(tokenize(store.by_id[r['page_id']]['text'][r['start']:r['end']]))) for i,r in enumerate(rows)])
        c.execute('CREATE INDEX chunks_book ON chunks(book_id)');c.execute("INSERT INTO chunk_search(chunk_search) VALUES('optimize')")
    c.close()  # Release the SQLite file before replacing it on Windows.
    (directory/'vectors.build.npy').replace(directory/'vectors.npy');database.replace(directory/'chunks.sqlite')
    signature['files']={n:hashlib.sha256((directory/n).read_bytes()).hexdigest() for n in ['vectors.npy','chunks.sqlite']}
    temp=directory/'manifest.tmp';temp.write_text(json.dumps(signature,indent=2)+'\n');temp.replace(directory/'manifest.json')
    checkpoint.unlink(missing_ok=True);(directory/'rows.build.json').unlink(missing_ok=True)
    print('Local RAG index ready. No Gemini API calls were used.',flush=True)

class RagIndex:
    def __init__(self,store,directory=INDEX_DIR):
        self.store,self.directory=store,directory;self.ready=False;self.reason='index_missing';self._encoder=None;self._load_lock=threading.Lock()
        if os.getenv('RAG_ENABLED','true').lower()!='true':self.reason='disabled';return
        try:
            manifest=json.loads((directory/'manifest.json').read_text());model=json.loads((MODEL_DIR/'manifest.json').read_text())
            if manifest['version']!=VERSION or manifest['corpus']!=store.fingerprint or any(manifest[k]!=model['files'][n]['sha256'] for k,n in [('model_sha256','model.onnx'),('tokenizer_sha256','tokenizer.json')]):
                self.reason='index_outdated';return
            for n in ['model.onnx','tokenizer.json']:
                if not (MODEL_DIR/n).is_file():self.reason='model_missing';return
            for name,digest in manifest['files'].items():
                if name not in {'vectors.npy','chunks.sqlite'} or hashlib.sha256((directory/name).read_bytes()).hexdigest()!=digest:raise ValueError('Invalid index')
            with self.connection() as c:self.rows=c.execute('SELECT idx,page_id,book_id,start,end FROM chunks ORDER BY idx').fetchall()
            self.matrix=np.load(directory/'vectors.npy',mmap_mode='r',allow_pickle=False)
            if self.matrix.shape!=(manifest['count'],384) or len(self.rows)!=manifest['count']:raise ValueError('Invalid index size')
            self.book_ids=np.asarray([r[2] for r in self.rows]);self.ready=True;self.reason=None
        except (OSError,ValueError,KeyError,sqlite3.Error):self.reason='index_missing_or_invalid'

    def connection(self):return closing(sqlite3.connect((self.directory/'chunks.sqlite').resolve().as_uri()+'?mode=ro',uri=True))
    def status(self):return {'ready':self.ready,'backend':'local_multilingual_e5','chunks':len(self.rows) if self.ready else 0,'reason':self.reason,'embedding_api_calls':0}
    @lru_cache(maxsize=128)
    def query_vector(self,query):
        with self._load_lock:
            if self._encoder is None:self._encoder=Encoder()
        return self._encoder.encode([query],query=True)[0]

    def _passage(self,idx):
        _,pid,_,start,end=self.rows[idx];p=self.store.by_id[pid]
        # Expand context to full words when a token window bisects a word.
        while start>0 and not p['text'][start-1].isspace():start-=1
        while end<len(p['text']) and not p['text'][end].isspace():end+=1
        return {**p,'reference_excerpt':p['text'][start:end],'chunk_id':f'{pid}@{start}-{end}','excerpt_start':start,'excerpt_end':end}

    def search(self,query,book_ids=None,limit=6):
        if not self.ready:return [],'unavailable'
        base=list(dict.fromkeys(tokenize(query)))[:32]
        if not base:return [],'local_hybrid'
        # Do not require Hindi/Sanskrit words to occur in an English edition.
        cross_language=all(re.fullmatch(r'[\u0900-\u097f]+',t) for t in base)
        expansions={t:list(dict.fromkeys([t]+[normalize(s) for s in SYNONYMS.get(t,[])])) for t in base}
        scope=(' AND c.book_id IN ('+','.join('?' for _ in book_ids)+')') if book_ids else ''
        with self.connection() as c:
            supported=0
            for terms in expansions.values():
                expr=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
                supported+=bool(c.execute('SELECT 1 FROM chunk_search s JOIN chunks c ON c.idx=s.rowid WHERE chunk_search MATCH ?'+scope+' LIMIT 1',[expr]+list(book_ids or [])).fetchone())
            if (not supported or supported/len(base)<.75) and not cross_language:return [],'local_hybrid'
            terms=list(dict.fromkeys(x for values in expansions.values() for x in values))[:40]
            expr=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
            lexical=[r[0] for r in c.execute('SELECT s.rowid FROM chunk_search s JOIN chunks c ON c.idx=s.rowid WHERE chunk_search MATCH ?'+scope+' ORDER BY bm25(chunk_search) LIMIT 40',[expr]+list(book_ids or []))]
        ids=np.flatnonzero(np.isin(self.book_ids,book_ids)) if book_ids else np.arange(len(self.rows))
        if not len(ids):return [],'local_hybrid'
        # Keep the original question, adding known source-language terms for
        # short Hindi/Sanskrit queries over predominantly English editions.
        semantic_query=query
        if cross_language:
            aliases=list(dict.fromkeys(t for terms in expansions.values() for t in terms if re.fullmatch(r'[a-z]+',t)))[:12]
            if aliases:semantic_query+=' '+ ' '.join(aliases)
        values=self.matrix[ids].astype(np.float32);scores=(values@self.query_vector(semantic_query))/np.linalg.norm(values,axis=1).clip(min=1e-12)
        if cross_language and float(scores.max())<.76:return [],'local_hybrid'
        n=min(40,len(ids));top=np.argpartition(-scores,n-1)[:n];semantic=[int(ids[i]) for i in top[np.argsort(-scores[top])]]
        rank=Counter()
        for sequence in [semantic,lexical]:
            for i,idx in enumerate(sequence):rank[idx]+=1/(40+i)
        output=[];seen=set()
        for idx,score in rank.most_common():
            p=self._passage(idx)
            if p['id'] in seen:continue
            seen.add(p['id']);output.append({'passage':p,'score':round(score,6),'match':'local_hybrid'})
            if len(output)==limit:break
        return output,'local_hybrid'
