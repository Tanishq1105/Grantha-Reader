"""Current Gemini transport: simulated provider, no live credentials."""
import io,json,socket
from urllib.error import HTTPError
import pytest
from backend import providers,grounding,check_gemini
from test_compact_rag import PAGE,QUOTE,answer
class SSE(io.BytesIO):headers={'Content-Type':'text/event-stream; charset=utf-8'}
def stream(value,finish='STOP',done=False,thought=False):
    raw=json.dumps(value,ensure_ascii=False);events=[]
    if thought:events.append({'candidates':[{'content':{'parts':[{'thought':True,'text':'Do not display private thoughts'}]}}]})
    for offset in range(0,len(raw),13):events.append({'candidates':[{'index':0,'content':{'parts':[{'text':raw[offset:offset+13]}]}}]})
    if finish:events.append({'candidates':[{'index':0,'finishReason':finish}]})
    data=': keepalive\n\n'+''.join('data: '+json.dumps(e,ensure_ascii=False)+'\r\n\r\n' for e in events)
    return SSE((data+('data: [DONE]\n\n' if done else '')).encode())
@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    for k,v in {'AI_ENABLED':'true','GEMINI_API_KEY':'private-secret-key','GEMINI_API_MODE':'generate_content','GEMINI_SECOND_PASS':'false','GEMINI_RESPONSE_MODE':'stream','GEMINI_THINKING_LEVEL':'low','GEMINI_MAX_RETRIES':'1','AI_REQUESTS_PER_MINUTE':'1000'}.items():monkeypatch.setenv(k,v)
    monkeypatch.delenv('GEMINI_RESPONSE_TIMEOUT_SECONDS',raising=False)
    monkeypatch.setattr(providers,'urlopen',lambda *a,**kw:pytest.fail('Unexpected live network request'))
def test_segmented_unicode_response_requires_explicit_finish(monkeypatch):
    calls=[];progress=[];result=answer();result['claims'][0]['text']='कर्तव्य का पालन करें।'
    def http(req,timeout):calls.append(req);assert timeout<=180;return stream(result,thought=True)
    monkeypatch.setattr(providers,'urlopen',http)
    checked=grounding.explain('कर्तव्य क्या है?','hi',[PAGE],progress=lambda **f:progress.append(f))
    assert checked[0]['text']=='कर्तव्य का पालन करें।' and checked[0]['supporting_quote']==QUOTE
    assert len(calls)==1 and calls[0].full_url.endswith('/models/gemini-3.8-flash:streamGenerateContent?alt=sse')
    assert calls[0].get_header('Accept')=='text/event-stream' and any(p['stage']=='receiving' for p in progress)
@pytest.mark.parametrize('done',[False,True])
def test_closed_stream_without_finish_is_not_an_answer(monkeypatch,done):
    monkeypatch.setattr(providers,'urlopen',lambda *a,**kw:stream(answer(),finish=None,done=done))
    with pytest.raises(providers.ProviderError) as e:grounding.explain('Explain duty','en',[PAGE])
    assert e.value.code=='incomplete_stream' and e.value.attempts==1 and e.value.diagnostic()['stream_event_count']>0
@pytest.mark.parametrize('finish',['MAX_TOKENS','SAFETY','RECITATION','CONTINUATION'])
def test_non_stop_finish_cannot_publish_claims(monkeypatch,finish):
    monkeypatch.setattr(providers,'urlopen',lambda *a,**kw:stream(answer(),finish))
    with pytest.raises(providers.ProviderError):grounding.explain('Explain duty','en',[PAGE])
def test_streamed_invented_quote_is_rejected(monkeypatch):
    bad=answer();bad['claims'][0]['evidence_quote']='This invented quote is absent from the source.'
    monkeypatch.setattr(providers,'urlopen',lambda *a,**kw:stream(bad))
    assert grounding.explain('Explain duty','en',[PAGE]) is None
