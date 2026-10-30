"""Prepared-vector setup; model transport is simulated, never downloaded."""
import hashlib,io,json,lzma,sqlite3
from pathlib import Path
import numpy as np
import pytest
from backend import setup_rag as setup


@pytest.fixture
def bundle(tmp_path,monkeypatch):
    data=tmp_path/'data';prepared=data/'rag-prepared';model=data/'models/multilingual-e5-small'
    prepared.mkdir(parents=True);model.mkdir(parents=True)
    pages=[{'id':'test:1','book_id':'test','ordinal':1,'text':'Synthetic fixture: Arjuna performs duty without attachment to results.'}]
    pages[0].update(source_id='fixture',page=1,section='one',refs=['1'],text_sha256=hashlib.sha256(pages[0]['text'].encode()).hexdigest())
    raw=json.dumps({'schema_version':2,'source_type':'uploaded_pdf','books':[{'id':'test','pdf_sha256':'fixture','stored_filename':'test.pdf','page_count':1}],'sources':[{'id':'fixture'}],'passages':pages}).encode();(data/'corpus.json').write_bytes(raw)
    files={}
    for name in ['model.onnx','tokenizer.json']:
        payload=('synthetic '+name).encode();(model/name).write_bytes(payload)
        files[name]={'source':name,'size':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
    (model/'manifest.json').write_text(json.dumps({'model':'intfloat/multilingual-e5-small','revision':'a'*40,'files':files}))
    signature={'version':1,'corpus':hashlib.sha256(json.dumps(pages,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),'model_sha256':files['model.onnx']['sha256'],'tokenizer_sha256':files['tokenizer.json']['sha256'],'tokens':224,'overlap':24,'count':1,'dimensions':384}
    stream=io.BytesIO();np.save(stream,np.ones((1,384),dtype=np.float16));vectors=stream.getvalue()
    rows=json.dumps([['test:1','test',0,len(pages[0]['text'])]]).encode()
    (prepared/'vectors.npy.xz').write_bytes(lzma.compress(vectors));(prepared/'rows.json.xz').write_bytes(lzma.compress(rows))
    meta={'signature':signature,'corpus_file_sha256':hashlib.sha256(raw).hexdigest(),'rows_sha256':hashlib.sha256(rows).hexdigest(),'vectors_size':len(vectors),'vectors_sha256':hashlib.sha256(vectors).hexdigest(),'files':{name:setup.digest(prepared/name) for name in ['vectors.npy.xz','rows.json.xz']}}
    (prepared/'manifest.json').write_text(json.dumps(meta))
    monkeypatch.setattr(setup,'urlopen',lambda *a,**kw:pytest.fail('Unexpected network request'))
    return tmp_path,prepared,model,meta


def test_prepare_restores_vectors_offsets_and_fts_and_reuses_them(bundle,monkeypatch):
    root,prepared,model,meta=bundle
    setup.prepare(root);directory=root/'data/rag'
    assert setup.digest(directory/'vectors.npy')==meta['vectors_sha256']
    with sqlite3.connect(directory/'chunks.sqlite') as c:
        assert c.execute('SELECT page_id FROM chunks').fetchall()==[('test:1',)]
        assert c.execute("SELECT rowid FROM chunk_search WHERE chunk_search MATCH 'duty'").fetchall()==[(0,)]
    before=(directory/'manifest.json').read_bytes()
    monkeypatch.setattr(setup.sqlite3,'connect',lambda *a,**kw:pytest.fail('Ready index should not rebuild'))
    setup.prepare(root);assert (directory/'manifest.json').read_bytes()==before


def test_changed_corpus_is_rejected_before_downloading(bundle):
    root,*_=bundle;(root/'data/corpus.json').write_text('{}')
    with pytest.raises(ValueError,match='belong to the supplied books'):setup.prepare(root)
    assert not (root/'data/rag/manifest.json').exists()


def test_tampered_compressed_data_is_rejected(bundle):
    root,prepared,*_=bundle;(prepared/'vectors.npy.xz').write_bytes(b'tampered')
    with pytest.raises(ValueError,match='checksum'):setup.prepare(root)


def test_verified_public_model_download_is_cached(bundle,monkeypatch):
    root,prepared,model,meta=bundle;original=(model/'model.onnx').read_bytes();(model/'model.onnx').unlink();calls=[]
    def fetch(url,timeout):calls.append(url);return io.BytesIO(original)
    monkeypatch.setattr(setup,'urlopen',fetch)
    setup.download_model(model);setup.download_model(model)
    assert len(calls)==1 and calls[0]=='https://huggingface.co/intfloat/multilingual-e5-small/resolve/'+('a'*40)+'/model.onnx'
    assert (model/'model.onnx').read_bytes()==original


def test_bad_model_download_preserves_existing_file(bundle,monkeypatch):
    root,prepared,model,meta=bundle;(model/'model.onnx').write_bytes(b'previous invalid file')
    monkeypatch.setattr(setup,'urlopen',lambda *a,**kw:io.BytesIO(b'incomplete'))
    with pytest.raises(ValueError,match='checksum'):setup.download_model(model)
    assert (model/'model.onnx').read_bytes()==b'previous invalid file'


def test_incorrect_expanded_vector_size_fails_before_publish(bundle):
    root,prepared,model,meta=bundle;meta['vectors_size']=1;(prepared/'manifest.json').write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='expected size'):setup.prepare(root)
    assert not (root/'data/rag/manifest.json').exists()
