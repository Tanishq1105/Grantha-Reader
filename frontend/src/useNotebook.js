import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from './api.js';
import {mergeNotebook} from './notebookMerge.js';
export default function useNotebook(initial){
 const [notebook,setState]=useState(initial.notebook),[saveStatus,setSaveStatus]=useState('saved'),[saveError,setSaveError]=useState('');
 const latest=useRef(initial.notebook),remote=useRef({notebook:initial.notebook,revision:initial.revision});
 const pending=useRef(null),active=useRef(true),blocked=useRef(false);
 const setNotebook=useCallback(update=>{const next=typeof update==='function'?update(latest.current):update;latest.current=next;setState(next);},[]);
 const persist=useCallback(()=>{
  if(pending.current)return pending.current;
  if(blocked.current)return Promise.resolve(false);
  if(JSON.stringify(latest.current)===JSON.stringify(remote.current.notebook))return Promise.resolve(true);
  pending.current=Promise.resolve().then(async()=>{
   let conflicts=0,networkRetries=0;
   try{
    while(active.current&&JSON.stringify(latest.current)!==JSON.stringify(remote.current.notebook)){
     setSaveStatus('saving');const snapshot=structuredClone(latest.current);
     try{
      const result=await api('/me/notebook',{method:'PUT',body:JSON.stringify({notebook:snapshot,revision:remote.current.revision})});
      if(!Number.isInteger(result.revision))throw new Error('The notebook save could not be confirmed.');
      remote.current={notebook:snapshot,revision:result.revision};
     }catch(error){
      if(error.status===409&&conflicts++<2){
       const saved=await api('/me/notebook');if(!saved.notebook||!Number.isInteger(saved.revision))throw error;
       const merged=mergeNotebook(remote.current.notebook,latest.current,saved.notebook);
       remote.current=saved;latest.current=merged;if(active.current)setState(merged);continue;
      }
      if((!error.status||error.status>=500)&&error.code!=='notebook_conflict'&&networkRetries++<1){await new Promise(resolve=>setTimeout(resolve,1000));continue;}
      throw error;
     }
    }
    if(active.current){setSaveStatus('saved');setSaveError('');}return true;
   }catch(error){blocked.current=true;if(active.current){setSaveStatus('error');setSaveError(error.message);}return false;}
  }).finally(()=>{pending.current=null;});return pending.current;
 },[]);
 const retrySave=useCallback(()=>{blocked.current=false;setSaveError('');return persist();},[persist]);
 const toggleBookmark=useCallback(id=>{setNotebook(prev=>({...prev,bookmarks:prev.bookmarks.includes(id)?prev.bookmarks.filter(x=>x!==id):[...prev.bookmarks,id]}));return retrySave();},[setNotebook,retrySave]);
 useEffect(()=>{if(JSON.stringify(notebook)===JSON.stringify(remote.current.notebook)||blocked.current||pending.current)return;setSaveStatus('pending');const timer=setTimeout(persist,400);return()=>clearTimeout(timer);},[notebook,persist]);
 useEffect(()=>{
  active.current=true;
  const beforeUnload=event=>{if(JSON.stringify(latest.current)!==JSON.stringify(remote.current.notebook)){event.preventDefault();event.returnValue='';}};
  const online=()=>{if(blocked.current)retrySave();};
  window.addEventListener('beforeunload',beforeUnload);window.addEventListener('online',online);
  return()=>{active.current=false;window.removeEventListener('beforeunload',beforeUnload);window.removeEventListener('online',online);};
 },[retrySave]);
 return {notebook,setNotebook,saveStatus,saveError,flushNotebook:persist,retrySave,toggleBookmark};
}
