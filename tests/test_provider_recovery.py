"""Transient failures, retry limits and safe diagnostics; no live Google calls."""
import io
import json
import socket
import ssl
from email.utils import formatdate
from urllib.error import HTTPError, URLError

import pytest
from backend import providers, grounding
from backend.schemas import ANSWER_SCHEMA


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setenv('GEMINI_API_MODE','interactions')
    monkeypatch.setenv('GEMINI_SECOND_PASS','true')
    for key in ('GEMINI_REQUEST_BUDGET_SECONDS', 'GEMINI_MAX_RETRIES', 'GEMINI_TIMEOUT_SECONDS', 'GEMINI_THINKING_LEVEL', 'GEMINI_MAX_OUTPUT_TOKENS'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GEMINI_API_KEY', 'private-test-key')
    monkeypatch.setenv('AI_ENABLED', 'true')
    monkeypatch.setattr(providers, 'urlopen', lambda *a, **k: pytest.fail('Unexpected network call'))
    monkeypatch.setattr(providers.time, 'sleep', lambda seconds: pytest.fail('Unexpected real sleep'))


def http_error(status=503, code='service_unavailable', delay=None, body=None):
    payload = body if body is not None else json.dumps({'error': {
        'code': code, 'message': 'private-test-key; private user question; full book text',
        'details': [{'project': 'private-project'}]}}).encode()
    return HTTPError('https://generativelanguage.googleapis.com/v1beta/interactions', status,
                     'private reason', {'Retry-After': delay} if delay is not None else {}, io.BytesIO(payload))


def response(value):
    return io.BytesIO(json.dumps({'status': 'completed', 'steps': [{
        'type': 'model_output', 'content': [{'type': 'text', 'text': json.dumps(value)}]}]}).encode())


def fake_clock(monkeypatch):
    clock = [0.0]
    waits = []
    monkeypatch.setattr(providers.time, 'monotonic', lambda: clock[0])
    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds
    monkeypatch.setattr(providers.time, 'sleep', sleep)
    monkeypatch.setattr(providers.random, 'uniform', lambda a, b: 0.5)
    return clock, waits


def test_503_retry_after_30_then_success(monkeypatch):
    clock, waits = fake_clock(monkeypatch)
    requests = []
    def http(req, timeout):
        requests.append((req, timeout))
        if len(requests) == 1:
            clock[0] += 42.4
            raise http_error(delay='30')
        return response({'status': 'insufficient_evidence', 'claims': []})
    monkeypatch.setattr(providers, 'urlopen', http)
    result = providers.complete_json('source-only', {}, ANSWER_SCHEMA)
    assert result['status'] == 'insufficient_evidence'
    assert waits == [30] and len(requests) == 2
    assert requests[0][0].data == requests[1][0].data
    assert all(timeout == 180 for _, timeout in requests)


@pytest.mark.parametrize('status,provider_code,kind', [
    (400, 'invalid_request', 'invalid_request'),
    (400, 'parameter_unknown', 'invalid_request'),
    (400, 'failed_precondition', 'project_precondition'),
    (401, 'authentication', 'authentication_error'),
    (402, 'payment_required', 'billing_required'),
    (403, 'permission_denied', 'permission_denied'),
    (404, 'model_not_found', 'model_unavailable'),
    (429, 'quota_exceeded', 'quota_exceeded'),
    (429, 'rate_limit_exceeded', 'rate_limited'),
    (499, 'cancelled', 'provider_unavailable'),
])
def test_permanent_and_quota_errors_are_not_retried_or_leaked(monkeypatch, status, provider_code, kind):
    calls = []
    def http(*args, **kwargs):
        calls.append(1)
        raise http_error(status, provider_code, '30')
    monkeypatch.setattr(providers, 'urlopen', http)
    with pytest.raises(providers.ProviderError) as exc:
        providers.complete_json('private prompt', {}, ANSWER_SCHEMA)
    error = exc.value
    assert len(calls) == 1 and error.attempts == 1
    assert error.http_status == status and error.code == kind and error.provider_code == provider_code
    assert error.stage == 'generation' and error.retry_after_seconds == 30
    assert 'private' not in str(error) + json.dumps(error.diagnostic())


@pytest.mark.parametrize('status', [408, 500, 502, 503, 504])
def test_transient_failures_stop_after_one_retry(monkeypatch, status):
    _, waits = fake_clock(monkeypatch)
    def http(*args, **kwargs):
        raise http_error(status, 'api_error')
    monkeypatch.setattr(providers, 'urlopen', http)
    with pytest.raises(providers.ProviderError) as exc:
        providers.complete_json('s', {}, ANSWER_SCHEMA)
    assert exc.value.attempts == 2 and waits == [2.5]
    assert exc.value.http_status == status


@pytest.mark.parametrize('delay', ['31', '120', '86400'])
def test_long_retry_after_is_reported_without_retrying_early(monkeypatch, delay):
    def http(*args, **kwargs):
        raise http_error(delay=delay)
    monkeypatch.setattr(providers, 'urlopen', http)
    with pytest.raises(providers.ProviderError) as exc:
        providers.complete_json('s', {}, ANSWER_SCHEMA)
    assert exc.value.attempts == 1 and exc.value.retry_after_seconds == int(delay)


def test_http_date_and_legacy_retry_info(monkeypatch):
    monkeypatch.setattr(providers.time, 'time', lambda: 1_700_000_000)
    date = formatdate(1_700_000_030, usegmt=True)
    error = providers._http_error(http_error(delay=date))
    assert error.retry_after_seconds == 30
    body = json.dumps({'error': {'code': 503, 'status': 'UNAVAILABLE', 'details': [
        {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '30.5s'}]}}).encode()
    error = providers._http_error(http_error(body=body))
    assert error.provider_code == 'service_unavailable' and error.retry_after_seconds == 31


@pytest.mark.parametrize('body', [b'not JSON: private-test-key', b'x' * 70000,
    b'{"error":{"code":"private-test-key","status":"private-project"}}',
    b'{"error":{"code":[],"status":{}}}', b'{"error":null}'])
def test_untrusted_error_body_cannot_escape(monkeypatch, body):
    monkeypatch.setenv('GEMINI_MAX_RETRIES', '0')
    def http(*args, **kwargs):
        raise http_error(body=body)
    monkeypatch.setattr(providers, 'urlopen', http)
    with pytest.raises(providers.ProviderError) as exc:
        providers.complete_json('s', {}, ANSWER_SCHEMA)
    assert exc.value.code == 'service_unavailable'
    assert exc.value.provider_code is None
    assert 'private' not in str(exc.value) + json.dumps(exc.value.diagnostic())


@pytest.mark.parametrize('reason,kind', [
    (TimeoutError('private'), 'network_timeout'),
    (ssl.SSLCertVerificationError('private'), 'certificate_error'),
    (ssl.SSLError('private'), 'tls_error'),
    (socket.gaierror('private'), 'dns_error'),
    (ConnectionRefusedError('private'), 'network_error'),
])
def test_transport_failures_never_retry_an_ambiguous_post(monkeypatch, reason, kind):
    def http(*args, **kwargs):
        raise URLError(reason)
    monkeypatch.setattr(providers, 'urlopen', http)
    with pytest.raises(providers.ProviderError) as exc:
        providers.complete_json('s', {}, ANSWER_SCHEMA)
    assert exc.value.code == kind and exc.value.attempts == 1
    assert exc.value.http_status is None and 'private' not in str(exc.value)


def test_budget_shrinks_timeout_and_stops_new_requests(monkeypatch):
    clock, waits = fake_clock(monkeypatch)
    budget = providers.RequestBudget()
    timeouts = []
    def http(req, timeout):
        timeouts.append(timeout)
        clock[0] = 359.5
        raise http_error(delay='30')
    monkeypatch.setattr(providers, 'urlopen', http)
    clock[0] = 350
    with pytest.raises(providers.ProviderError) as exc:
        providers.complete_json('s', {}, ANSWER_SCHEMA, budget=budget, stage='verification')
    assert timeouts == [10] and not waits
    assert exc.value.stage == 'verification' and exc.value.attempts == 1
    with pytest.raises(providers.ProviderError) as exc:
        providers.complete_json('s', {}, ANSWER_SCHEMA, budget=budget)
    assert exc.value.code == 'request_timeout' and timeouts == [10]


@pytest.mark.parametrize('retry_on', ['generation', 'verification'])
def test_pipeline_shares_one_retry_and_preserves_source_verification(monkeypatch, retry_on):
    _, waits = fake_clock(monkeypatch)
    passage = {'id':'book:1', 'text':'Perform your duty without attachment to its fruits. ' * 3,
               'page':1, 'extraction':'pdf_text', 'review_status':'unreviewed'}
    draft = {'status':'answered','claims':[{'text':'Perform your duty.', 'citation_ids':['book:1']}]}
    verdict = {'answers_question':True,'checks':[{'index':0,'supported':True,
               'evidence':[{'id':'book:1','quote':'Perform your duty without attachment'}]}]}
    stages = []
    failed = False
    def http(req, timeout):
        nonlocal failed
        data = json.loads(req.data)
        stage = 'verification' if 'claims' in json.loads(data['input']) else 'generation'
        stages.append(stage)
        if stage == retry_on and not failed:
            failed = True
            raise http_error(delay='1')
        return response(draft if stage == 'generation' else verdict)
    monkeypatch.setattr(providers, 'urlopen', http)
    claims = grounding.explain('What should I do?', 'en', [passage])
    assert claims == draft['claims'] and waits == [1]
    assert stages == (['generation','generation','verification'] if retry_on == 'generation'
                      else ['generation','verification','verification'])


def test_failed_verification_never_returns_unchecked_draft(monkeypatch):
    _, waits = fake_clock(monkeypatch)
    passage = {'id':'book:1','text':'Perform your duty without attachment. ' * 3,
               'page':1,'extraction':'pdf_text','review_status':'unreviewed'}
    calls = []
    def http(req, timeout):
        data = json.loads(json.loads(req.data)['input'])
        calls.append(data)
        if len(calls) == 2:
            return response({'status':'answered','claims':[{'text':'Do your duty.','citation_ids':['book:1']}]})
        raise http_error(delay='1')
    monkeypatch.setattr(providers, 'urlopen', http)
    with pytest.raises(providers.ProviderError) as exc:
        grounding.explain('Explain this page', 'en', [passage])
    assert exc.value.stage == 'verification' and exc.value.attempts == 3
    assert len(waits) == 1 and 'claims' in calls[-1]


def test_api_returns_safe_diagnostics_and_source_fallback(client, monkeypatch, caplog):
    monkeypatch.setenv('GEMINI_MAX_RETRIES', '0')
    def http(*args, **kwargs):
        raise http_error(delay='30')
    monkeypatch.setattr(providers, 'urlopen', http)
    r = client.post('/api/ask',json={'question':'Explain this page','scope':'page',
                    'page_id':'gitaasitis:164','mode':'explain'})
    assert r.status_code == 503 and r.headers['Retry-After'] == '30'
    assert r.json['provider_http_status'] == 503 and r.json['provider_code'] == 'service_unavailable'
    assert r.json['request_stage'] == 'generation' and r.json['api_calls_attempted'] == 1
    assert r.json['claims'] == [] and r.json['generated'] is False
    assert r.json['evidence'][0]['id'] == 'gitaasitis:164'
    assert 'private-test-key' not in r.get_data(as_text=True) + caplog.text
    assert 'http=503 provider=service_unavailable stage=generation calls=1' in caplog.text


def test_redirect_does_not_forward_key(monkeypatch):
    from email.message import Message
    from urllib.request import Request, HTTPSHandler, build_opener
    from urllib.response import addinfourl
    requests = []
    class FakeHTTPS(HTTPSHandler):
        def https_open(self, req):
            requests.append(req)
            headers = Message()
            headers['Location'] = 'https://example.invalid/steal'
            result = addinfourl(io.BytesIO(), headers, req.full_url, 302)
            result.msg = 'Found'
            return result
    opener = build_opener(providers._NoRedirect(), FakeHTTPS())
    req = Request('https://generativelanguage.googleapis.com/v1beta/interactions', data=b'{}',
                  headers={'x-goog-api-key': 'private-test-key'})
    with pytest.raises(HTTPError):
        opener.open(req)
    assert len(requests) == 1 and requests[0].full_url == req.full_url
