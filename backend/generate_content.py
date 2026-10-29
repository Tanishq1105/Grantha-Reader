"""Small stateless generateContent request. A partial completion is never an answer."""
import json
import re

def generate(system,payload,schema,budget,thinking):
    from . import providers as p
    model=p.model_name()
    if not re.fullmatch(r'[a-zA-Z0-9._-]{1,100}',model):
        raise p.ProviderError('GEMINI_MODEL must be a model ID, without a URL or slash.','configuration_error')
    action=':streamGenerateContent' if p.response_mode()=='stream' else ':generateContent'
    response=p.request_json('/models/'+model+action,{
        'systemInstruction':{'parts':[{'text':system}]},
        'contents':[{'role':'user','parts':[{'text':json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]}],
        'generationConfig':{'responseMimeType':'application/json','responseJsonSchema':schema,
            'maxOutputTokens':min(4096,p._integer('GEMINI_MAX_OUTPUT_TOKENS',4096,512,32768)),
            'thinkingConfig':{'thinkingLevel':thinking}},
    },timeout=p.response_timeout(),budget=budget)
    try:
        if response.get('promptFeedback',{}).get('blockReason'):
            raise p.ProviderError('Gemini blocked this request. Try a question about a specific book passage.','content_blocked',http_status=200)
        candidates=response.get('candidates')
        if not isinstance(candidates,list) or not candidates:raise ValueError()
        candidate=candidates[0];finish=candidate.get('finishReason')
        if finish=='MAX_TOKENS':raise p.ProviderError('Gemini reached its output limit before completing the answer. Ask for a shorter explanation.','output_limit',http_status=200)
        if finish!='STOP':raise p.ProviderError('Gemini did not complete an answer for this question.','incomplete_response',http_status=200)
        answer=json.loads(''.join(part['text'] for part in candidate['content']['parts'] if isinstance(part,dict) and isinstance(part.get('text'),str) and not part.get('thought')))
        if not isinstance(answer,dict):raise ValueError()
        return answer
    except (KeyError,TypeError,ValueError,AttributeError):
        raise p.ProviderError('Gemini returned an invalid structured answer.','invalid_response',http_status=200) from None
