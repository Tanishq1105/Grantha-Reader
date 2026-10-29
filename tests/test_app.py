import copy
import hashlib
import json
from pathlib import Path
import pytest
from backend.app import create_app
from backend.db import ROOT,read_corpus
from backend import grounding,providers
from backend.pdf_extract import font_text,native_text
import pymupdf

def test_book_collection_and_every_page_are_preserved(app):
 store=app.extensions['store'];assert [b['id'] for b in store.books][:3]==['gitascan','gitaasitis','ramayana'];assert len(store.books)==17
 assert [b['page_count'] for b in store.books][:3]==[428,1029,2303];assert len(store.passages)==23348
 assert all(p['source_url'].startswith('/api/books/') for p in store.passages)
 for b in store.books:
  assert hashlib.sha256((ROOT/'data/pdfs'/b['stored_filename']).read_bytes()).hexdigest()==b['pdf_sha256']
  assert len(store.by_book[b['id']])==b['page_count']

def test_scan_has_real_hindi_ocr_and_visible_review_status(app):
 p=app.extensions['store'].by_id['gitascan:21'];assert p['extraction']=='ocr' and p['review_status']=='ocr_unreviewed'
 assert len(p['text'])>500 and 'अर्जुन' in p['text'];assert p['ocr_confidence']<100
 assert app.extensions['store'].books[0]['indexed_pages']==421
 assert len(app.extensions['store'].books[0]['sections'])==18

@pytest.mark.parametrize('pid',['gitascan:1','gitascan:428','gitaasitis:42','gitaasitis:1029','ramayana:59','ramayana:2303'])
def test_book_pages_open_with_local_source_links(client,pid):
 r=client.get('/api/passages/'+pid);assert r.status_code==200;assert r.json['passage']['id']==pid
 assert r.json['passage']['page_url'].startswith('/api/books/')

def test_first_and_last_navigation_stay_inside_edition(client):
 assert client.get('/api/passages/gitascan:1').json['previous'] is None
 assert client.get('/api/passages/gitascan:428').json['next'] is None
 assert client.get('/api/passages/gitascan:429').status_code==404

@pytest.mark.parametrize('query',['Gita 2.47','गीता २.४७','2:47'])
def test_exact_verse_uses_corrected_printed_heading_and_full_continuation(client,query):
 result=client.get('/api/search',query_string={'q':query,'book':'gitaasitis'}).json
 assert result['method']=='exact';rows=[x['passage'] for x in result['results']]
 assert [p['page'] for p in rows]==[163,164,165]
 text='\n'.join(p['reference_excerpt'] for p in rows)
 assert 'You have a right to perform your prescribed duty' in text
 assert 'TEXT\n48' not in text and 'TEXT 48' not in text
 assert 'All purposes served by a small well' not in text


def test_grouped_verses_resolve_to_same_printed_passage(client):
 a=client.get('/api/search',query_string={'q':'5.27','book':'gitaasitis'}).json
 b=client.get('/api/search',query_string={'q':'5.28','book':'gitaasitis'}).json
 assert [x['passage']['id'] for x in a['results']]==[x['passage']['id'] for x in b['results']]
 assert a['results'][0]['passage']['reference_excerpt']==b['results'][0]['passage']['reference_excerpt']

@pytest.mark.parametrize('book,ref,last',[('gitaasitis','18.78',1028),('ramayana','4.67',1168)])
def test_reference_spans_exclude_publisher_and_volume_front_matter(client,book,ref,last):
 result=client.get('/api/search',query_string={'q':ref,'book':book}).json
 assert result['method']=='exact'
 assert result['results'][-1]['passage']['page']==last
 assert not any('e-vedas.com' in x['passage']['reference_excerpt'] for x in result['results'])

def test_end_of_chapter_excludes_following_chapter_heading(client):
 rows=client.get('/api/search',query_string={'q':'1.46','book':'gitaasitis'}).json['results']
 assert 'CHAPTER 2' not in '\n'.join(x['passage']['reference_excerpt'] for x in rows)


def test_source_printing_errors_are_annotated_not_rewritten(client):
 p=client.get('/api/passages/ramayana:4.63').json['passage'];assert p['page']==1154
 assert 'Canto XLIII' in p['text'] and 'Canto 63' in p['heading_note']
 p=client.get('/api/passages/ramayana:7.46').json['passage'];assert p['page']==2168
 assert 'Canto LVI' in p['text'] and 'Canto 46' in p['heading_note']


