"""Accumulate GenerateContent SSE on the server; accept an explicit finish only."""
import json

def read(response,budget):
    from .providers import ProviderError
    lines=[];parts=[];size=0;events=0
    budget.stream_event_count=0;budget.stream_last_event=None
    def consume():
        nonlocal events
        if not lines:return None
        raw='\n'.join(lines)
        if raw.strip()=='[DONE]':return None
        chunk=json.loads(raw)
        if not isinstance(chunk,dict):raise ValueError('Invalid chunk')
        events+=1;budget.stream_event_count=events;budget.stream_last_event='chunk'
        if chunk.get('error'):raise ProviderError('Google ended the response with a service error. No partial answer was shown.','stream_service_error',http_status=200)
        if chunk.get('promptFeedback',{}).get('blockReason'):return {'promptFeedback':chunk['promptFeedback']}
        candidates=chunk.get('candidates',[])
        if not isinstance(candidates,list):raise ValueError('Invalid candidates')
        if not candidates:return None
        if len(candidates)!=1 or not isinstance(candidates[0],dict):raise ValueError('Invalid candidate')
        candidate=candidates[0]
        if candidate.get('index',0)!=0:raise ValueError('Unexpected candidate index')
        content=candidate.get('content',{})
        if not isinstance(content,dict):raise ValueError('Invalid content')
        deltas=content.get('parts',[])
        if not isinstance(deltas,list):raise ValueError('Invalid parts')
        for part in deltas:
            if not isinstance(part,dict):raise ValueError('Invalid part')
            if not part.get('thought') and isinstance(part.get('text'),str):parts.append({'text':part['text']})
        budget.report('receiving')
        finish=candidate.get('finishReason')
        if finish:
            budget.stream_last_event=finish if finish in {'STOP','MAX_TOKENS','SAFETY','RECITATION'} else 'finished'
            return {'candidates':[{'finishReason':finish,'content':{'parts':parts}}]}
        return None
    while True:
        budget.check();raw=response.readline(1_000_001)
        if not raw:
            result=consume()
            if result is not None:return result
            raise ProviderError('Google closed the stream without a completed answer. No partial answer was shown.','incomplete_stream',http_status=200)
        size+=len(raw)
        if len(raw)>1_000_000 or size>4_000_000:raise ValueError('Oversized stream')
        line=raw.decode('utf-8').rstrip('\r\n')
        if not line:
            result=consume();lines=[]
            if result is not None:return result
        elif line.startswith('data:'):lines.append(line[5:].lstrip(' '))
