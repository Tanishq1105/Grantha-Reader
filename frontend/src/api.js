let csrfToken='';
export function setCSRF(value){csrfToken=value||'';}
export async function api(path,options={}){
 const {timeoutMs=20000,signal,...requestOptions}=options;
 const controller=new AbortController();let timedOut=false;
 const abort=()=>controller.abort();if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{once:true});
 const timer=setTimeout(()=>{timedOut=true;controller.abort();},timeoutMs);
 let response,body;
 try{
  response=await fetch('/api'+path,{...requestOptions,signal:controller.signal,credentials:'same-origin',headers:{'Content-Type':'application/json',...(csrfToken?{'X-CSRF-Token':csrfToken}:{}),...options.headers}});
  try{body=await response.json();}catch(error){if(controller.signal.aborted)throw error;throw new Error('The server returned an invalid response.');}
  if(!body||typeof body!=='object')throw new Error('The server returned an invalid response.');
 }catch(error){if(timedOut){const e=new Error('The app server took too long to respond. Check the connection and try again.');e.code='network_timeout';throw e;}throw error;}
 finally{clearTimeout(timer);signal?.removeEventListener('abort',abort);}
 if(body.csrf_token)setCSRF(body.csrf_token);
 if(!response.ok&&!body.status){if(response.status===401&&!path.startsWith('/auth/'))window.dispatchEvent(new Event('grantha-session-expired'));const e=new Error(body.error||'The request failed. Please try again.');e.status=response.status;e.code=body.code;throw e;}
 return body;
}
export async function sectionPassages(bookId,section,signal){
 const query=`/passages?book=${encodeURIComponent(bookId)}&section=${encodeURIComponent(section)}`;
 const first=await api(query,{signal}),passages=[...first.passages];
 while(passages.length<first.total){const page=await api(query+'&offset='+passages.length,{signal});if(!page.passages.length)break;passages.push(...page.passages);}return passages;
}
