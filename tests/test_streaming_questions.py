import io
import json
import threading
import time
import pytest
from backend import providers, grounding
from backend.schemas import ANSWER_SCHEMA
from backend.question_jobs import QuestionJobs, QueueBusy
from conftest import signup

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv('GEMINI_API_MODE','interactions')
    monkeypatch.setenv('GEMINI_SECOND_PASS','true')
    monkeypatch.setenv('GEMINI_STREAMING','true')
    monkeypatch.setenv('AI_ENABLED','true');monkeypatch.setenv('GEMINI_API_KEY','private-stream-test-key')
    monkeypatch.setenv('AI_REQUESTS_PER_MINUTE','1000')
    for name in ('GEMINI_TIMEOUT_SECONDS','GEMINI_REQUEST_BUDGET_SECONDS','GEMINI_MAX_OUTPUT_TOKENS'):
        monkeypatch.delenv(name,raising=False)
    monkeypatch.setattr(providers,'urlopen',lambda *a,**k:pytest.fail('Unexpected live network call'))

class Stream(io.BytesIO):
    headers={'Content-Type':'text/event-stream; charset=utf-8'}
    def __init__(self,events):
        super().__init__(''.join('event: update\ndata: '+json.dumps(e,ensure_ascii=False)+'\n\n' for e in events).encode())

