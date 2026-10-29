import json
from .question_jobs import QuestionJobs, QueueBusy
from pathlib import Path
from functools import lru_cache
from io import BytesIO
import hashlib
import os
import random
import threading
import time
import re
import sqlite3
from collections import OrderedDict
import pymupdf
from flask import g, Flask, jsonify, request, send_from_directory, send_file
from dotenv import load_dotenv
from .db import ROOT, Store, engine_for, initialize
from .retrieval import Retriever, tokenize, infer_books
from . import grounding, providers, vectors
from .local_rag import RagIndex
from .auth import initialize_auth
from .account_db import account_engine_for
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

load_dotenv(ROOT / '.env')
RENDER_LOCK=threading.Lock()
MESSAGES={
 'en':{'source':'These are pages from the selected uploaded book(s). A search match is not a complete answer; open each original page to check its context.', 'empty':'I could not find enough support in the selected book pages.', 'disabled':'AI explanations are not configured. The original book pages and search results remain available.', 'failed':'The explanation could not be supported by the retrieved pages. Please read the original pages below.', 'error':'The AI provider is unavailable. Your books remain readable.', 'rate':'The AI request limit has been reached. Try again in a minute.'},
 'hi':{'source':'ये चुनी हुई PDF पुस्तकों के पृष्ठ हैं। खोज का परिणाम पूरा उत्तर नहीं है; मूल पृष्ठ खोलकर संदर्भ देखें।','empty':'चुनी हुई पुस्तक के पृष्ठों में पर्याप्त आधार नहीं मिला।','disabled':'AI व्याख्या अभी कॉन्फ़िगर नहीं है। मूल पुस्तक और खोज उपलब्ध हैं।','failed':'व्याख्या के लिए पृष्ठों में पर्याप्त आधार नहीं मिला। नीचे मूल पृष्ठ पढ़ें।','error':'AI सेवा उपलब्ध नहीं है। पुस्तक पढ़ी जा सकती है।','rate':'AI अनुरोध सीमा पूरी हो गई है। एक मिनट बाद प्रयास करें।'},
 'sa':{'source':'चयितग्रन्थानां पृष्ठानि अत्र सन्ति। मूलपृष्ठेषु प्रसङ्गं पश्यतु।','empty':'चयितग्रन्थेषु पर्याप्तं प्रमाणं न प्राप्तम्।','disabled':'AI व्याख्या उपलब्धा नास्ति। मूलपृष्ठानि पठतु।','failed':'व्याख्यायाः पर्याप्तं प्रमाणं न प्राप्तम्। मूलपृष्ठानि पठतु।','error':'AI सेवा उपलब्धा नास्ति।','rate':'कृपया किञ्चित्कालानन्तरं पुनः प्रयतताम्।'}
}

