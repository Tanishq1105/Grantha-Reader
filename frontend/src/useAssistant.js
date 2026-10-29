import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from './api.js';
const wait=(ms,signal)=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(new DOMException('Aborted','AbortError'));};const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);if(signal.aborted)abort();else signal.addEventListener('abort',abort,{once:true});});
export default function useAssistant(){
 const [conversations,setConversations]=useState({}),[pending,setPending]=useState(null);
 const state=useRef({busy:false,controller:null,job:null,cancelled:false}),alive=useRef(true);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;state.current.controller?.abort();};},[]);
 const append=useCallback((channel,message)=>{if(alive.current)setConversations(previous=>({...previous,[channel]:[...(previous[channel]||[]).slice(-29),message]}));},[]);
 const askQuestion=useCallback(async(channel,payload)=>{
  if(state.current.busy)return;
  const controller=new AbortController();state.current={busy:true,controller,job:null,cancelled:false};
  const started=Date.now(),requestId=crypto.randomUUID?.()||`q_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  const update=fields=>{if(alive.current)setPending({channel,started,...fields});};
  append(channel,{role:'user',text:payload.question,book_id:payload.page_id?.split(':')[0]||payload.books?.[0],page:payload.page_id?.split(':')[1]});update({stage:'searching'});
  try{
   let result;
   try{result=await api('/ask',{method:'POST',signal:controller.signal,body:JSON.stringify({...payload,async:true,request_id:requestId})});}
   catch(error){
    if(error.name==='AbortError'||(error.status&&error.status<500))throw error;
    update({stage:'reconnecting'});
    for(let attempt=0;attempt<3;attempt++){await wait(1500,controller.signal);try{result=await api(`/ask/requests/${requestId}`,{signal:controller.signal});break;}catch(reconnect){if(reconnect.name==='AbortError'||reconnect.status===401)throw reconnect;}}
    if(!result)throw new Error('The connection was interrupted. Your question may still be running; wait a moment before trying again.');
   }
   if(result.status==='processing'){
    state.current.job=result.job_id;
    if(state.current.cancelled)await api(`/ask/jobs/${result.job_id}/cancel`,{method:'POST',body:'{}'});
    let failures=0;
    while(result.status==='processing'){
     update({...result,stage:state.current.cancelled?'cancelling':result.stage});await wait(1500,controller.signal);
     try{result=await api(`/ask/jobs/${state.current.job}`,{signal:controller.signal});failures=0;}
     catch(error){if(error.name==='AbortError'||error.status===401||error.status===404||++failures>3)throw error;update({stage:'reconnecting'});await wait(1500,controller.signal);}
     if(Date.now()-started>660000)throw new Error('This question is taking too long. The server may still be finishing it; try again later.');
    }
   }
   append(channel,{role:'assistant',...result,retryPayload:payload});
  }catch(error){if(error.name!=='AbortError')append(channel,{role:'assistant',status:'connection_error',message:error.message,evidence:[],retryPayload:payload});}
  finally{state.current.busy=false;if(alive.current)setPending(null);}
 },[append]);
 const cancelQuestion=useCallback(async()=>{if(!state.current.busy)return;state.current.cancelled=true;setPending(p=>p?{...p,stage:'cancelling'}:p);if(state.current.job)try{await api(`/ask/jobs/${state.current.job}/cancel`,{method:'POST',body:'{}'});}catch(error){if(alive.current)setPending(p=>p?{...p,cancelError:error.message}:p);}},[]);
 const clearConversation=useCallback(channel=>{if(!state.current.busy)setConversations(p=>({...p,[channel]:[]}));},[]);
 return {conversations,pending,askQuestion,cancelQuestion,clearConversation};
}