def test_reader_does_not_repost_a_503_even_with_old_retry_setting(monkeypatch):
    calls=[]
    def http(req,timeout):
        calls.append(req);raise HTTPError(req.full_url,503,'private text',{'Retry-After':'30'},io.BytesIO(b'{"error":{"status":"UNAVAILABLE","message":"private-secret-key"}}'))
    monkeypatch.setattr(providers,'urlopen',http)
    with pytest.raises(providers.ProviderError) as e:grounding.explain('Private question','en',[PAGE])
    d=e.value.diagnostic();assert len(calls)==1 and d['api_calls_attempted']==1 and d['request_attempts'][0]['http_status']==503
    assert d['context_excerpts']==1 and d['context_characters']==len(PAGE['text']) and 'private' not in json.dumps(d).lower()
@pytest.mark.parametrize('phase',['headers','body'])
def test_timeout_phase_and_no_automatic_retry(monkeypatch,phase):
    calls=[]
    class Stalled(SSE):
        def readline(self,*args):raise socket.timeout('private prompt and key')
    def http(req,timeout):
        calls.append(req)
        if phase=='headers':raise socket.timeout('private prompt and key')
        return Stalled(b'')
    monkeypatch.setattr(providers,'urlopen',http)
    with pytest.raises(providers.ProviderError) as e:grounding.explain('Explain duty','en',[PAGE])
    d=e.value.diagnostic();assert len(calls)==1 and e.value.code=='network_timeout'
    assert d['request_attempts'][0]['phase']==('reading_response' if phase=='body' else 'connecting_or_waiting_for_headers')
    assert d['response_mode']=='generate_content_stream' and d['response_timeout_seconds']==180 and 'private' not in json.dumps(d)
def test_malformed_stream_is_rejected(monkeypatch):
    monkeypatch.setattr(providers,'urlopen',lambda *a,**kw:SSE(b'data: {bad JSON}\n\n'))
    with pytest.raises(providers.ProviderError) as e:grounding.explain('Explain duty','en',[PAGE])
    assert e.value.code=='invalid_response'
def test_connection_check_has_one_small_request_without_books(monkeypatch):
    calls=[];monkeypatch.setattr(providers,'urlopen',lambda req,timeout:calls.append(req) or stream({'ok':True}))
    result=check_gemini.run_check();assert result['result']=='ok' and len(calls)==1 and result['api_calls_attempted']==1
    assert len(calls[0].data)<1500 and 'excerpts' not in calls[0].data.decode() and 'private-secret-key' not in json.dumps(result)
def test_diagnostic_route_requires_account_and_limits_repeats(client,app,monkeypatch):
    seen=[];monkeypatch.setattr(check_gemini,'run_check',lambda:seen.append(True) or {'result':'ok','api_calls_attempted':1})
    assert app.test_client().post('/api/ai/check',json={}).status_code==401
    assert client.post('/api/ai/check',json={}).json['result']=='ok'
    assert client.post('/api/ai/check',json={}).status_code==429 and len(seen)==1
def test_high_resolution_zoom_page(client):
    from PIL import Image
    r=client.get('/api/books/gitaasitis/pages/164/image?width=3600');assert r.status_code==200 and r.mimetype=='image/png'
    with Image.open(io.BytesIO(r.data)) as image:assert image.width==3600
    assert client.get('/api/books/gitaasitis/pages/164/image?width=10000').status_code==400
def test_noisy_ocr_does_not_displace_clear_excerpts():
    from backend.compact_grounding import compact_evidence
    noisy={**PAGE,'id':'scan:1','extraction':'ocr','ocr_confidence':95,'text':('/_=~ $ < > @ '*80)+PAGE['text']}
    clean=[{**PAGE,'id':f'book:{n}'} for n in range(1,4)]
    assert [p['id'] for p in compact_evidence([noisy,*clean])]==[p['id'] for p in clean]
    assert compact_evidence([noisy])==[]