def test_native_extraction_keeps_heading_before_body_and_decodes_fonts():
 with pymupdf.open(ROOT/'data/pdfs/ramayana.pdf') as doc:
  r=native_text(doc[1153]);assert r['text'].index('Canto XLIII')<r['text'].index('Having extolled me')
 assert font_text('Kåñëa','ScaGoudy')=='Kṛṣṇa';assert font_text('Råmåyaƒa','Nalandahel')=='Rāmāyaṇa'
 assert r['legacy_sanskrit_omitted'] is True and '\uf8ff' not in r['text']

@pytest.mark.parametrize('query',['Why was Rama sent into exile?','राम वनवास','सीता','Hanuman'])
def test_book_search_handles_english_and_hindi_terms(client,query):
 data=client.get('/api/search',query_string={'q':query,'book':'ramayana'}).json
 assert data['results'];assert {x['passage']['book_id'] for x in data['results']}=={'ramayana'}

@pytest.mark.parametrize('query',['Who invented the smartphone?','What is the current Bitcoin price?','Gita 99.999'])
def test_unsupported_book_questions_do_not_create_answers(client,query):
 r=client.post('/api/ask',json={'question':query,'books':['gitaasitis'],'scope':'book','mode':'strict'}).json
 assert r['status']=='insufficient_evidence' and not r['generated'] and not r['claims']


def test_no_cross_edition_substitution_when_scan_has_no_verse_anchor(client):
 r=client.get('/api/search',query_string={'q':'2.47','book':'gitascan'}).json
 assert r['method']=='exact' and r['results']==[]
 r=client.get('/api/search',query_string={'q':'page 21','book':'gitascan'}).json
 assert [x['passage']['id'] for x in r['results']]==['gitascan:21']


def test_page_questions_use_current_and_neighbor_pages(client,monkeypatch):
 monkeypatch.setenv('AI_ENABLED','false')
 r=client.post('/api/ask',json={'question':'Explain this page','mode':'explain','scope':'page','page_id':'gitaasitis:164','books':['gitaasitis']}).json
 assert r['status']=='ai_not_configured' and not r['generated']
 assert [p['page'] for p in r['evidence']]==[164,163,165]
 assert {p['book_id'] for p in r['evidence']}=={'gitaasitis'}


def test_selection_must_belong_to_the_current_page(client,app):
 base={'question':'Explain this selection','scope':'page','page_id':'gitaasitis:164','books':['gitaasitis']}
 assert client.post('/api/ask',json={**base,'selected_text':'an invented quotation not in the book'}).status_code==400
 text=app.extensions['store'].by_id['gitaasitis:164']['text'][50:180]
 assert client.post('/api/ask',json={**base,'selected_text':text}).status_code==200
 assert client.post('/api/ask',json={**base,'books':['ramayana']}).status_code==400

@pytest.mark.parametrize('patch',[{'language':[]},{'mode':{}},{'scope':[]},{'books':[{}]},{'history':['x']*5},{'page_id':[]},{'selected_text':[]},{'question':'x'}])
def test_invalid_inputs_rejected(client,patch):
 assert client.post('/api/ask',json={'question':'Rama exile',**patch}).status_code==400


def test_invalid_or_unsupported_model_claims_are_rejected(app,monkeypatch):
 p=app.extensions['store'].by_id['gitaasitis:164']
 monkeypatch.setattr(providers,'complete_json',lambda *args,**kwargs:{'status':'answered','claims':[{'text':'Invented claim','citation_ids':['unknown:1']}]})
 assert grounding.explain('What is said?','en',[p]) is None
 responses=iter([{'status':'answered','claims':[{'text':'Invented claim','citation_ids':[p['id']]}]},{'answers_question':True,'checks':[{'index':0,'supported':True,'evidence':[{'id':p['id'],'quote':'This sentence is not in the source.'}]}]}])
 monkeypatch.setattr(providers,'complete_json',lambda *args,**kwargs:next(responses))
 assert grounding.explain('What is said?','en',[p]) is None


def test_checked_ai_answer_is_labelled_and_cites_pdf_page(client,app,monkeypatch):
 monkeypatch.setenv('GEMINI_API_MODE','interactions')
 monkeypatch.setenv('GEMINI_SECOND_PASS','true')
 monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('GEMINI_MODEL','test-only');monkeypatch.setenv('GEMINI_API_KEY','test-only')
 responses=iter([{'status':'answered','claims':[{'text':'The passage distinguishes duty from entitlement to its fruits.','citation_ids':['gitaasitis:164']}]},{'answers_question':True,'checks':[{'index':0,'supported':True,'evidence':[{'id':'gitaasitis:164','quote':'You have a right to perform your prescribed duty'}]}]}])
 monkeypatch.setattr(providers,'complete_json',lambda *args,**kwargs:next(responses))
 r=client.post('/api/ask',json={'question':'Gita 2.47','books':['gitaasitis'],'scope':'book','mode':'explain'}).json
 assert r['generated'] and r['status']=='answered' and 'AI interpretation' in r['message']
 assert r['claims'][0]['citation_ids']==['gitaasitis:164']


