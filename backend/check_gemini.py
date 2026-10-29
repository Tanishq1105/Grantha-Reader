"""One small, stateless provider check. Does not load accounts or send book text."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import os
import platform
from urllib.request import getproxies
from dotenv import load_dotenv
from . import providers


def run_check():
    start = time.monotonic()
    result = {
        'diagnostic_version': '3.5',
        'time_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'model': providers.model_name(),
        'api_key_configured': bool(providers.api_key()),
        'ai_enabled': providers.llm_ready(),
        'python_version':platform.python_version(),
        'proxy_configured':{kind:bool(getproxies().get(kind)) for kind in ['http','https','all']},
        'certificate_override_configured':any(os.getenv(k) for k in ['SSL_CERT_FILE','SSL_CERT_DIR']),
    }
    try:
        result['endpoint']='Gemini generateContent v1beta' if providers.api_mode()=='generate_content' else 'Gemini Interactions v1beta'
        result['response_mode']=('generate_content_stream' if providers.response_mode()=='stream' else 'json') if providers.api_mode()=='generate_content' else 'stream' if providers.streaming_enabled() else 'json'
        result['response_timeout_seconds']=providers.response_timeout() if providers.api_mode()=='generate_content' else providers._integer('GEMINI_TIMEOUT_SECONDS',180,5,300)
        budget = providers.RequestBudget(max_retries=0)
        schema = {'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok']}
        answer = providers.complete_json('Return the JSON object {"ok": true}.', {'check':'connectivity'}, schema, budget=budget)
        if answer != {'ok': True}:
            raise providers.ProviderError('Gemini returned an unexpected diagnostic response.', 'invalid_response', attempts=budget.attempts)
        result.update(result='ok', api_calls_attempted=budget.attempts,request_attempts=budget.trace,**budget.transport_details)
    except providers.ProviderError as error:
        result.update(result='failed', error=error.code, detail=str(error), **error.diagnostic())
    result['elapsed_seconds'] = round(time.monotonic()-start, 1)
    return result


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = run_check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['result'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
