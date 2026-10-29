"""Native Gemini REST integration. Keys and book context stay server-side.

API/model choices checked against Google's documentation on 2026-10-24.
No search tools or external scripture retrieval are enabled in model requests.
"""
import json
import io
import math
import os
import random
import socket
import ssl
import time
from email.utils import parsedate_to_datetime
from http.client import HTTPException
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import URLError, HTTPError

GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'
DEFAULT_MODEL = 'gemini-3.8-flash'
DEFAULT_EMBEDDING_MODEL = 'gemini-embedding-2'


class ProviderError(Exception):
    def __init__(self, message, code='provider_unavailable', *, http_status=None,
                 provider_code=None, retry_after_seconds=None, attempts=0, stage=None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.provider_code = provider_code
        self.retry_after_seconds = retry_after_seconds
        self.attempts = attempts
        self.stage = stage
        self.response_mode = None
        self.stream_event_count = None
        self.stream_last_event = None
        self.transport_details = {}

    def diagnostic(self):
        """Only locally constructed values: no response messages, headers or prompts."""
        return {'provider_http_status': self.http_status, 'provider_code': self.provider_code,
                'retry_after_seconds': self.retry_after_seconds,
                'api_calls_attempted': self.attempts, 'request_stage': self.stage,
                'response_mode': self.response_mode,
                'stream_event_count': self.stream_event_count,
                'stream_last_event': self.stream_last_event, **self.transport_details}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # An API-key-bearing request must never be forwarded to another URL.
        return None


def urlopen(req, timeout):
    return build_opener(_NoRedirect()).open(req, timeout=timeout)


def model_name():
    return os.getenv('GEMINI_MODEL', '').strip() or DEFAULT_MODEL


def api_mode():
    value=os.getenv('GEMINI_API_MODE','generate_content').strip().lower()
    if value not in {'generate_content','interactions'}:
        raise ProviderError('GEMINI_API_MODE must be generate_content or interactions.','configuration_error')
    return value


def response_mode():
    value=os.getenv('GEMINI_RESPONSE_MODE','stream').strip().lower()
    if value not in {'stream','json'}:raise ProviderError('GEMINI_RESPONSE_MODE must be stream or json.','configuration_error')
    return value

def response_timeout():
    return _integer('GEMINI_RESPONSE_TIMEOUT_SECONDS',180,10,300)

def api_key():
    return os.getenv('GEMINI_API_KEY', '').strip()


def streaming_enabled():
    value = os.getenv('GEMINI_STREAMING', 'false').strip().lower()
    if value not in {'true', 'false'}:
        raise ProviderError('GEMINI_STREAMING must be true or false.', 'configuration_error')
    return value == 'true'


def _integer(name, default, minimum, maximum):
    try:
        number = int(os.getenv(name, str(default)))
        if not minimum <= number <= maximum:
            raise ValueError()
        return number
    except ValueError as error:
        raise ProviderError(f'{name} must be between {minimum} and {maximum}.', 'configuration_error') from error


class RequestBudget:
    """One retry shared by generation and verification, with bounded scheduling."""
    def __init__(self, max_retries=None, progress=None, cancelled=None):
        self.retries_left = (_integer('GEMINI_MAX_RETRIES', 1, 0, 1)
                             if max_retries is None else max_retries)
        self.deadline = time.monotonic() + _integer('GEMINI_REQUEST_BUDGET_SECONDS', 360, 30, 600)
        self.attempts = 0
        self.progress = progress or (lambda **fields: None)
        self.cancelled = cancelled or (lambda: False)
        self.interruptible = cancelled is not None
        self.stage = 'generation'
        self.started=time.monotonic();self.trace=[];self.transport_details={}
        self.stream_event_count=None;self.stream_last_event=None

    def remaining(self):
        return max(0, self.deadline - time.monotonic())


    def check(self):
        if self.cancelled():
            raise ProviderError('This question was cancelled.', 'cancelled', attempts=self.attempts)
        if self.remaining() < 1:
            raise ProviderError('The explanation reached its time limit. Try a question about a smaller passage.', 'request_timeout', attempts=self.attempts)

    def report(self, phase=None):
        self.check()
        self.progress(stage=phase or self.stage, api_calls_attempted=self.attempts)


_KNOWN_CODES = frozenset({
    'invalid_request', 'parameter_unknown', 'failed_precondition', 'authentication',
    'payment_required', 'permission_denied', 'not_found', 'model_not_found',
    'rate_limit_exceeded', 'too_many_requests', 'quota_exceeded', 'api_error',
    'service_unavailable', 'deadline_exceeded', 'gateway_timeout', 'cancelled', 'unimplemented',
    'out_of_range', 'already_exists', 'aborted', 'safety', 'recitation', 'language',
    'prohibited_content', 'spii', 'blocklist', 'content_blocked',
})
_LEGACY_CODES = {'INVALID_ARGUMENT': 'invalid_request', 'FAILED_PRECONDITION': 'failed_precondition',
                 'UNAUTHENTICATED': 'authentication', 'PERMISSION_DENIED': 'permission_denied',
                 'NOT_FOUND': 'not_found', 'INTERNAL': 'api_error', 'UNAVAILABLE': 'service_unavailable',
                 'DEADLINE_EXCEEDED': 'deadline_exceeded', 'CANCELLED': 'cancelled'}


def _retry_after(value):
    if not isinstance(value, str) or len(value) > 128:
        return None
    try:
        if value.strip().isascii() and value.strip().isdigit():
            return int(value.strip())
        date = parsedate_to_datetime(value)
        if date.tzinfo is not None:
            return max(0, math.ceil(date.timestamp() - time.time()))
    except (ValueError, TypeError, OverflowError):
        pass
    return None


def _http_error(error):
    """Classify bounded error data; never return Google's free-form message."""
    status, provider_code = error.code, None
    delay = _retry_after(error.headers.get('Retry-After')) if error.headers else None
    try:
        raw = error.read(65_537)
        body = json.loads(raw) if len(raw) <= 65_536 else None
        info = body.get('error') if isinstance(body, dict) else None
        if isinstance(info, dict):
            native = info.get('code')
            if isinstance(native, str) and native in _KNOWN_CODES:
                provider_code = native
            elif isinstance(info.get('status'), str):
                provider_code = _LEGACY_CODES.get(info['status'])
            # Legacy embedding errors can supply a typed retry delay.
            details = info.get('details', [])
            if isinstance(details, list):
                for detail in details:
                    if not isinstance(detail, dict):
                        continue
                    if detail.get('@type') == 'type.googleapis.com/google.rpc.RetryInfo':
                        value = detail.get('retryDelay')
                        if isinstance(value, str) and len(value) < 32 and value.endswith('s'):
                            seconds = float(value[:-1])
                            if math.isfinite(seconds) and seconds >= 0:
                                delay = max(delay or 0, math.ceil(seconds))
    except (ValueError, TypeError, OSError, HTTPException):
        pass
    finally:
        error.close()

    if status == 400 and provider_code == 'failed_precondition':
        code, message = 'project_precondition', 'Google requires a project prerequisite. Check the project status and billing eligibility in AI Studio.'
    elif status in (400, 416, 422):
        code, message = 'invalid_request', 'Google rejected the request parameters. Check the server integration and Gemini model configuration.'
    elif status == 401:
        code, message = 'authentication_error', 'Google rejected the API key. Check GEMINI_API_KEY on the server.'
    elif status == 402:
        code, message = 'billing_required', 'Google reports that project credits are depleted. Review the project billing status in AI Studio.'
    elif status == 403:
        code, message = 'permission_denied', 'Google denied access. Check the API key restrictions and project permissions.'
    elif status == 404:
        code, message = 'model_unavailable', 'Google could not find the model or API resource. Check GEMINI_MODEL and project access.'
    elif status == 429 and provider_code == 'quota_exceeded':
        code, message = 'quota_exceeded', 'Google reports that the daily quota is exhausted. Wait for the quota reset or review the project limits in AI Studio.'
    elif status == 429:
        code, message = 'rate_limited', 'Google rejected the request because of a rate or quota limit. Wait before retrying and check this model’s project limits in AI Studio.'
    elif status == 503:
        code, message = 'service_unavailable', 'Google’s Gemini service is temporarily unavailable. Please try again later.'
    elif status in (408, 504):
        code, message = 'provider_timeout', 'Google could not finish within its deadline. Please try again later.'
    elif status in (500, 502):
        code, message = 'service_error', 'Google returned a server error. Please try again later.'
    elif 300 <= status < 400:
        code, message = 'redirect_blocked', 'The Gemini endpoint returned an unexpected redirect. The API key was not forwarded.'
    else:
        code, message = 'provider_unavailable', 'Google returned an unexpected API error. See the diagnostic details below.'
    return ProviderError(message, code, http_status=status, provider_code=provider_code,
                         retry_after_seconds=delay)


def _transport_error(error):
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return ProviderError('The server could not verify Google’s TLS certificate. Check the trusted certificate or proxy configuration.', 'certificate_error')
    if isinstance(reason, ssl.SSLError):
        return ProviderError('The secure connection to Google failed. Check the server’s TLS and proxy configuration.', 'tls_error')
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return ProviderError('The server timed out waiting for Gemini. The timed-out request was not automatically repeated because Google may still be processing it.', 'network_timeout')
    if isinstance(reason, socket.gaierror):
        return ProviderError('The server could not resolve Google’s API hostname. Check its internet connection and DNS settings.', 'dns_error')
    return ProviderError('The server could not complete the connection to Google. Check its internet connection and proxy settings.', 'network_error')


_STREAM_EVENTS = frozenset({
    'interaction.created', 'interaction.completed', 'interaction.status_update',
    'interaction.in_progress', 'interaction.requires_action', 'interaction.error',
    'interaction.failed', 'interaction.cancelled', 'interaction.incomplete',
    'step.start', 'step.delta', 'step.stop', 'error', 'done',
})


def _read_stream(response, budget):
    """Read SSE framing and both documented JSON discriminators; never accept EOF as success."""
    steps, lines, event_name = {}, [], ''
    size, count, last_event, done = 0, 0, None, False

    def consume():
        nonlocal count, last_event, done
        if not lines:
            return None
        raw = '\n'.join(lines)
        if raw.strip() == '[DONE]':
            done, last_event = True, 'done'
            return None
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError('Invalid stream event')
        count += 1
        # Google's REST examples use both event_type and type. SSE event: is
        # also authoritative when the JSON body omits its discriminator.
        candidates = (event.get('event_type'), event.get('type'), event_name)
        kind = next((v for v in candidates if isinstance(v, str) and v in _STREAM_EVENTS), 'unknown')
        last_event = kind
        if kind in {'error', 'interaction.error', 'interaction.failed'}:
            info = event.get('error', {})
            code = info.get('code') if isinstance(info, dict) else None
            statuses = {'service_unavailable': 503, 'api_error': 500, 'deadline_exceeded': 504,
                        'gateway_timeout': 504, 'quota_exceeded': 429, 'rate_limit_exceeded': 429,
                        'too_many_requests': 429, 'invalid_request': 400, 'parameter_unknown': 400,
                        'authentication': 401, 'permission_denied': 403, 'payment_required': 402,
                        'model_not_found': 404, 'not_found': 404}
            status = statuses.get(code, 500) if isinstance(code, str) else 500
            failure = _http_error(HTTPError(GEMINI_BASE_URL, status, '', {},
                                          io.BytesIO(json.dumps({'error': info}).encode())))
            # The HTTP response already succeeded; a second POST is ambiguous.
            failure.http_status = 200
            raise failure
        if kind in {'interaction.cancelled', 'interaction.incomplete', 'interaction.requires_action'}:
            raise ProviderError('Gemini ended without a complete answer. Try a shorter question or a smaller passage.',
                                'incomplete_response', http_status=200)
        if kind == 'step.start':
            index, step = event.get('index'), event.get('step')
            if type(index) is not int or not isinstance(step, dict) or index in steps or not 0 <= index < 100:
                raise ValueError('Invalid step start')
            content = step.get('content', [])
            if not isinstance(content, list):
                raise ValueError('Invalid step content')
            steps[index] = {**step, 'content': list(content), 'status': 'in_progress'}
        elif kind == 'step.delta':
            index, delta = event.get('index'), event.get('delta')
            if type(index) is not int or index not in steps or not isinstance(delta, dict):
                raise ValueError('Invalid step delta')
            if steps[index].get('type') == 'model_output' and delta.get('type') == 'text':
                value = delta.get('text')
                if not isinstance(value, str):
                    raise ValueError('Invalid text delta')
                steps[index]['content'].append({'type': 'text', 'text': value})
        elif kind == 'step.stop':
            index = event.get('index')
            if type(index) is not int or index not in steps:
                raise ValueError('Invalid step stop')
            steps[index]['status'] = 'done'
        elif kind == 'interaction.completed':
            result = event.get('interaction')
            if not isinstance(result, dict):
                raise ValueError('Invalid final interaction')
            if result.get('status') != 'completed':
                raise ProviderError('Gemini ended without a complete answer. Try a shorter question or a smaller passage.',
                                    'incomplete_response', http_status=200)
            return {**result, 'steps': result.get('steps', [steps[i] for i in sorted(steps)])}
        return None

    try:
        while not done:
            budget.check()
            line = response.readline(65_537)
            budget.check()
            first_line = size == 0
            size += len(line)
            if len(line) > 65_536 or size > 4_000_000:
                raise ValueError('Oversized stream')
            if not line:
                result = consume()
                if result is not None:
                    return result
                break
            line = line.decode('utf-8-sig' if first_line else 'utf-8').rstrip('\r\n')
            if not line:
                result = consume()
                lines, event_name = [], ''
                if result is not None:
                    return result
                budget.report()
            elif line.startswith('data:'):
                lines.append(line[5:].removeprefix(' '))
            elif line.startswith('event:'):
                event_name = line[6:].strip()
            # Comments/heartbeats, event IDs and retry hints carry no answer text.
        raise ProviderError('The Gemini connection closed before a completion event. No partial answer was shown. '
                            'Set GEMINI_STREAMING=false in .env and restart the app before trying again.',
                            'incomplete_stream', http_status=200)
    except (ValueError, TypeError):
        failure = ProviderError('Gemini returned a malformed or oversized response stream.', 'invalid_response', http_status=200)
        failure.response_mode, failure.stream_event_count, failure.stream_last_event = 'stream', count, last_event
        raise failure from None
    except ProviderError as failure:
        failure.response_mode, failure.stream_event_count, failure.stream_last_event = 'stream', count, last_event
        raise


def request_json(path, payload, timeout=180, *, budget=None):
    """Retry only explicit transient HTTP failures, never an ambiguous POST timeout."""
    key = api_key()
    if not key:
        raise ProviderError('Set GEMINI_API_KEY on the server.', 'not_configured')
    if not key.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in key):
        raise ProviderError('GEMINI_API_KEY must contain only the key, without spaces or line breaks.', 'configuration_error')
    if not path.startswith('/') or '?' in path or '#' in path or '..' in path:
        raise ProviderError('Invalid Gemini API path.', 'configuration_error')
    generate_stream=path.endswith(':streamGenerateContent')
    request_mode='generate_content_stream' if generate_stream else 'stream' if payload.get('stream') else 'json'
    raw_request=json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = Request(GEMINI_BASE_URL + path + ('?alt=sse' if generate_stream else ''), data=raw_request,
                  method='POST', headers={'Content-Type': 'application/json', 'x-goog-api-key': key,
                  'Accept':'text/event-stream' if generate_stream or payload.get('stream') else 'application/json'})
    budget = budget or RequestBudget(max_retries=0)
    budget.transport_details.update(request_bytes=len(raw_request),model=model_name(),api_endpoint='generateContent' if path.startswith('/models/') else 'Interactions',response_timeout_seconds=timeout)
    while True:
        budget.check()
        remaining = budget.remaining()
        budget.attempts += 1
        budget.report()
        attempt={'number':budget.attempts,'phase':'connecting_or_waiting_for_headers'};budget.trace.append(attempt);began=time.monotonic()
        def record(outcome,http_status=None):
            attempt.update(outcome=outcome,http_status=http_status,elapsed_seconds=round(time.monotonic()-began,2))
        try:
            with urlopen(req, timeout=min(timeout, remaining)) as response:
                attempt['phase']='reading_response'
                content_type=response.headers.get('Content-Type','') if hasattr(response,'headers') else ''
                if 'text/event-stream' in content_type:
                    if generate_stream:
                        from .generate_stream import read
                        result=read(response,budget)
                    else:result=_read_stream(response,budget)
                    record('completed',200);return result
                raw = response.read(4_000_001)
                if len(raw) > 4_000_000:
                    raise ValueError('Oversized response')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise ValueError('Expected response object')
                record('completed',200);return result
        except HTTPError as error:
            failure = _http_error(error)
            record(failure.code,failure.http_status)
            failure.response_mode=request_mode
            failure.attempts = budget.attempts
            delay = failure.retry_after_seconds
            if delay is None:
                delay = 2 + random.uniform(0, 1)
            if (failure.http_status in {408, 500, 502, 503, 504}
                    and budget.retries_left and delay <= 30
                    and budget.remaining() >= delay + 5):
                budget.retries_left -= 1
                budget.report('retrying')
                if not budget.interruptible:time.sleep(delay)
                else:
                    until=time.monotonic()+delay
                    while time.monotonic()<until:
                        budget.check();time.sleep(min(.25,until-time.monotonic()))
                continue
            raise failure from None
        except (URLError, OSError, HTTPException) as error:
            failure = _transport_error(error)
            record(failure.code)
            failure.response_mode=request_mode
            failure.attempts = budget.attempts
            raise failure from None
        except ProviderError as failure:
            record(failure.code,failure.http_status);failure.response_mode=request_mode
            raise
        except (ValueError, TypeError, AttributeError):
            record('invalid_response')
            raise ProviderError('Google returned an invalid or oversized JSON response.', 'invalid_response', attempts=budget.attempts) from None