def create_app(database_url=None, corpus_path=None, pdf_root=None, account_database_url=None):
    app=Flask(__name__,static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=48_000,JSON_AS_ASCII=False)
    app.json.ensure_ascii=False
    account_engine=account_engine_for(account_database_url)
    try:
        with account_engine.connect() as connection:connection.execute(text('SELECT 1'))
    except SQLAlchemyError:
        account_engine.dispose()
        raise RuntimeError('Could not connect to the account database. Run python -m backend.manage check-user-db. See docs/SUPABASE.md.') from None
    engine=engine_for(database_url);initialize(engine,corpus_path)
    store=Store(engine);retriever=Retriever(store);rag=RagIndex(store)
    try:initialize_auth(app, account_engine, store)
    except SQLAlchemyError:
        account_engine.dispose()
        raise RuntimeError('Could not initialize the private account tables. Check database ownership and docs/SUPABASE.md.') from None
    app.extensions.update(store=store,retriever=retriever,rag=rag)
    answer_cache=OrderedDict();cache_lock=threading.Lock()
    jobs=QuestionJobs()
    app.extensions['question_jobs']=jobs
    directory=Path(pdf_root or ROOT/'data/pdfs')
    book_map={b['id']:b for b in store.books}
    for b in store.books:
        file=directory/b['stored_filename']
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest()!=b['pdf_sha256']:
            raise ValueError('Original PDF missing or changed: '+b['filename'])

    def choose_book(bid):
        if bid not in book_map:raise ValueError('Choose an uploaded book edition.')
        return book_map[bid]

    def scope_books(raw):
        if raw is None or raw=='all' or raw==[]:return None
        if isinstance(raw,str):raw=[raw]
        if not isinstance(raw,list) or len(raw)>len(book_map) or any(not isinstance(b,str) or b not in book_map for b in raw):raise ValueError('Choose an uploaded book edition.')
        return list(dict.fromkeys(raw))

    def page_record(pid):
        return store.by_id.get(pid) or store.by_ref.get(pid)

    def retrieve(query,books,limit=8):
        if books is None:books=infer_books(query,store.books)
        results,method=retriever.search(query,books,limit=24)
        if method!='exact':
            try:
                if rag.ready:results,method=rag.search(query,books,limit)
                else:method='lexical_fallback'
            except (OSError,ValueError,RuntimeError,ImportError,sqlite3.Error):
                rag.ready=False;rag.reason='inference_unavailable'
                app.logger.warning('Local semantic retrieval unavailable; using book text search.')
                method='lexical_fallback'
        return results[:limit],method

    @app.errorhandler(ValueError)
    def bad_value(error):return jsonify(error=str(error)),400

    @app.errorhandler(413)
    def too_large(error):return jsonify(error='Request too large.'),413

    @app.errorhandler(SQLAlchemyError)
    def database_unavailable(error):
        app.logger.warning('Database request failed (%s).',type(error).__name__)
        return jsonify(error='Account storage is temporarily unavailable. Your latest changes may not be saved. Keep this page open and retry.',code='database_unavailable'),503

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='strict-origin-when-cross-origin'
        response.headers['X-Frame-Options']='SAMEORIGIN'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'; object-src 'self'"
        if request.path.startswith('/api/') and response.mimetype=='application/json':response.headers['Cache-Control']='no-store'
        return response

    @app.get('/api/health')
    def health():
        with account_engine.connect() as connection:connection.execute(text('SELECT 1'))
        return jsonify(status='ok',source_type='uploaded_pdf',books=len(store.books),pages=len(store.passages),account_database=account_engine.dialect.name,ai_enabled=providers.llm_ready(),ai_provider="gemini",ai_model=providers.model_name(),ai_endpoint=providers.api_mode(),app_version='3.5.0',ai_response_mode=providers.response_mode(),search='local_hybrid' if rag.ready else 'lexical',rag=rag.status(),corpus_fingerprint=store.fingerprint)

    @app.get('/api/books')
    def catalog():return jsonify(books=[{k:v for k,v in b.items() if k not in {'reference_spans','toc_override'}} for b in store.books])

    @app.get('/api/sources')
    def sources():return jsonify(sources=store.sources)

    @app.get('/api/books/<bid>/pdf')
    def pdf(bid):
        b=choose_book(bid)
        return send_file(directory/b['stored_filename'],mimetype='application/pdf',conditional=True,etag=b['pdf_sha256'],download_name=b['filename'],as_attachment=request.args.get('download')=='1',max_age=3600)

    @lru_cache(maxsize=12)
    def image_bytes(bid,page,width):
        b=choose_book(bid)
        if not 1<=page<=b['page_count']:raise ValueError('PDF page is outside this book.')
        # MuPDF is protected from concurrent threads within a Gunicorn worker.
        with RENDER_LOCK, pymupdf.open(directory/b['stored_filename']) as doc:
            source=doc[page-1];scale=width/source.rect.width
            return source.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False).tobytes('png')

    def rendered_page(bid,page,width):
        data=image_bytes(bid,page,width);b=choose_book(bid)
        return send_file(BytesIO(data),mimetype='image/png',etag=f"{b['pdf_sha256']}-{page}-{width}",max_age=3600)

    @app.get('/api/books/<bid>/cover')
    def cover(bid):return rendered_page(bid,choose_book(bid).get('cover_page',1),360)

    @app.get('/api/books/<bid>/pages/<int:page>/image')
    def page_image(bid,page):
        width=int(request.args.get('width','1200'))
        if width not in {800,1200,1800,2400,3600}:raise ValueError('Choose a page image width of 800, 1200, 1800, 2400 or 3600.')
        return rendered_page(bid,page,width)

    @app.get('/api/passages')
    def page_list():
        bid=request.args.get('book','gitascan');choose_book(bid)
        rows=store.by_book[bid];section=request.args.get('section')
        if section:rows=[p for p in rows if p['section']==section]
        offset=max(0,int(request.args.get('offset','0')));limit=min(100,max(1,int(request.args.get('limit','30'))))
        return jsonify(passages=rows[offset:offset+limit],total=len(rows),offset=offset)

    @app.get('/api/passages/<path:pid>')
    def passage(pid):
        p=page_record(pid)
        if not p:return jsonify(error='This PDF page or indexed reference is not present in the selected edition.'),404
        b=book_map[p['book_id']];n=p['page']
        return jsonify(passage=p,previous=f"{b['id']}:{n-1}" if n>1 else None,next=f"{b['id']}:{n+1}" if n<b['page_count'] else None)

    @app.get('/api/search')
    def search():
        q=request.args.get('q','').strip()
        if not 2<=len(q)<=1000:raise ValueError('Enter a question, phrase, page or reference (2–1000 characters).')
        results,method=retrieve(q,scope_books(request.args.get('book')))
        return jsonify(results=results,method=method)

    diagnostic_times={}
    @app.post('/api/ai/check')
    def check_ai():
        with cache_lock:
            now=time.monotonic()
            for owner,started in list(diagnostic_times.items()):
                if now-started>600:diagnostic_times.pop(owner,None)
            if now-diagnostic_times.get(g.user['id'],-1000)<210:return jsonify(error='A connection check was recently started. Wait before testing again.',code='diagnostic_cooldown'),429
            if not store.consume_ai_budget(max(1,int(os.getenv('AI_REQUESTS_PER_MINUTE','12')))):return jsonify(error='AI request limit reached. Try later.',code='rate_limited'),429
            diagnostic_times[g.user['id']]=now
        from .check_gemini import run_check
        return jsonify(run_check())

    @app.post('/api/ask')
    def ask():
        body=request.get_json(silent=True)
        if not isinstance(body,dict):raise ValueError('Send a JSON object.')
        if 'async' in body and type(body['async']) is not bool:raise ValueError('Invalid async setting.')
        q=body.get('question','');lang=body.get('language','en');mode=body.get('mode','strict');scope=body.get('scope','book')
        if not isinstance(q,str) or not 2<=len(q.strip())<=1000:raise ValueError('Use a question of 2–1000 characters.')
        if not isinstance(lang,str) or lang not in MESSAGES or mode not in ('strict','explain') or scope not in ('page','book','all'):raise ValueError('Invalid language, scope or mode.')
        books=scope_books(body.get('books'));history=body.get('history',[])
        if not isinstance(history,list) or len(history)>4 or any(not isinstance(x,str) or len(x)>1000 for x in history):raise ValueError('Invalid recent question history.')
        pid=body.get('page_id');current=None
        if pid is not None:
            if not isinstance(pid,str):raise ValueError('Invalid current PDF page.')
            current=page_record(pid)
            if not current or books and current['book_id'] not in books:raise ValueError('Current page is outside the selected edition.')
        selected=body.get('selected_text','')
        if not isinstance(selected,str) or len(selected)>2500:raise ValueError('Select at most 2,500 characters.')
        if selected and (not current or ' '.join(selected.split()) not in ' '.join(current['text'].split())):raise ValueError('Selected text must occur on the current indexed page.')
        q=q.strip();method='page_context'
        if current and scope=='book' and (selected or re.search(r'\b(?:this|current) page\b|इस पृष्ठ|इस पन्ने|अस्य पृष्ठस्य',q,re.I)):scope='page'
        if scope=='page':
            if not current:raise ValueError('Choose a page to ask about.')
            ps=store.by_book[current['book_id']];i=current['ordinal']
            anchor={**current,'requested_page':True}
            if selected:
                match=re.search(r'\s+'.join(re.escape(t) for t in selected.split()),current['text'])
                if match:
                    start=max(0,match.start()-180);end=min(len(current['text']),max(match.end()+180,start+1400))
                    anchor={**current,'requested_page':True,'reference_excerpt':current['text'][start:end]}
            evidence=[anchor]+[ps[n] for n in (i-1,i+1) if 0<=n<len(ps)]
        else:
            query=q
            if history and len(tokenize(q))<=2 and not retriever.has_explicit_reference(q):query=history[-1]+' '+q
            results,method=retrieve(query,None if scope=='all' else books,limit=6)
            evidence=[r['passage'] for r in results]
        evidence=[{**p,'edition':book_map[p['book_id']]['edition'],'book_title':book_map[p['book_id']]['title']} for p in evidence if p['text'].strip()]
        message=MESSAGES[lang];common={'mode':mode,'language':lang,'retrieval':method,'evidence':evidence,'claims':[],'generated':False}
        if not evidence:return jsonify(**common,status='insufficient_evidence',message=message['empty'])
        if mode=='strict':return jsonify(**common,status='sources_found',message=message['source'])
        if not providers.llm_ready():return jsonify(**common,status='ai_not_configured',message=message['disabled'])
        if os.getenv('GEMINI_SECOND_PASS','false').lower()!='true':
            prepared=grounding.compact_evidence(evidence);by_id={p['id']:p for p in evidence}
            common.update(retrieved_source_count=len(evidence),context_excerpts=len(prepared),context_characters=sum(len(p['text']) for p in prepared))
            evidence=[{**by_id[p['id']],'reference_excerpt':p['text']} for p in prepared];common['evidence']=evidence
            if not evidence:return jsonify(**common,status='insufficient_evidence',message=message['failed'])
        prompt=q+(('\nSelected excerpt from the current page:\n'+selected) if selected else '')
        cache_key=hashlib.sha256(json.dumps([g.user['id'],store.fingerprint,providers.model_name(),providers.api_mode(),prompt,lang,history,[(p['id'],p.get('reference_excerpt')) for p in evidence],os.getenv('GEMINI_SECOND_PASS','false')],ensure_ascii=False).encode()).hexdigest()
        with cache_lock:
            cached=answer_cache.get(cache_key)
            if cached and time.monotonic()-cached[0]<900:
                answer_cache.move_to_end(cache_key)
                return jsonify(**cached[1],cached=True)
        if not store.consume_ai_budget(max(1,int(os.getenv('AI_REQUESTS_PER_MINUTE','12')))):return jsonify(**common,status='rate_limited',message=message['rate']),429
        def run_explanation(progress=None,cancelled=None):
            try:claims=grounding.explain(prompt,lang,evidence,history=history,progress=progress,cancelled=cancelled)
            except providers.ProviderError as error:
                app.logger.warning('Gemini request failed: kind=%s http=%s provider=%s stage=%s calls=%s retry_after=%s mode=%s events=%s last_event=%s',
                    error.code,error.http_status,error.provider_code,error.stage,error.attempts,error.retry_after_seconds,error.response_mode,error.stream_event_count,error.stream_last_event)
                code=(429 if error.code in {'rate_limited','quota_exceeded'} else
                      504 if error.code in {'network_timeout','provider_timeout','request_timeout'} else
                      502 if error.code in {'invalid_request','invalid_response','incomplete_stream','incomplete_response'} else 503)
                return {**common,'status':'provider_unavailable','provider_error':error.code,
                    'message':message['error'],'detail':str(error),**error.diagnostic()},code
            if not claims:return {**common,'status':'insufficient_evidence','message':message['failed']},200
            label={'en':'AI interpretation of the cited book pages. Check the originals; automated checks and OCR can be wrong.','hi':'उद्धृत पुस्तक-पृष्ठों पर आधारित AI व्याख्या। मूल पृष्ठ जाँचें; OCR और स्वचालित जाँच में त्रुटि हो सकती है।','sa':'उद्धृतपृष्ठाधारिता AI व्याख्या। मूलपृष्ठानि पश्यतु; त्रुटिः सम्भवति।'}[lang]
            result={**common,'claims':claims,'generated':True,'status':'answered','message':label,'grounding':'second_pass' if os.getenv('GEMINI_SECOND_PASS','false')=='true' else 'exact_quote_check'}
            with cache_lock:
                answer_cache[cache_key]=(time.monotonic(),result)
                while len(answer_cache)>100:answer_cache.popitem(last=False)
            return result,200
        if body.get('async'):
            fingerprint=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            try:key=jobs.submit(g.user['id'],body.get('request_id'),fingerprint,run_explanation)
            except QueueBusy as error:return jsonify(**common,status='busy',message=str(error)),429
            return jsonify(**common,status='processing',job_id=key,stage='queued'),202
        result,code=run_explanation();response=jsonify(result);response.status_code=code
        if result.get('retry_after_seconds') is not None:response.headers['Retry-After']=str(result['retry_after_seconds'])
        return response

    @app.get('/api/ask/jobs/<job_id>')
    def question_status(job_id):
        result=jobs.get(g.user['id'],job_id)
        if result is None:return jsonify(error='This question expired or is not available to your account.',code='question_expired'),404
        return jsonify(result)

    @app.get('/api/ask/requests/<request_id>')
    def find_question(request_id):
        result=jobs.find(g.user['id'],request_id)
        if result is None:return jsonify(error='No running or recent question was found for this request.',code='question_not_found'),404
        return jsonify(result)

    @app.post('/api/ask/jobs/<job_id>/cancel')
    def cancel_question(job_id):
        if not jobs.cancel(g.user['id'],job_id):return jsonify(error='Question not found.'),404
        return jsonify(status='cancelling',message='Stopping the question. Google may still be processing the current request.')

    @app.get('/api/practice')
    def practice():
        bid=request.args.get('book','gitascan');choose_book(bid)
        available=[p for p in store.by_book[bid] if len(p['text'])>250 and not p.get('unresolved_glyphs') and (p['extraction']!='ocr' or (p.get('ocr_confidence') or 0)>=55)]
        if len(available)<4:return jsonify(status='unavailable',message='Not enough indexed pages for this exercise.')
        rng=random.Random(request.args.get('seed') or os.urandom(8));choices=rng.sample(available,4);answer=rng.choice(choices)
        return jsonify(status='ready',kind='page_recognition',excerpt=answer['text'][:450],extraction=answer['extraction'],choices=[{'id':p['id'],'page':p['page'],'page_url':p['page_url']} for p in choices],answer_id=answer['id'])

    @app.get('/')
    def home():
        if not (ROOT/'dist/index.html').exists():return jsonify(error='Run npm run build, or npm run dev for Vite.'),503
        return send_from_directory(ROOT/'dist','index.html')

    @app.get('/<path:filename>')
    def assets(filename):return send_from_directory(ROOT/'dist',filename)
    return app

if __name__=='__main__':create_app().run(host='127.0.0.1',port=int(os.getenv('FLASK_PORT','5000')),debug=False)
