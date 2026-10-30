"""Regression checks for the optional 512 MiB deployment profile."""
import hashlib
import json
import pytest
from sqlalchemy import select
from backend.db import Store, engine_for, initialize, passages
from backend.book_storage import PageSequence, PageMap
from backend.low_memory_rag import LexicalIndex


def corpus(path):
    pages=[]
    for i in range(1,4):
        text='कर्म is action. ' * i
        pages.append({'id':f'b:{i}','book_id':'b','source_id':'s','page':i,'ordinal':i-1,
                      'section':'one' if i<3 else 'two','text':text,
                      'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'refs':[str(i)]})
    data={'schema_version':2,'source_type':'uploaded_pdf','books':[{'id':'b','pdf_sha256':'fixture','stored_filename':'b.pdf','page_count':3}],
          'sources':[{'id':'s'}],'passages':pages}
    path.write_text(json.dumps(data,ensure_ascii=False));return data


def test_lazy_access_and_fingerprint(tmp_path):
    path=tmp_path/'corpus.json';data=corpus(path);e=engine_for('sqlite:///'+str(tmp_path/'books.db'))
    initialize(e,path);s=Store(e)
    assert isinstance(s.passages,PageSequence) and isinstance(s.by_id,PageMap)
    assert s.fingerprint==hashlib.sha256(json.dumps(data['passages'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert s.passages[-1]['id']=='b:3'
    assert [p['id'] for p in s.by_book['b'][1:3]]==['b:2','b:3']
    assert len(PageSequence(e,'b','one'))==2
    assert s.by_id.get('absent') is None and 'b:2' in s.by_id
    assert s.by_ref['b:1']==s.by_id['b:1']
    with pytest.raises(IndexError):s.passages[100]


def test_cache_reuse_and_changed_text_rollback(tmp_path,monkeypatch):
    from backend import book_storage
    path=tmp_path/'corpus.json';data=corpus(path);e=engine_for('sqlite:///'+str(tmp_path/'books.db'))
    initialize(e,path)
    original=book_storage.items
    monkeypatch.setattr(book_storage,'items',lambda *a:pytest.fail('Unchanged corpus must not be parsed again'))
    initialize(e,path)
    monkeypatch.setattr(book_storage,'items',original)
    data['passages'][0]['text']='tampered'
    path.write_text(json.dumps(data,ensure_ascii=False))
    with pytest.raises(ValueError,match='integrity'):initialize(e,path,replace=True)
    with e.connect() as c:assert c.execute(select(passages.c.id)).all()==[('b:1',),('b:2',),('b:3',)]


def test_low_profile_preserves_retrieval_and_never_encodes(app,monkeypatch):
    from backend import local_rag
    monkeypatch.setattr(local_rag,'Encoder',lambda *a,**k:pytest.fail('No E5 model in low-memory mode'))
    rag=LexicalIndex(app.extensions['store'])
    assert rag.ready and rag.status()['semantic_enabled'] is False
    for q,books in [('duty without attachment',['gitaasitis']),('राम वनवास',['ramayana']),('आत्मा',['upanishads1'])]:
        rows,method=rag.search(q,books)
        assert rows and method=='local_bm25'
        for r in rows:
            p=r['passage']
            assert p['book_id'] in books
            assert p['reference_excerpt']==p['text'][p['excerpt_start']:p['excerpt_end']]
    assert rag.search('current Bitcoin price')[0]==[]
