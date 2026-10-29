"""Real local multilingual embeddings over clearly synthetic test documents."""
from types import SimpleNamespace
import pytest
from backend import local_rag
@pytest.fixture(scope='module')
def tiny_index(tmp_path_factory):
 texts=['Krishna tells Arjuna to perform his duty without attachment to the fruits of action. Work should be done without craving a reward.','Rama was sent into exile in the forest. Kaikeyi asked Dasharatha to honour the two boons he had promised her, and Rama left for fourteen years.','The Upanishad teaches about the self, or atman, and Brahman. Knowledge of the self is associated with liberation from ignorance.']
 pages=[{'id':f'fixture{n}:1','book_id':f'fixture{n}','page':1,'text':text,'extraction':'pdf_text'} for n,text in enumerate(texts)]
 store=SimpleNamespace(passages=pages,by_id={p['id']:p for p in pages},fingerprint='synthetic-fixture-v1')
 directory=tmp_path_factory.mktemp('local-rag');local_rag.build(store,directory)
 return store,directory,local_rag.RagIndex(store,directory)
@pytest.mark.parametrize('query,expected',[('Why was Rama sent into exile?','fixture1'),('राम को वनवास क्यों मिला?','fixture1'),('रामः वनं किमर्थं गतः?','fixture1'),('What is the self?','fixture2'),('What is duty without attachment?','fixture0'),('अपने काम में परिणामों की चिन्ता कैसे छोड़ें?','fixture0')])
def test_real_multilingual_retrieval(tiny_index,query,expected):
 _,_,index=tiny_index;assert index.ready;rows,method=index.search(query,limit=1)
 assert method=='local_hybrid' and rows[0]['passage']['book_id']==expected
 p=rows[0]['passage'];assert p['reference_excerpt']==p['text'][p['excerpt_start']:p['excerpt_end']]
 assert index.status()['embedding_api_calls']==0
def test_filters_and_unrelated_questions(tiny_index):
 _,_,index=tiny_index;rows,_=index.search('duty without attachment',book_ids=['fixture0'])
 assert rows and all(r['passage']['book_id']=='fixture0' for r in rows)
 assert index.search('What is the current Bitcoin price?')[0]==[] and index.search('Who invented the smartphone?')[0]==[]
def test_stale_corpus_is_rejected(tiny_index):
 store,directory,_=tiny_index;changed=SimpleNamespace(**{**vars(store),'fingerprint':'changed'})
 index=local_rag.RagIndex(changed,directory);assert not index.ready and index.reason=='index_outdated'
def test_unicode_chunk_offsets_and_token_budget():
 from tokenizers import Tokenizer
 tok=Tokenizer.from_file(str(local_rag.MODEL_DIR/'tokenizer.json'))
 text='कर्मण्येवाधिकारस्ते मा फलेषु कदाचन। This is a chunk-boundary test.\n'*70
 chunks=list(local_rag.chunks_for({'id':'unicode:1','book_id':'unicode','text':text,'extraction':'pdf_text'},tok));assert len(chunks)>1
 assert all(len(tok.encode('passage: '+text[c['start']:c['end']]).ids)<=256 for c in chunks)
 assert all(a['end']>b['start'] for a,b in zip(chunks,chunks[1:]))


@pytest.mark.parametrize('question,expected',[('What does the Gita say about duty?',['gitaasitis']),('Compare the Gita and Upanishads',['gitaasitis','upanishads1']),('What does the Rigveda say?',['rigveda1']),('What is duty?',None)])
def test_work_names_narrow_collection_scope(question,expected):
 from backend.retrieval import infer_books
 books=[{'id':'gitaasitis','category':'gita'},{'id':'upanishads1','category':'upanishads'},{'id':'rigveda1','category':'vedas'},{'id':'samaveda','category':'vedas'}]
 assert infer_books(question,books)==expected