def llm_ready():
    return os.getenv('AI_ENABLED', 'false').strip().lower() == 'true' and bool(api_key())


def complete_json(system, payload, schema, *, budget=None, stage='generation'):
    budget = budget or RequestBudget()
    try:
        budget.stage=stage
        budget.report()
        return _complete_json(system, payload, schema, budget)
    except ProviderError as error:
        error.stage = stage
        error.attempts = budget.attempts
        error.transport_details={**budget.transport_details,'elapsed_seconds':round(time.monotonic()-budget.started,2),'request_attempts':list(budget.trace)}
        if budget.stream_event_count is not None:error.stream_event_count=budget.stream_event_count;error.stream_last_event=budget.stream_last_event
        if error.response_mode is None and os.getenv('GEMINI_API_MODE','generate_content')=='generate_content':
            error.response_mode='generate_content_stream' if os.getenv('GEMINI_RESPONSE_MODE','stream')=='stream' else 'json'
        if error.response_mode is None:
            error.response_mode = 'stream' if os.getenv('GEMINI_API_MODE','generate_content')=='interactions' and os.getenv('GEMINI_STREAMING', 'false').strip().lower() == 'true' else 'json'
        raise


def _complete_json(system, payload, schema, budget):
    """Request a schema-bound stateless interaction, accepting final text only."""
    if not llm_ready():
        raise ProviderError('Enable AI and configure GEMINI_API_KEY.', 'not_configured')
    thinking = os.getenv('GEMINI_THINKING_LEVEL', 'low').strip()
    if thinking not in {'low', 'medium', 'high'}:
        raise ProviderError('GEMINI_THINKING_LEVEL must be low, medium or high.', 'configuration_error')
    if api_mode()=='generate_content':
        from .generate_content import generate
        return generate(system,payload,schema,budget,thinking)
    response = request_json('/interactions', {
        'model': model_name(),
        'system_instruction': system,
        'input': json.dumps(payload, ensure_ascii=False),
        'response_format': {'type': 'text', 'mime_type': 'application/json', 'schema': schema},
        'generation_config': {
            'max_output_tokens': _integer('GEMINI_MAX_OUTPUT_TOKENS', 4096, 512, 32768),
            'thinking_level': thinking,
            'thinking_summaries': 'none',
        },
        'store': False,
        'stream': streaming_enabled(),
        'background': False,
    }, timeout=_integer('GEMINI_TIMEOUT_SECONDS', 180, 5, 300), budget=budget)
    try:
        if response.get('status') != 'completed':
            raise ValueError('Interaction is not complete')
        steps = response['steps']
        if not isinstance(steps, list) or any(not isinstance(step, dict) for step in steps):
            raise ValueError('Malformed steps')
        outputs = [step for step in steps if step.get('type') == 'model_output']
        if not outputs or outputs[-1].get('status') not in (None, 'done'):
            raise ValueError('No completed model output')
        parts = outputs[-1]['content']
        if not isinstance(parts, list) or any(not isinstance(part, dict) for part in parts):
            raise ValueError('Malformed output content')
        text = ''.join(part['text'] for part in parts if part.get('type') == 'text')
        answer = json.loads(text)
        if not isinstance(answer, dict):
            raise ValueError('Expected a structured object')
        return answer
    except (KeyError, IndexError, TypeError, ValueError):
        # Incomplete/safety-blocked/tool-only output cannot become an answer.
        raise ProviderError('Gemini did not return a complete structured answer.', 'invalid_response') from None