def events(answer):
    text=json.dumps(answer,ensure_ascii=False)
    return [
        {'event_type':'interaction.created','interaction':{'status':'in_progress'}},
        {'event_type':'step.start','index':0,'step':{'type':'thought'}},
        {'event_type':'step.delta','index':0,'delta':{'type':'text','text':'private thoughts must not become output'}},
        {'event_type':'step.stop','index':0},
        {'event_type':'step.start','index':1,'step':{'type':'model_output'}},
        {'event_type':'step.delta','index':1,'delta':{'type':'text','text':text[:len(text)//2]}},
        {'event_type':'step.delta','index':1,'delta':{'type':'text','text':text[len(text)//2:]}},
        {'event_type':'step.stop','index':1},
        {'event_type':'interaction.completed','interaction':{'status':'completed'}},
    ]

def test_stream_progresses_past_old_wait_and_ignores_thoughts(monkeypatch):
    clock=[0.0];seen=[];reports=[];answer={'status':'answered','claims':[{'text':'कर्म का विचार।','citation_ids':['book:1']}]}
    class SlowStream(Stream):
        def readline(self,*args):
            line=super().readline(*args)
            if line==b'\n':clock[0]+=15
            return line
    monkeypatch.setattr(providers.time,'monotonic',lambda:clock[0])
    def http(req,timeout):seen.append((json.loads(req.data),req.get_header('Accept'),timeout));return SlowStream(events(answer))
    monkeypatch.setattr(providers,'urlopen',http);budget=providers.RequestBudget(progress=lambda **fields:reports.append(fields))
    assert providers.complete_json('source only',{},ANSWER_SCHEMA,budget=budget)==answer
    assert clock[0]>90 and budget.attempts==1 and reports
    body,accept,timeout=seen[0]
    assert body['stream'] and not body['store'] and not body['background']
    assert accept=='text/event-stream' and timeout==180

@pytest.mark.parametrize('cut',[-1,-2,-3])
def test_incomplete_stream_never_releases_partial_answer(monkeypatch,cut):
    monkeypatch.setattr(providers,'urlopen',lambda *a,**k:Stream(events({'claims':[{'text':'unchecked'}]})[:cut]))
    with pytest.raises(providers.ProviderError) as exc:providers.complete_json('s',{},ANSWER_SCHEMA)
    assert exc.value.code=='incomplete_stream' and exc.value.attempts==1

def test_stream_error_safe_and_not_reposted(monkeypatch):
    calls=[]
    def http(*a,**k):calls.append(1);return Stream([{'event_type':'error','error':{'code':'service_unavailable','message':'private-stream-test-key'}}])
    monkeypatch.setattr(providers,'urlopen',http)
    with pytest.raises(providers.ProviderError) as exc:providers.complete_json('s',{},ANSWER_SCHEMA)
    assert exc.value.code=='service_unavailable' and exc.value.http_status==200 and len(calls)==1
    assert 'private' not in str(exc.value)+json.dumps(exc.value.diagnostic())

def test_cancelled_budget_prevents_new_api_call(monkeypatch):
    stop=threading.Event()
    budget=providers.RequestBudget(progress=lambda **fields:stop.set(),cancelled=stop.is_set)
    with pytest.raises(providers.ProviderError) as exc:providers.complete_json('s',{},ANSWER_SCHEMA,budget=budget)
    assert exc.value.code=='cancelled' and exc.value.attempts==0

def test_both_streamed_steps_still_require_exact_support(monkeypatch):
    passage={'id':'book:1','text':'Perform your duty without attachment to its fruits. '*3,'page':1,'extraction':'pdf_text','review_status':'unreviewed'}
    draft={'status':'answered','claims':[{'text':'Perform your duty.','citation_ids':['book:1']}]}
    check={'answers_question':True,'checks':[{'index':0,'supported':True,'evidence':[{'id':'book:1','quote':'invented evidence does not occur'}]}]}
    replies=iter([draft,check]);bodies=[]
    def http(req,timeout):bodies.append(json.loads(req.data));return Stream(events(next(replies)))
    monkeypatch.setattr(providers,'urlopen',http)
    assert grounding.explain('Explain this.','en',[passage]) is None
    assert len(bodies)==2 and all(b['stream'] and not b['store'] for b in bodies)

def wait_done(client,key):
    until=time.monotonic()+4
    while time.monotonic()<until:
        r=client.get('/api/ask/jobs/'+key)
        if r.json['status']!='processing':return r.json
        time.sleep(.01)
    pytest.fail('Question did not finish')

def test_async_request_private_idempotent_and_reader_responsive(app,client,monkeypatch):
    gate=threading.Event();entered=threading.Event();calls=[]
    def explain(*a,progress=None,cancelled=None,**k):
        calls.append(1);progress(stage='verification',api_calls_attempted=2);entered.set();gate.wait(4)
        return [{'text':'A supported test statement.','citation_ids':['gitaasitis:164']}]
    monkeypatch.setattr(grounding,'explain',explain)
    body={'question':'Explain this page','mode':'explain','scope':'page','page_id':'gitaasitis:164','async':True,'request_id':'test_async_request_1'}
    try:
        first=client.post('/api/ask',json=body);assert first.status_code==202 and not first.json['claims']
        key=first.json['job_id'];assert entered.wait(1)
        assert client.get('/api/ask/jobs/'+key).json['stage']=='verification'
        assert client.get('/api/books').status_code==200
        assert client.post('/api/ask',json=body).json['job_id']==key and len(calls)==1
        assert client.get('/api/ask/requests/test_async_request_1').json['job_id']==key
        assert client.post('/api/ask',json={**body,'question':'Different question'}).status_code==400
        other=signup(app)[0]
        assert other.get('/api/ask/jobs/'+key).status_code==404
        assert other.get('/api/ask/requests/test_async_request_1').status_code==404
        assert other.post('/api/ask/jobs/'+key+'/cancel',json={}).status_code==404
    finally:gate.set()
    result=wait_done(client,key);assert result['status']=='answered' and result['generated']

def test_cancelled_job_discards_answer(client,monkeypatch):
    entered=threading.Event()
    def explain(*a,progress=None,cancelled=None,**k):
        entered.set();until=time.monotonic()+4
        while not cancelled() and time.monotonic()<until:time.sleep(.01)
        return [{'text':'Discard this','citation_ids':['gitaasitis:164']}]
    monkeypatch.setattr(grounding,'explain',explain)
    r=client.post('/api/ask',json={'question':'Explain this page','mode':'explain','scope':'page','page_id':'gitaasitis:164','async':True,'request_id':'cancel_question_test'})
    key=r.json['job_id'];assert entered.wait(1)
    assert client.post('/api/ask/jobs/'+key+'/cancel',json={}).status_code==200
    result=wait_done(client,key);assert result['status']=='cancelled' and not result['claims'] and not result['generated']

def test_queue_capacity_and_expiry():
    jobs=QuestionJobs(workers=1,ttl=0,capacity=1);gate=threading.Event()
    def work(progress,cancelled):gate.wait(1);return {'status':'answered'},200
    key=jobs.submit('owner','request_one','fingerprint',work)
    try:
        with pytest.raises(QueueBusy):jobs.submit('other','request_two','fingerprint',work)
        assert jobs.get('other',key) is None
    finally:gate.set();jobs.executor.shutdown(wait=True)
    assert jobs.get('owner',key) is None
