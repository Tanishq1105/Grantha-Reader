"""Regression tests for documented SSE variants and the complete-JSON default."""
import io
import json
import pytest
from backend import providers, check_gemini, grounding
from backend.schemas import ANSWER_SCHEMA
from test_streaming_questions import events

ANSWER = {'status':'answered','claims':[{'text':'कर्म और duty।','citation_ids':['book:1']}]}

@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv('GEMINI_API_MODE','interactions')
    monkeypatch.setenv('GEMINI_SECOND_PASS','true')
    monkeypatch.setenv('AI_ENABLED','true')
    monkeypatch.setenv('GEMINI_API_KEY','secret-regression-key')
    monkeypatch.delenv('GEMINI_STREAMING',raising=False)
    monkeypatch.setattr(providers,'urlopen',lambda *a,**k:pytest.fail('Unexpected network call'))

class SSE(io.BytesIO):
    headers = {'Content-Type':'text/event-stream; charset=utf-8'}

@pytest.mark.parametrize('style',['type','header','mixed','event_type'])
def test_completion_variants_do_not_report_false_disconnect(monkeypatch,style):
    frames=[]
    for index,event in enumerate(events(ANSWER)):
        kind=event.pop('event_type')
        key='type' if style=='type' or (style=='mixed' and index%2==0) else 'event_type'
        if style!='header':event[key]=kind
        frames.append('event: '+kind+'\r\ndata: '+json.dumps(event,ensure_ascii=False)+'\r\n\r\n')
    raw=('\ufeff: heartbeat\r\n\r\n'+''.join(frames)+'event: done\r\ndata: [DONE]\r\n\r\n').encode()
    monkeypatch.setenv('GEMINI_STREAMING','true')
    monkeypatch.setattr(providers,'urlopen',lambda *a,**k:SSE(raw))
    assert providers.complete_json('source only',{},ANSWER_SCHEMA)==ANSWER

def test_multiline_and_final_frame_without_blank_line(monkeypatch):
    response={'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':json.dumps(ANSWER)}]}]}
    data=json.dumps({'interaction':response},indent=2)
    raw='event: interaction.completed\n'+ '\n'.join('data: '+line for line in data.splitlines())
    monkeypatch.setattr(providers,'urlopen',lambda *a,**k:SSE(raw.encode()))
    assert providers.complete_json('source only',{},ANSWER_SCHEMA)==ANSWER

@pytest.mark.parametrize('tail',['','event: done\ndata: [DONE]\n\n'])
def test_done_or_eof_without_completion_is_never_an_answer(monkeypatch,tail):
    raw=''.join('event: '+e['event_type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events(ANSWER)[:-1])+tail
    calls=[]
    def http(*a,**k):calls.append(1);return SSE(raw.encode())
    monkeypatch.setattr(providers,'urlopen',http)
    with pytest.raises(providers.ProviderError) as caught:providers.complete_json('s',{},ANSWER_SCHEMA)
    error=caught.value
    assert error.code=='incomplete_stream' and len(calls)==1
    assert error.diagnostic()['stream_last_event']==('done' if tail else 'step.stop')
    assert error.diagnostic()['stream_event_count']==8

@pytest.mark.parametrize('kind',['interaction.error','error'])
def test_stream_error_header_is_classified_without_leaking_message(monkeypatch,kind):
    raw=f'event: {kind}\ndata: '+json.dumps({'error':{'code':'gateway_timeout','message':'secret-regression-key'}})+'\n\n'
    monkeypatch.setattr(providers,'urlopen',lambda *a,**k:SSE(raw.encode()))
    with pytest.raises(providers.ProviderError) as caught:providers.complete_json('s',{},ANSWER_SCHEMA)
    assert caught.value.code=='provider_timeout'
    assert caught.value.provider_code=='gateway_timeout'
    assert 'secret' not in str(caught.value)+json.dumps(caught.value.diagnostic())

def test_complete_json_default_still_verifies_source_evidence(monkeypatch):
    passage={'id':'book:1','text':'Perform your duty without attachment to its fruits. '*3,'page':1,'extraction':'pdf_text','review_status':'unreviewed'}
    draft={'status':'answered','claims':[{'text':'Perform your duty.','citation_ids':['book:1']}]}
    check={'answers_question':True,'checks':[{'index':0,'supported':True,'evidence':[{'id':'book:1','quote':'Perform your duty without attachment to its fruits.'}]}]}
    responses=iter([draft,check]);calls=[]
    def http(request,timeout):
        payload=json.loads(request.data);calls.append(payload)
        assert payload['stream'] is False and request.get_header('Accept')=='application/json'
        return io.BytesIO(json.dumps({'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':json.dumps(next(responses))}]}]}).encode())
    monkeypatch.setattr(providers,'urlopen',http)
    assert grounding.explain('Explain this.','en',[passage])==draft['claims']
    assert len(calls)==2

def test_check_is_one_small_call_and_contains_no_credentials(monkeypatch):
    calls=[]
    def http(request,timeout):
        calls.append(json.loads(request.data))
        return io.BytesIO(json.dumps({'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':'{"ok": true}'}]}]}).encode())
    monkeypatch.setattr(providers,'urlopen',http)
    result=check_gemini.run_check()
    assert result['result']=='ok' and result['api_calls_attempted']==1 and result['response_mode']=='json'
    assert len(calls)==1 and 'secret' not in json.dumps(result)

def test_invalid_stream_setting_is_clear_configuration_error(monkeypatch):
    monkeypatch.setenv('GEMINI_STREAMING','not-a-boolean')
    with pytest.raises(providers.ProviderError) as caught:providers.complete_json('s',{},ANSWER_SCHEMA)
    assert caught.value.code=='configuration_error' and caught.value.attempts==0
