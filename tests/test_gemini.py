"""API contract checks: no real key, network call, or model output is used."""
import io
import json
from urllib.error import HTTPError, URLError
import pytest
from backend import providers
from backend.schemas import ANSWER_SCHEMA

@pytest.fixture(autouse=True)
def isolate_provider(monkeypatch):
    monkeypatch.setenv('GEMINI_API_MODE','interactions')
    monkeypatch.setenv('GEMINI_SECOND_PASS','true')
    for name in ['GEMINI_STREAMING', 'GEMINI_REQUEST_BUDGET_SECONDS', 'GEMINI_MAX_RETRIES', 'GEMINI_MODEL', 'GEMINI_THINKING_LEVEL', 'GEMINI_TIMEOUT_SECONDS', 'GEMINI_MAX_OUTPUT_TOKENS', 'GEMINI_EMBEDDING_MODEL', 'EMBEDDING_DIMENSIONS']:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('GEMINI_API_KEY', 'test-key-only')
    monkeypatch.setenv('AI_ENABLED', 'true')
    monkeypatch.setenv('EMBEDDINGS_ENABLED', 'false')
    monkeypatch.setattr(providers, 'urlopen', lambda *a, **k: pytest.fail('Unexpected real network call'))


def output(value):
    return {'status': 'completed', 'steps': [{'type': 'model_output', 'content': [{'type': 'text', 'text': json.dumps(value, ensure_ascii=False)}]}]}


def test_native_request_uses_google_auth_and_stateless_schema(monkeypatch):
    seen=[]
    expected={'status':'answered','claims':[{'text':'कर्म के फल।','citation_ids':['gitaasitis:164']}]}
    def http(req, timeout):
        seen.append((req, timeout))
        return io.BytesIO(json.dumps(output(expected)).encode())
    monkeypatch.setattr(providers, 'urlopen', http)
    assert providers.complete_json('Only explain the supplied pages.', {'question':'कर्म क्या है?'}, ANSWER_SCHEMA)==expected
    req, timeout=seen[0];body=json.loads(req.data)
    assert req.full_url=='https://generativelanguage.googleapis.com/v1beta/interactions'
    assert req.get_header('X-goog-api-key')=='test-key-only'
    assert req.get_header('Authorization') is None and 'test-key-only' not in req.full_url and b'test-key-only' not in req.data
    assert body['model']=='gemini-3.8-flash' and body['store'] is False
    assert body['stream'] is False and body['background'] is False and 'tools' not in body
    assert req.get_header('Accept') == 'application/json'
    assert body['response_format']['schema']==ANSWER_SCHEMA
    assert body['generation_config']['thinking_summaries']=='none'
    assert 'कर्म' in json.loads(body['input'])['question'] and timeout==180


def test_model_override_and_empty_model_default(monkeypatch):
    monkeypatch.setenv('GEMINI_MODEL','custom-test-model');assert providers.model_name()=='custom-test-model'
    monkeypatch.setenv('GEMINI_MODEL',' ');assert providers.model_name()=='gemini-3.8-flash'
    monkeypatch.setenv('AI_ENABLED','false');assert not providers.llm_ready()
    monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('GEMINI_API_KEY',' ')
    assert not providers.llm_ready()
    with pytest.raises(providers.ProviderError,match='configure GEMINI_API_KEY'):
        providers.complete_json('s',{},ANSWER_SCHEMA)


def test_only_final_model_output_is_read(monkeypatch):
    result={'status':'completed','steps':[
        {'type':'thought','content':[{'type':'text','text':'private reasoning, not an answer'}]},
        {'type':'model_output','content':[{'type':'text','text':'draft'}]},
        {'type':'model_output','status':'done','content':[{'type':'text','text':'{"status":"insufficient_'},{'type':'text','text':'evidence","claims":[]}'}]}]}
    monkeypatch.setattr(providers,'request_json',lambda *a,**k:result)
    assert providers.complete_json('s',{},ANSWER_SCHEMA)=={'status':'insufficient_evidence','claims':[]}