def test_low_confidence_ocr_does_not_reach_model(app,monkeypatch):
 p={**app.extensions['store'].by_id['gitascan:21'],'ocr_confidence':30}
 monkeypatch.setattr(providers,'complete_json',lambda *args,**kwargs:pytest.fail('Should not call model for low-confidence OCR'))
 assert grounding.explain('Explain','hi',[p]) is None


def test_source_pdf_range_and_page_render_are_served(client):
 r=client.get('/api/books/ramayana/pdf',headers={'Range':'bytes=0-4'});assert r.status_code==206 and r.data==b'%PDF-'
 r=client.get('/api/books/ramayana/pages/59/image?width=800');assert r.status_code==200 and r.data.startswith(b'\x89PNG')
 assert client.get('/api/books/ramayana/pages/2304/image').status_code==400
 assert client.get('/api/books/ramayana/pages/59/image?width=999999').status_code==400
 assert client.get('/.env').status_code==404


def test_practice_answer_is_an_actual_source_excerpt(client,app):
 r=client.get('/api/practice?book=ramayana&seed=fixed').json
 assert r['status']=='ready' and len(r['choices'])==4
 assert r['excerpt']==app.extensions['store'].by_id[r['answer_id']]['text'][:450]
 assert r['answer_id'] in [x['id'] for x in r['choices']]


def test_integrity_checks_reject_changed_text(tmp_path):
 c=read_corpus();c['passages'][100]['text']+='fabricated';f=tmp_path/'bad.json';f.write_text(json.dumps(c),encoding='utf-8')
 with pytest.raises(ValueError,match='Source integrity'):read_corpus(f)


def test_gemini_native_pipeline_checks_claims_before_showing_answer(client,monkeypatch):
 monkeypatch.setenv('GEMINI_API_MODE','interactions')
 monkeypatch.setenv('GEMINI_SECOND_PASS','true')
 import io
 monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('GEMINI_API_KEY','test-key-only')
 bodies=[]
 draft={'status':'answered','claims':[{'text':'The passage distinguishes duty from entitlement to its fruits.','citation_ids':['gitaasitis:164']}]}
 check={'answers_question':True,'checks':[{'index':0,'supported':True,'evidence':[{'id':'gitaasitis:164','quote':'You have a right to perform your prescribed duty'}]}]}
 replies=iter([draft,check])
 def http(req,timeout):
  bodies.append(json.loads(req.data))
  return io.BytesIO(json.dumps({'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':json.dumps(next(replies))}]}]}).encode())
 monkeypatch.setattr(providers,'urlopen',http)
 r=client.post('/api/ask',json={'question':'Gita 2.47','books':['gitaasitis'],'scope':'book','mode':'explain'}).json
 assert r['generated'] and r['claims'][0]['citation_ids']==['gitaasitis:164']
 assert len(bodies)==2
 assert bodies[0]['response_format']['schema']['required']==['status','claims']
 assert bodies[1]['response_format']['schema']['required']==['answers_question','checks']
 assert all(body['store'] is False and 'tools' not in body for body in bodies)


def test_gemini_failure_keeps_the_book_evidence(client,monkeypatch):
 monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('GEMINI_API_KEY','test-key-only')
 def unavailable(*a,**k):raise providers.ProviderError('Gemini quota or rate limit reached.','rate_limited')
 monkeypatch.setattr(providers,'complete_json',unavailable)
 r=client.post('/api/ask',json={'question':'Explain this page','scope':'page','page_id':'gitaasitis:164','mode':'explain'})
 assert r.status_code==429 and r.json['provider_error']=='rate_limited'
 assert not r.json['generated'] and not r.json['claims']
 assert r.json['evidence'][0]['id']=='gitaasitis:164'


def test_health_exposes_model_but_never_the_key(client,monkeypatch):
 monkeypatch.setenv('GEMINI_API_KEY','secret-health-test')
 r=client.get('/api/health')
 assert r.json['ai_provider']=='gemini' and r.json['ai_model']
 assert 'secret-health-test' not in r.get_data(as_text=True)
