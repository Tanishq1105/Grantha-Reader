"""Prepare the shipped vectors and download a pinned public model once.

No embedding computation, Gemini request, user database or credentials are used.
Run explicitly before starting the server; normal questions never download files.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
import hashlib
import json
import lzma
import sqlite3
import numpy as np
from .db import ROOT
from .retrieval import tokenize


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def download_model(directory):
    manifest=json.loads((directory/'manifest.json').read_text())
    if manifest['model']!='intfloat/multilingual-e5-small':
        raise ValueError('Unexpected embedding model. Restore the supplied model manifest.')
    revision=manifest['revision']
    if len(revision)!=40 or any(c not in '0123456789abcdef' for c in revision):
        raise ValueError('Invalid pinned model revision.')
    for name in ['model.onnx','tokenizer.json']:
        info=manifest['files'][name];target=directory/name
        if target.is_file() and target.stat().st_size==info['size'] and digest(target)==info['sha256']:continue
        source=info['source']
        if source.startswith('/') or '..' in source or '?' in source or '#' in source:
            raise ValueError('Invalid model source.')
        url=f'https://huggingface.co/{manifest["model"]}/resolve/{revision}/{source}'
        print(f'Downloading {name} once ({info["size"]//1_000_000} MB). No API key is used.',flush=True)
        # Validate complete bytes before replacing any existing local model.
        with TemporaryDirectory(prefix='.model-download-',dir=directory) as stage:
            temp=Path(stage)/name;size=0;h=hashlib.sha256()
            try:
                with urlopen(url,timeout=90) as response,temp.open('wb') as out:
                    while block:=response.read(1024*1024):
                        size+=len(block)
                        if size>info['size']:raise ValueError('The model download exceeded its expected size.')
                        h.update(block);out.write(block)
            except OSError:
                raise RuntimeError('Model download failed. Check access to huggingface.co and retry setup-rag. Existing verified files are reused.') from None
            if size!=info['size'] or h.hexdigest()!=info['sha256']:
                raise ValueError('Model checksum mismatch. No unverified model was installed; retry setup-rag.')
            temp.replace(target)


def prepare(root=ROOT):
    root=Path(root);data=root/'data';bundle=data/'rag-prepared';directory=data/'rag'
    model_dir=data/'models/multilingual-e5-small'
    package=json.loads((bundle/'manifest.json').read_text())
    signature=package['signature']
    if digest(data/'corpus.json')!=package['corpus_file_sha256']:
        raise ValueError('These prepared vectors belong to the supplied books. Restore the original corpus, or rebuild embeddings for your changed collection.')
    for name in ['vectors.npy.xz','rows.json.xz']:
        if digest(bundle/name)!=package['files'][name]:raise ValueError('Prepared search data failed its checksum. Extract the full ZIP again.')
    model=json.loads((model_dir/'manifest.json').read_text())
    if any(signature[key]!=model['files'][name]['sha256'] for key,name in [('model_sha256','model.onnx'),('tokenizer_sha256','tokenizer.json')]):
        raise ValueError('The model manifest does not match the supplied vectors.')
    download_model(model_dir)
    existing=directory/'manifest.json'
    if existing.is_file():
        try:
            current=json.loads(existing.read_text())
            if all(current.get(k)==v for k,v in signature.items()) and set(current['files'])=={'vectors.npy','chunks.sqlite'} and all(digest(directory/n)==h for n,h in current['files'].items()):
                print('Local search is already ready. No embeddings were recomputed.',flush=True);return
        except (OSError,ValueError,KeyError):pass
    print('Preparing the precomputed book vectors and local text search. No Gemini calls or embedding computation.',flush=True)
    corpus=json.loads((data/'corpus.json').read_text(encoding='utf-8'))
    pages=sorted(corpus['passages'],key=lambda p:(p['book_id'],p['ordinal']))
    fingerprint=hashlib.sha256(json.dumps(pages,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if fingerprint!=signature['corpus']:raise ValueError('Prepared vectors do not match the current passage ordering.')
    by_id={p['id']:p for p in pages}
    with lzma.open(bundle/'rows.json.xz','rb') as f:raw=f.read(50_000_001)
    if len(raw)>50_000_000 or hashlib.sha256(raw).hexdigest()!=package['rows_sha256']:
        raise ValueError('Invalid prepared source offsets.')
    rows=json.loads(raw)
    if len(rows)!=signature['count']:raise ValueError('Prepared chunk count mismatch.')
    for pid,bid,start,end in rows:
        p=by_id.get(pid)
        if not p or p['book_id']!=bid or type(start) is not int or type(end) is not int or not 0<=start<end<=len(p['text']):
            raise ValueError('Invalid prepared source reference.')
    directory.mkdir(exist_ok=True)
    with TemporaryDirectory(prefix='.rag-setup-',dir=data) as stage:
        stage=Path(stage);vector=stage/'vectors.npy';size=0
        with lzma.open(bundle/'vectors.npy.xz','rb') as src,vector.open('wb') as out:
            while block:=src.read(1024*1024):
                size+=len(block)
                if size>package['vectors_size']:raise ValueError('Prepared vectors exceed their expected size.')
                out.write(block)
        if size!=package['vectors_size'] or digest(vector)!=package['vectors_sha256']:
            raise ValueError('Prepared vectors failed their checksum.')
        matrix=np.load(vector,mmap_mode='r',allow_pickle=False)
        if matrix.shape!=(signature['count'],384) or matrix.dtype!=np.float16:
            raise ValueError('Unexpected vector shape or precision.')
        del matrix  # Release the Windows mapping before replacing the file.
        db=stage/'chunks.sqlite'
        c=sqlite3.connect(db)
        try:
            with c:
                c.execute('CREATE TABLE chunks (idx INTEGER PRIMARY KEY,page_id TEXT,book_id TEXT,start INTEGER,end INTEGER)')
                c.execute("CREATE VIRTUAL TABLE chunk_search USING fts5(terms, tokenize='unicode61 remove_diacritics 0')")
                c.executemany('INSERT INTO chunks VALUES (?,?,?,?,?)',((i,*row) for i,row in enumerate(rows)))
                c.executemany('INSERT INTO chunk_search(rowid,terms) VALUES (?,?)',((i,' '.join(tokenize(by_id[pid]['text'][start:end]))) for i,(pid,bid,start,end) in enumerate(rows)))
                c.execute('CREATE INDEX chunks_book ON chunks(book_id)')
                c.execute("INSERT INTO chunk_search(chunk_search) VALUES('optimize')")
        finally:c.close()
        result={**signature,'files':{name:digest(stage/name) for name in ['vectors.npy','chunks.sqlite']}}
        (stage/'manifest.json').write_text(json.dumps(result,indent=2)+'\n')
        for name in ['vectors.npy','chunks.sqlite','manifest.json']:(stage/name).replace(directory/name)
    print(f'Local search ready: {signature["count"]:,} chunks. Start the app with npm run dev.',flush=True)
