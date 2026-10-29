"""The small stateless generation path: simulated provider, never live calls."""
import io,json
import pytest
from backend import providers,grounding
from backend.compact_grounding import compact_evidence
from conftest import signup
TEXT='Krishna advises Arjuna to perform his duty without attachment to the results. This is synthetic test evidence, not a quotation from an edition.'
PAGE={'id':'test:1','book_id':'test','page':1,'text':TEXT,'extraction':'pdf_text','edition':'Synthetic fixture'}
QUOTE='perform his duty without attachment to the results'
def answer(claim=None):return {'status':'answered','claims':[claim or {'text':'Perform duty without attachment.','citation_id':'test:1','evidence_quote':QUOTE}]}
def response(value,finish='STOP'):return {'candidates':[{'finishReason':finish,'content':{'parts':[{'text':json.dumps(value,ensure_ascii=False)}]}}]}
@pytest.fixture(autouse=True)
def isolate(monkeypatch):
 for k,v in {'GEMINI_API_MODE':'generate_content','GEMINI_SECOND_PASS':'false','AI_ENABLED':'true','GEMINI_API_KEY':'test-key-only','AI_REQUESTS_PER_MINUTE':'1000','GEMINI_MAX_RETRIES':'0'}.items():monkeypatch.setenv(k,v)
 monkeypatch.setattr(providers,'urlopen',lambda *a,**kw:pytest.fail('Unexpected network call'))
def test_one_stateless_request_even_with_old_streaming_setting(monkeypatch):
 seen=[];monkeypatch.setenv('GEMINI_STREAMING','true');monkeypatch.setenv('GEMINI_RESPONSE_MODE','json')
 def http(req,timeout):seen.append((req,timeout));return io.BytesIO(json.dumps(response(answer())).encode())
 monkeypatch.setattr(providers,'urlopen',http)
 claims=grounding.explain('What is duty?','hi',[PAGE],history=['old question','latest question'])
 assert claims==[{'text':'Perform duty without attachment.','citation_ids':['test:1'],'supporting_quote':QUOTE}] and len(seen)==1
 req,timeout=seen[0];body=json.loads(req.data)
 assert req.full_url.endswith('/models/gemini-3.8-flash:generateContent') and req.get_header('X-goog-api-key')=='test-key-only'
 assert req.get_header('Accept')=='application/json' and 'tools' not in body and 'stream' not in body
 assert body['generationConfig']['thinkingConfig']=={'thinkingLevel':'low'} and body['generationConfig']['responseMimeType']=='application/json'
 payload=json.loads(body['contents'][0]['parts'][0]['text'])
 assert payload['previous_question']=='latest question' and payload['language']=='hi'
 assert payload['excerpts'][0]['text']==TEXT and len(req.data)<10000 and timeout<=180
@pytest.mark.parametrize('claim',[
 {'text':'Unknown source','citation_id':'other:9','evidence_quote':QUOTE},
 {'text':'Invented evidence','citation_id':'test:1','evidence_quote':'not a quotation found anywhere in the source'},
 {'text':'Tiny quote','citation_id':'test:1','evidence_quote':'duty'},
 {'text':'','citation_id':'test:1','evidence_quote':QUOTE},
 {'text':'Invalid ID type','citation_id':['test:1'],'evidence_quote':QUOTE}])
def test_invalid_evidence_rejects_entire_answer(monkeypatch,claim):
 monkeypatch.setattr(providers,'request_json',lambda *a,**kw:response(answer(claim)))
 assert grounding.explain('Explain duty','en',[PAGE]) is None
@pytest.mark.parametrize('finish',['MAX_TOKENS','SAFETY','RECITATION',None])
def test_only_completed_answers_are_shown(monkeypatch,finish):
 monkeypatch.setattr(providers,'request_json',lambda *a,**kw:response(answer(),finish))
 with pytest.raises(providers.ProviderError):grounding.explain('Explain duty','en',[PAGE])
def test_thought_parts_are_not_in_answer(monkeypatch):
 value=response(answer());value['candidates'][0]['content']['parts'].insert(0,{'thought':True,'text':'internal reasoning'})
 monkeypatch.setattr(providers,'request_json',lambda *a,**kw:value)
 assert grounding.explain('Explain duty','en',[PAGE])[0]['text']=='Perform duty without attachment.'