def embeddings_ready():
    return os.getenv('EMBEDDINGS_ENABLED', 'false').strip().lower() == 'true' and bool(api_key())


def embedding_settings():
    model = os.getenv('GEMINI_EMBEDDING_MODEL', '').strip() or DEFAULT_EMBEDDING_MODEL
    if model != DEFAULT_EMBEDDING_MODEL:
        raise ProviderError('This embedding adapter uses gemini-embedding-2. Revisit its task prefixes before changing model families.', 'configuration_error')
    return {'provider': 'gemini', 'model': model,
            'dimensions': _integer('EMBEDDING_DIMENSIONS', 768, 128, 2000),
            'endpoint': GEMINI_BASE_URL, 'task_format': 'retrieval-v1'}


def embeddings(texts, task='document'):
    if not embeddings_ready():
        raise ProviderError('Set EMBEDDINGS_ENABLED=true and GEMINI_API_KEY.', 'not_configured')
    if task not in {'document', 'query'} or not isinstance(texts, list) or any(not isinstance(t, str) or not t.strip() for t in texts):
        raise ProviderError('Invalid embedding input.', 'configuration_error')
    cfg = embedding_settings()
    result = []
    # One content per call: Embedding 2 aggregates multiple parts in a content.
    # Never let different PDF pages collapse into one shared vector.
    for text in texts:
        prefixed = ('task: search result | query: ' + text) if task == 'query' else ('title: Scripture book page | text: ' + text)
        response = request_json('/models/' + cfg['model'] + ':embedContent', {
            'model': 'models/' + cfg['model'],
            'content': {'parts': [{'text': prefixed}]},
            'embedContentConfig': {'outputDimensionality': cfg['dimensions']},
        }, timeout=45)
        try:
            vector = response['embedding']['values']
            if not isinstance(vector, list) or len(vector) != cfg['dimensions']:
                raise ValueError('Wrong dimensions')
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector) or not any(vector):
                raise ValueError('Invalid vector')
            result.append(vector)
        except (KeyError, TypeError, ValueError):
            raise ProviderError('Gemini returned an invalid embedding.', 'invalid_response') from None
    return result
