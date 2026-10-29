import {useEffect, useRef, useState} from 'react';
import {api} from './api.js';
import {Icon, EmptyState} from './components.jsx';
import {useApp, readPassage} from './state.jsx';

export default function SearchDialog({open, onClose}) {
  const {books, t, title} = useApp();
  const dialog=useRef(null), queryInput=useRef(null), controller=useRef(null);
  const [query,setQuery]=useState(''), [bookId,setBookId]=useState('all');
  const [results,setResults]=useState(null), [loading,setLoading]=useState(false), [error,setError]=useState('');
  useEffect(()=>{
    if(open){if(!dialog.current.open)dialog.current.showModal();queryInput.current.focus();}
    else {dialog.current.close();controller.current?.abort();setLoading(false);}
  },[open]);
  useEffect(()=>()=>controller.current?.abort(),[]);
  async function search(event){
    event.preventDefault();controller.current?.abort();const request=new AbortController();controller.current=request;
    setLoading(true);setError('');setResults(null);
    try {const data=await api('/search?q='+encodeURIComponent(query)+'&book='+bookId,{signal:request.signal});if(controller.current===request && !request.signal.aborted)setResults(data);}
    catch(e){if(e.name!=='AbortError' && controller.current===request)setError(e.message);}
    finally{if(controller.current===request)setLoading(false);}
  }
  return <dialog id="search-dialog" ref={dialog} aria-labelledby="search-heading" onCancel={onClose} onClose={onClose}>
    <div className="search-dialog-head"><h2 id="search-heading">{t('search')}</h2><button className="icon-button" aria-label={t('close')} onClick={onClose}><Icon name="close"/></button></div>
    <form id="search-form" onSubmit={search}><div className="search-input-wrap"><Icon name="search"/><label className="sr-only" htmlFor="search-query">{t('search')}</label><input id="search-query" ref={queryInput} value={query} onChange={e=>setQuery(e.target.value)} placeholder="Try ‘page 59’, ‘Gita 2.47’, राम, or duty…" maxLength="1000" minLength="2" required/><button className="primary" disabled={loading}>{t('send')}</button></div><label className="sr-only" htmlFor="search-book">Book</label><select id="search-book" value={bookId} onChange={e=>setBookId(e.target.value)}><option value="all">{t('all')}</option>{books.map(b=><option key={b.id} value={b.id}>{title(b)}</option>)}</select></form>
    <div id="search-results" aria-live="polite">{loading?<p>{t('loading')}</p>:error?<p>{error}</p>:results?<><p className="result-count">{results.results.length} pages · {results.method} search</p>{results.results.length?results.results.map(({passage:p})=><button key={p.id} className="search-result" onClick={()=>{onClose();readPassage(p.id);}}><span>{books.find(b=>b.id===p.book_id)?.title} <strong>{p.ref_label}</strong></span><p>{(p.reference_excerpt || p.text).slice(0,240)}{(p.reference_excerpt || p.text).length>240?'…':''}</p><small>{p.extraction.includes('ocr')?'Unreviewed OCR · check the original page':'Extracted from the book PDF'}</small></button>):<EmptyState>No matching source page was found. Try an exact reference or a shorter phrase.</EmptyState>}</>:<p className="quiet">Search the text of your book editions. Use “page 59” for a PDF page. Verse and canto links follow indexed printed headings. Scanned text may contain OCR errors.</p>}</div>
  </dialog>;
}