def test_context_remains_small_despite_previous_env_settings(monkeypatch):
 monkeypatch.setenv('GEMINI_CONTEXT_CHARACTERS','16000')
 pages=[{**PAGE,'id':f'test:{n}','page':n,'text':TEXT*40} for n in range(1,12)];compact=compact_evidence(pages)
 assert len(compact)<=3 and sum(len(p['text']) for p in compact)<=3600
 assert all(p['text'] in pages[p['page']-1]['text'] for p in compact)
def test_bad_ocr_does_not_reach_gemini(monkeypatch):
 monkeypatch.setattr(providers,'complete_json',lambda *a,**kw:pytest.fail('Bad OCR must be excluded'))
 assert grounding.explain('Explain','hi',[{**PAGE,'extraction':'ocr','ocr_confidence':30}]) is None
 assert grounding.explain('Explain','sa',[{**PAGE,'unresolved_glyphs':3}]) is None
def test_success_cache_is_private_and_avoids_duplicate_call(client,app,monkeypatch):
 calls=[]
 def fake(system,payload,schema,**kwargs):
  calls.append(payload);p=payload['excerpts'][0]
  return {'status':'answered','claims':[{'text':'Test interpretation.','citation_id':p['id'],'evidence_quote':p['text'][:80]}]}
 monkeypatch.setattr(providers,'complete_json',fake)
 body={'question':'Explain this page for the caching regression.','scope':'page','page_id':'gitaasitis:164','books':['gitaasitis'],'mode':'explain'}
 assert client.post('/api/ask',json=body).json['generated']
 assert client.post('/api/ask',json=body).json['cached'] and len(calls)==1
 other,_=signup(app);assert other.post('/api/ask',json=body).json['generated'] and len(calls)==2
def test_typed_current_page_uses_page_context(client,monkeypatch):
 seen=[];monkeypatch.setattr(providers,'complete_json',lambda system,payload,*a,**kw:seen.append(payload) or {'status':'insufficient_evidence','claims':[]})
 r=client.post('/api/ask',json={'question':'Explain this page.','scope':'book','page_id':'gitaasitis:164','books':['gitaasitis'],'mode':'explain'})
 assert r.json['retrieval']=='page_context' and seen[0]['excerpts'][0]['id']=='gitaasitis:164'
 assert all(p['id'] in ['gitaasitis:163','gitaasitis:164','gitaasitis:165'] for p in seen[0]['excerpts'])


def test_local_inference_failure_preserves_lexical_search(client,app,monkeypatch):
 rag=app.extensions['rag'];monkeypatch.setattr(rag,'ready',True);monkeypatch.setattr(rag,'reason',None)
 def unavailable(*a,**kw):raise RuntimeError('Synthetic local failure')
 monkeypatch.setattr(rag,'search',unavailable)
 result=client.get('/api/search?q=duty&book=gitaasitis').json
 assert result['method']=='lexical_fallback' and result['results']
 assert rag.ready is False and rag.reason=='inference_unavailable'


def test_selected_text_anchors_default_book_question(client,app,monkeypatch):
 seen=[];page=app.extensions['store'].by_id['gitaasitis:164'];selected=page['text'][1200:1280]
 monkeypatch.setattr(providers,'complete_json',lambda system,payload,*a,**kw:seen.append(payload) or {'status':'insufficient_evidence','claims':[]})
 r=client.post('/api/ask',json={'question':'Explain these words.','scope':'book','page_id':page['id'],'selected_text':selected,'books':['gitaasitis'],'mode':'explain'})
 assert r.json['retrieval']=='page_context' and seen[0]['excerpts'][0]['id']==page['id']
 assert selected in seen[0]['excerpts'][0]['text']


@pytest.mark.parametrize('value',[{'candidates':[None]}, {'candidates':'invalid'}, []])
def test_malformed_provider_envelopes_fail_closed(monkeypatch,value):
 monkeypatch.setattr(providers,'request_json',lambda *a,**kw:value)
 with pytest.raises(providers.ProviderError) as failure:grounding.explain('Explain duty','en',[PAGE])
 assert failure.value.code=='invalid_response'