@pytest.mark.parametrize('response',[
    {'status':'incomplete','steps':[]}, {'status':'failed','steps':[]},
    {'status':'requires_action','steps':[{'type':'function_call'}]},
    {'status':'completed','steps':[]}, {'status':'completed','steps':[None]},
    {'status':'completed','steps':[{'type':'model_output','content':None}]},
    {'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':'not JSON'}]}]},
    {'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':'[]'}]}]},
])
def test_incomplete_blocked_or_malformed_output_is_not_an_answer(monkeypatch,response):
    monkeypatch.setattr(providers,'request_json',lambda *a,**k:response)
    with pytest.raises(providers.ProviderError) as exc:providers.complete_json('s',{},ANSWER_SCHEMA)
    assert exc.value.code=='invalid_response'


@pytest.mark.parametrize('status,code',[(401,'authentication_error'),(403,'permission_denied'),(404,'model_unavailable'),(429,'rate_limited'),(500,'service_error')])
def test_http_errors_are_actionable_without_exposing_raw_content(monkeypatch,status,code):
    monkeypatch.setenv('GEMINI_MAX_RETRIES', '0')
    def http(*a,**k):raise HTTPError('https://generativelanguage.googleapis.com/v1beta/interactions',status,'private-key-or-prompt',{},io.BytesIO(b'private book text and API key'))
    monkeypatch.setattr(providers,'urlopen',http)
    with pytest.raises(providers.ProviderError) as exc:providers.complete_json('s',{},ANSWER_SCHEMA)
    assert exc.value.code==code
    assert 'private' not in str(exc.value) and 'test-key-only' not in str(exc.value)


def test_timeout_and_invalid_configuration_fail_closed(monkeypatch):
    def timeout(*a,**k):raise TimeoutError('secret request details')
    monkeypatch.setattr(providers,'urlopen',timeout)
    with pytest.raises(providers.ProviderError):providers.complete_json('s',{},ANSWER_SCHEMA)
    monkeypatch.setenv('GEMINI_TIMEOUT_SECONDS','invalid')
    with pytest.raises(providers.ProviderError) as exc:providers.complete_json('s',{},ANSWER_SCHEMA)
    assert exc.value.code=='configuration_error'


def test_embedding_pages_remain_distinct_and_queries_get_their_task(monkeypatch):
    monkeypatch.setenv('EMBEDDINGS_ENABLED','true');seen=[]
    def http(req,timeout):
        seen.append((req.full_url,json.loads(req.data)))
        return io.BytesIO(json.dumps({'embedding':{'values':[1.0]+[0.0]*767}}).encode())
    monkeypatch.setattr(providers,'urlopen',http)
    vectors=providers.embeddings(['Page A','Page B']);assert len(vectors)==2 and len(seen)==2
    assert all(url.endswith('/models/gemini-embedding-2:embedContent') for url,_ in seen)
    assert seen[0][1]['content']['parts'][0]['text'].endswith('Page A')
    assert seen[1][1]['content']['parts'][0]['text'].endswith('Page B')
    assert seen[0][1]['embedContentConfig']=={'outputDimensionality':768}
    providers.embeddings(['What is duty?'],task='query')
    assert seen[-1][1]['content']['parts'][0]['text'].startswith('task: search result | query: ')


@pytest.mark.parametrize('values',[[0.0]*768,[float('nan')]+[0.0]*767,[True]+[0.0]*767,[1.0]*5])
def test_invalid_embedding_vectors_rejected(monkeypatch,values):
    monkeypatch.setenv('EMBEDDINGS_ENABLED','true')
    monkeypatch.setattr(providers,'request_json',lambda *a,**k:{'embedding':{'values':values}})
    with pytest.raises(providers.ProviderError):providers.embeddings(['page'])
