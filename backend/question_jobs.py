"""Private, bounded in-process questions. Deploy with one web worker."""
from concurrent.futures import ThreadPoolExecutor
import re
import secrets
import threading
import time


class QueueBusy(Exception):
    pass


class QuestionJobs:
    def __init__(self, workers=2, ttl=900, capacity=100):
        self.executor=ThreadPoolExecutor(max_workers=workers,thread_name_prefix='grantha-ai')
        self.workers,self.ttl,self.capacity=workers,ttl,capacity
        self.lock,self.jobs=threading.Lock(),{}

    def _prune(self):
        now=time.monotonic()
        for key in list(self.jobs):
            job=self.jobs[key]
            if not job['running'] and now-job['updated']>self.ttl:del self.jobs[key]

    def submit(self, owner, request_id, fingerprint, work):
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',request_id):
            raise ValueError('Send a valid question request ID.')
        with self.lock:
            self._prune()
            for key,job in self.jobs.items():
                if job['owner']==owner and job['request_id']==request_id:
                    if job['fingerprint']!=fingerprint:raise ValueError('This request ID belongs to a different question.')
                    return key
            if any(j['owner']==owner and j['running'] for j in self.jobs.values()):
                raise QueueBusy('Your earlier question is still running or stopping. Wait for it to finish before asking again.')
            if sum(j['running'] for j in self.jobs.values())>=self.workers:
                raise QueueBusy('The reading assistant is busy. Please try again shortly.')
            if len(self.jobs)>=self.capacity:
                finished=[k for k,j in self.jobs.items() if not j['running']]
                if not finished:raise QueueBusy('The reading assistant is busy. Please try again shortly.')
                del self.jobs[min(finished,key=lambda k:self.jobs[k]['updated'])]
            key=secrets.token_urlsafe(24);now=time.monotonic()
            self.jobs[key]={'owner':owner,'request_id':request_id,'fingerprint':fingerprint,'running':True,
                'created':now,'updated':now,'stage':'queued','api_calls_attempted':0,'cancel':threading.Event(),'result':None}
            self.executor.submit(self._run,key,work)
            return key

    def _run(self,key,work):
        with self.lock:event=self.jobs[key]['cancel']
        def progress(**fields):
            with self.lock:
                job=self.jobs[key]
                for field in ('stage','api_calls_attempted'):
                    if field in fields:job[field]=fields[field]
                job['updated']=time.monotonic()
        try:result,code=work(progress,event.is_set)
        except Exception:
            result,code={'status':'provider_unavailable','generated':False,'claims':[],'evidence':[],
                'message':'The question could not be completed. Please retry.','provider_error':'question_error'},503
        with self.lock:
            if event.is_set():result={**result,'status':'cancelled','generated':False,'claims':[],
                'message':'This question was stopped. Google may have processed the request.'}
            self.jobs[key].update(result=result,running=False,updated=time.monotonic())

    def get(self,owner,key):
        with self.lock:
            self._prune();job=self.jobs.get(key)
            if not job or job['owner']!=owner:return None
            if not job['running']:return {**job['result'],'job_id':key}
            return {'status':'processing','job_id':key,'stage':'cancelling' if job['cancel'].is_set() else job['stage'],
                'api_calls_attempted':job['api_calls_attempted'],'elapsed_seconds':round(time.monotonic()-job['created']),
                'generated':False,'claims':[]}

    def find(self,owner,request_id):
        with self.lock:
            self._prune()
            key=next((k for k,j in self.jobs.items() if j['owner']==owner and j['request_id']==request_id),None)
        return self.get(owner,key) if key else None

    def cancel(self,owner,key):
        with self.lock:
            job=self.jobs.get(key)
            if not job or job['owner']!=owner:return False
            if job['running']:job['cancel'].set()
            return True
