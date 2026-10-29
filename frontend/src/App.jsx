import {useCallback,useEffect,useRef,useState} from 'react';
import {api} from './api.js';
import {LABELS,validNotebook} from '../lib.js';
import {AppContext,readLocal,parseRoute,navigate,readPassage} from './state.jsx';
import {Icon} from './components.jsx';
import Auth from './Auth.jsx';
import useNotebook from './useNotebook.js';
import useAssistant from './useAssistant.js';
import Library from './pages/Library.jsx';
import Reader from './pages/Reader.jsx';
import Study from './pages/Study.jsx';
import Sources from './pages/Sources.jsx';
import Account from './pages/Account.jsx';
import SearchDialog from './SearchDialog.jsx';

export default function App(){
 const [user,setUser]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 const [signupEnabled,setSignupEnabled]=useState(true);
 useEffect(()=>{const theme=readLocal('grantha-reading-theme','paper');document.documentElement.dataset.readingTheme=['paper','sepia','night'].includes(theme)?theme:'paper';},[]);
 const [lang,setLang]=useState(()=>{const value=readLocal('grantha-language','en');return LABELS[value]?value:'en';});
 useEffect(()=>{let active=true;setLoading(true);setError('');api('/auth/session').then(r=>{if(active){setUser(r.user);setSignupEnabled(r.signup_enabled!==false);}}).catch(e=>{if(active)setError(e.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[attempt]);
 useEffect(()=>{document.documentElement.lang=lang;try{localStorage.setItem('grantha-language',lang);}catch{}},[lang]);
 useEffect(()=>{const expired=()=>{setUser(null);setAttempt(x=>x+1);};window.addEventListener('grantha-session-expired',expired);return()=>window.removeEventListener('grantha-session-expired',expired);},[]);
 if(loading || error)return <div className="initial-loading"><span className="brand-mark">ग</span>{error?<><h1>The reading room is unavailable.</h1><p>{error}</p><button className="primary" onClick={()=>setAttempt(x=>x+1)}>Try again</button></>:<p role="status">Opening your reading room…</p>}</div>;
 if(!user)return <Auth lang={lang} setLang={setLang} onAuth={setUser} signupEnabled={signupEnabled}/>;
 return <LoadReadingRoom key={user.id} user={user} lang={lang} setLang={setLang} onLogout={()=>setUser(null)}/>;
}

function LoadReadingRoom(props){
 const [data,setData]=useState(null),[error,setError]=useState(''),[attempt,setAttempt]=useState(0);
 useEffect(()=>{
  const controller=new AbortController();let active=true;setError('');
  Promise.all(['/books','/sources','/health','/me/notebook'].map(path=>api(path,{signal:controller.signal}))).then(([books,sources,health,saved])=>{
   if(active)setData({books:books.books,sources:sources.sources,health,initial:{...saved,notebook:validNotebook(saved.notebook,books.books.map(b=>b.id))}});
  }).catch(e=>{if(active&&e.name!=='AbortError')setError(e.message);});
  return()=>{active=false;controller.abort();};
 },[attempt]);
 if(!data)return <div className="initial-loading"><span className="brand-mark">ग</span>{error?<><h1>Your books could not be loaded.</h1><p>{error}</p><button className="primary" onClick={()=>setAttempt(x=>x+1)}>Try again</button></>:<p role="status">Loading your books and notebook…</p>}</div>;
 return <ReadingRoom {...props} catalog={data}/>;
}

function ReadingRoom({user,lang,setLang,onLogout,catalog}){
 const [route,setRoute]=useState(()=>parseRoute(window.location.hash));
 const synced=useNotebook(catalog.initial);
 const [searchOpen,setSearchOpen]=useState(false),[toastMessage,setToastMessage]=useState('');
 const assistant=useAssistant();
 const [mode,setMode]=useState(catalog.health.ai_enabled?'explain':'strict');
 const [navCollapsed,setNavCollapsed]=useState(()=>readLocal('grantha-nav-collapsed','true')==='true');
 useEffect(()=>{try{localStorage.setItem('grantha-nav-collapsed',String(navCollapsed));}catch{}},[navCollapsed]);
 const timer=useRef(null);
 const toast=useCallback(message=>{setToastMessage(message);clearTimeout(timer.current);timer.current=setTimeout(()=>setToastMessage(''),4500);},[]);
 const closeSearch=useCallback(()=>setSearchOpen(false),[]);
 useEffect(()=>()=>clearTimeout(timer.current),[]);
 useEffect(()=>{const change=()=>setRoute(parseRoute(window.location.hash));window.addEventListener('hashchange',change);return()=>window.removeEventListener('hashchange',change);},[]);
 useEffect(()=>{window.scrollTo(0,0);},[route.page]);
 useEffect(()=>{if(route.page!=='reader')document.title='Grantha — '+(LABELS[lang][route.page] || 'Account');},[route.page,lang]);
 useEffect(()=>{
  function shortcut(e){if(document.fullscreenElement||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)||document.activeElement?.isContentEditable)return;if(e.key==='/'&&!searchOpen){e.preventDefault();setSearchOpen(true);}}
  document.addEventListener('keydown',shortcut);return()=>document.removeEventListener('keydown',shortcut);
 },[searchOpen]);
 async function logout(){if(!await synced.flushNotebook()){toast('Save or export your unsaved notebook before signing out.');return;}try{await api('/auth/logout',{method:'POST',body:'{}'});onLogout();}catch(e){toast(e.message);}}
 const t=key=>LABELS[lang][key] || LABELS.en[key] || key;
 const resumePage=synced.notebook.lastPage || catalog.books[0].id+':'+catalog.books[0].start_page;
 function go(page){page==='reader'?readPassage(resumePage):navigate(page);if(window.innerWidth<900)setNavCollapsed(true);}
 const value={...catalog,...synced,...assistant,user,lang,t,title:b=>lang==='en'?b.title:b.title_sa || b.title,toast,mode,setMode,resumePage,logout};
 return <AppContext.Provider value={value}><div className={`app-shell ${navCollapsed?'nav-collapsed':''} ${route.page==='reader'?'reader-active':''}`}>
  <a className="skip-link" href="#main" onClick={e=>{e.preventDefault();document.getElementById('main').focus();}}>Skip to content</a>
  <header className="site-header"><div className="brand-group"><button className="icon-button nav-toggle" aria-label={navCollapsed?'Expand navigation':'Collapse navigation'} aria-expanded={!navCollapsed} aria-controls="app-navigation" onClick={()=>setNavCollapsed(x=>!x)}><Icon name="sidebar"/></button><a className="brand" href="#library"><span className="brand-mark">ग</span><span>GRANTHA<small>THE READING ROOM</small></span></a></div><div className="header-tools"><span className="header-sync" aria-live="polite"><Icon name={synced.saveStatus==='saved'?'check':'refresh'}/>{synced.saveStatus==='saved'?'All changes saved':synced.saveStatus==='error'?'Not synced':'Saving…'}</span><button className="icon-button search-trigger" aria-label={t('search')} onClick={()=>setSearchOpen(true)}><Icon name="search"/></button><label className="sr-only" htmlFor="ui-language">{t('language')}</label><select id="ui-language" value={lang} onChange={e=>setLang(e.target.value)}><option value="en">English</option><option value="hi">हिन्दी</option><option value="sa">संस्कृतम्</option></select><button className={'account-button '+(route.page==='account'?'active':'')} onClick={()=>go('account')} aria-label={t('account')} title={user.name}><span>{user.name.charAt(0).toUpperCase()}</span></button></div></header>
  {!navCollapsed&&<button className="navigation-backdrop" aria-label="Close navigation" onClick={()=>setNavCollapsed(true)}/>}
  <aside id="app-navigation" className="global-sidebar"><nav aria-label="Main navigation">{[['library','library'],['reader','book'],['study','pen'],['sources','leaf']].map(([page,icon])=><button key={page} onClick={()=>go(page)} title={t(page)} aria-label={t(page)} className={'nav-button '+(route.page===page?'active':'')} aria-current={route.page===page?'page':undefined}><Icon name={icon}/><span>{t(page)}</span></button>)}<div className="nav-divider"/><button className="nav-button" title={t('bookmarks')} aria-label={t('bookmarks')} onClick={()=>go('study/bookmarks')}><Icon name="save"/><span>{t('bookmarks')}</span><small>{synced.notebook.bookmarks.length}</small></button><button className="nav-button" title="Ask the collection" aria-label="Ask the collection" onClick={()=>{go('library');setTimeout(()=>document.getElementById('home-question')?.focus(),100);}}><Icon name="sparkle"/><span>Ask the collection</span></button></nav><div className="sidebar-foot"><Icon name="leaf"/><p>Read slowly.<br/>Return to the source.</p></div></aside>
  {synced.saveError&&<div className="save-error" role="alert"><span>{synced.saveError} Your unsaved notebook is still on this page.</span><button onClick={synced.retrySave}>Retry save</button><button onClick={()=>navigate('study')}>Export notebook</button></div>}
  <main id="main" tabIndex="-1" className={route.page==='reader'?'reader-main':''}>{route.page==='library'?<Library/>:route.page==='reader'?<Reader id={route.id} searchOpen={searchOpen}/>:route.page==='study'?<Study tabHint={route.tab}/>:route.page==='account'?<Account/>:<Sources/>}</main>
  <footer className="site-footer"><span>ग्रन्थ · A space for close reading</span><span>{synced.saveStatus==='saved'?'Notebook saved to your account':synced.saveStatus==='error'?'Notebook has unsaved changes':'Saving your notebook…'}</span><button onClick={()=>navigate('sources')}>Edition & attribution <Icon name="arrow"/></button></footer>
  <SearchDialog open={searchOpen} onClose={closeSearch}/><div id="toast" className={toastMessage?'visible':''} role="status" aria-live="polite">{toastMessage}</div>
 </div></AppContext.Provider>;
}
