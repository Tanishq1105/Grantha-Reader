import React from 'react';
import {beforeEach, test, expect, vi} from 'vitest';
import {render, screen, waitFor, within, fireEvent} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../frontend/src/App.jsx';
import original from './fixtures/pdf-sample.json';

let corpus, calls, signedIn, remoteNotebook, revision;
const account={id:'reader-1',name:'Ananya',email:'ananya@example.test'};
const user=()=>userEvent.setup();
function reply(body,ok=true,status=ok?200:400){return Promise.resolve({ok,status,json:async()=>body});}
function mockFetch(url,options={}){
 const u=new URL(url,'http://localhost');calls.push({url,options});
 if(u.pathname==='/api/auth/session')return reply({user:signedIn?account:null,csrf_token:'test-csrf'});
 if(['/api/auth/login','/api/auth/signup'].includes(u.pathname)){signedIn=true;return reply({user:account,csrf_token:'rotated-csrf'});}
 if(u.pathname==='/api/auth/logout'){signedIn=false;return reply({user:null,csrf_token:'logout-csrf'});}
 if(u.pathname==='/api/me/notebook'){
  if(options.method==='PUT'){
   const body=JSON.parse(options.body);if(body.revision!==revision)return reply({error:'Notebook changed on another device.',code:'notebook_conflict'},false,409);
   remoteNotebook=body.notebook;revision++;return reply({revision});
  }return reply({notebook:remoteNotebook,revision});
 }
 if(u.pathname==='/api/books')return reply({books:corpus.books});
 if(u.pathname==='/api/sources')return reply({sources:corpus.sources});
 if(u.pathname==='/api/health')return reply({ai_enabled:false,books:3,pages:3760});
 if(u.pathname.startsWith('/api/passages/')){
  const id=decodeURIComponent(u.pathname.split('/').pop());
  const p=corpus.passages.find(p=>p.id===id || p.refs.some(r=>p.book_id+':'+r===id));
  if(!p)return reply({error:'This PDF page is not in the selected edition.'},false);
  const b=corpus.books.find(b=>b.id===p.book_id);
  return reply({passage:p,previous:p.page>1?b.id+':'+(p.page-1):null,next:p.page<b.page_count?b.id+':'+(p.page+1):null});
 }
 if(u.pathname==='/api/search')return reply({method:'exact',results:u.searchParams.get('q').includes('99.999')?[]:[{passage:corpus.passages.find(p=>p.id==='gitaasitis:163')}]});
 if(u.pathname==='/api/ask'){
  const body=JSON.parse(options.body),p=corpus.passages.find(p=>p.id===body.page_id)||corpus.passages[0];
  return reply({status:body.mode==='strict'?'sources_found':'ai_not_configured',generated:false,claims:[],message:body.mode==='strict'?'Matching book pages.':'AI explanations are not configured.',evidence:[p]});
 }
 if(u.pathname==='/api/practice'){
  const ps=corpus.passages.filter(p=>p.book_id===u.searchParams.get('book')).slice(0,4);
  return reply(ps.length<4?{status:'unavailable',message:'Not enough indexed pages for this exercise.'}:{status:'ready',excerpt:ps[0].text.slice(0,450),extraction:ps[0].extraction,choices:ps,answer_id:ps[0].id});
 }
 return reply({error:'Unexpected test request: '+url},false);
}
beforeEach(()=>{corpus=structuredClone(original);calls=[];signedIn=true;revision=0;remoteNotebook={version:1,notes:{},bookmarks:[],read:[],lastPage:'gitascan:13'};localStorage.clear();window.history.replaceState(null,'','/');vi.stubGlobal('fetch',vi.fn(mockFetch));});
async function openReader(id='gitaasitis/164'){window.history.replaceState(null,'','/#read/'+id);render(<App/>);await screen.findByRole('button',{name:'Save page'});if(!document.getElementById('reader-contents'))fireEvent.click(screen.getByRole('button',{name:'Book contents'}));}

test('bookshelf shows the three uploaded editions and original source filenames',async()=>{
 const u=user();render(<App/>);
 expect((await screen.findAllByRole('button',{name:/^Begin reading:/}))).toHaveLength(3);
 expect(screen.getByText('3,760')).toBeTruthy();
 await u.click(within(screen.getByRole('navigation')).getByRole('button',{name:'Sources',exact:true}));
 for(const book of corpus.books)expect(await screen.findByText(book.filename)).toBeTruthy();
 expect(screen.getByText(/two Gītā books retain their own page numbers/)).toBeTruthy();
});
test('reader displays original PDF page, saves notes, and preserves page across language changes',async()=>{
 const u=user();await openReader('gitascan/13');
 const img=document.querySelector('.pdf-page-image');expect(img.src).toContain('/api/books/gitascan/pages/13/image');
 await u.click(screen.getByRole('button',{name:'Save page'}));
 await u.click(screen.getByRole('button',{name:'Notes',exact:true}));
 await u.type(screen.getByLabelText('Your reflection'),'Read the surrounding pages.');
 await waitFor(()=>expect(remoteNotebook.notes['gitascan:13']).toBe('Read the surrounding pages.'));
 expect(remoteNotebook.bookmarks).toContain('gitascan:13');
 await u.click(screen.getByRole('button',{name:/Search text/}));
 expect(document.querySelector('.extracted-text').textContent).toContain(corpus.passages.find(p=>p.id==='gitascan:13').text.split('\n')[0]);
 expect(screen.getByText(/Unreviewed OCR. Check wording/)).toBeTruthy();
 const src=img.src;
 await u.selectOptions(screen.getByLabelText('Language'),'hi');
 expect(document.documentElement.lang).toBe('hi');expect(img.src).toBe(src);
 expect(screen.getByRole('link',{name:/मूल PDF खोलें/}).href).toContain('/api/books/gitascan/pdf#page=13');
 await u.selectOptions(document.getElementById('ui-language'),'sa');
 expect(document.documentElement.lang).toBe('sa');expect(img.src).toBe(src);
});
test('question carries current page, chosen scope and recent user questions',async()=>{
 const u=user();await openReader();await u.click(screen.getByRole('button',{name:'Ask this book'}));
 const box=screen.getByLabelText('Ask about the page, a teaching, a character…');
 await u.type(box,'Explain this page');await u.click(within(document.getElementById('ask-form')).getByRole('button',{name:'Explore'}));
 expect(await screen.findByText('Matching book pages.')).toBeTruthy();
 const body=JSON.parse(calls.find(x=>x.url==='/api/ask').options.body);
 expect(body).toMatchObject({question:'Explain this page',mode:'strict',language:'en',scope:'book',books:['gitaasitis'],page_id:'gitaasitis:164',selected_text:'',history:[]});
 expect(document.querySelector('.evidence-card').textContent).toContain('PDF 164');
 await u.click(screen.getByRole('button',{name:'Answer settings'}));
 await u.click(screen.getByRole('button',{name:'AI explanation'}));
 await u.selectOptions(screen.getByLabelText('Question scope'),'book');
 await u.type(box,'What does duty mean here?');await u.click(within(document.getElementById('ask-form')).getByRole('button',{name:'Explore'}));
 expect(await screen.findByText('AI explanations are not configured.')).toBeTruthy();
 const followup=JSON.parse(calls.filter(x=>x.url==='/api/ask').at(-1).options.body);
 expect(followup.history).toEqual(['Explain this page']);expect(followup.scope).toBe('book');expect(followup.mode).toBe('explain');
 expect(document.querySelector('.claim')).toBeNull();
});
test('selected source text is sent with the page question and can be cleared',async()=>{
 const u=user();await openReader();await u.click(screen.getByRole('button',{name:'Ask this book'}));await u.click(screen.getByRole('button',{name:/Search text/}));
 const container=document.querySelector('.extracted-text'),node=container.querySelector('span')?.firstChild || container.firstChild;
 const actual=corpus.passages.find(p=>p.id==='gitaasitis:164').text.slice(0,80);
 vi.spyOn(window,'getSelection').mockReturnValue({anchorNode:node,focusNode:node,toString:()=>actual});
 fireEvent.mouseUp(container);
 expect(await screen.findAllByText(/Selected excerpt · 80 characters/)).toHaveLength(2);
 await u.type(screen.getByLabelText('Ask about the page, a teaching, a character…'),'Explain these words');
 await u.click(within(document.getElementById('ask-form')).getByRole('button',{name:'Explore'}));
 await screen.findByText('Matching book pages.');
 expect(JSON.parse(calls.find(x=>x.url==='/api/ask').options.body).selected_text).toBe(actual);
 await u.click(within(document.querySelector('.ask-selection')).getByRole('button',{name:'Clear selection'}));
 expect(document.querySelector('.ask-selection')).toBeNull();
});
test('search citation opens corrected original page and missing verse gives honest feedback',async()=>{
 const u=user();render(<App/>);await screen.findAllByRole('button',{name:/^Begin reading:/});
 await u.click(screen.getByRole('button',{name:'Search the collection'}));
 const dialog=screen.getByRole('dialog');await u.type(within(dialog).getByRole('textbox'),'Gita 2.47');
 await u.click(within(dialog).getByRole('button',{name:'Explore'}));
 await waitFor(()=>expect(dialog.querySelector('.search-result')).toBeTruthy());
 await u.click(dialog.querySelector('.search-result'));await screen.findByRole('button',{name:'Save page'});
 expect(window.location.hash).toBe('#read/gitaasitis/163');expect(dialog.open).toBe(false);
 await u.type(screen.getByLabelText('PDF page / indexed verse'),'99.999');await u.click(screen.getByRole('button',{name:'Go',exact:true}));
 expect(await screen.findByText(/This reference is not indexed in this edition/)).toBeTruthy();
 expect(window.location.hash).toBe('#read/gitaasitis/163');
});
test('recognition exercise compares four actual source page images',async()=>{
 const u=user();remoteNotebook.lastPage='ramayana:59';window.history.replaceState(null,'','/#study');render(<App/>);
 const check=await screen.findByRole('button',{name:'Check answer'});expect(check.disabled).toBe(true);
 expect(document.querySelectorAll('.pdf-quiz-option img')).toHaveLength(4);
 await u.click(screen.getByRole('button',{name:'Option A, PDF page 59'}));await u.click(check);
 expect(await screen.findByText('A match.')).toBeTruthy();expect(document.querySelector('.pdf-quiz-option.correct')).toBeTruthy();
 await u.selectOptions(document.getElementById('practice-book'),'gitascan');
 expect(await screen.findByText('Not enough indexed pages for this exercise.')).toBeTruthy();
});
test('API failures can be retried without leaving a blank reading room',async()=>{
 const u=user();fetch.mockRejectedValue(new Error('Connection unavailable'));render(<App/>);
 expect(await screen.findByText('Connection unavailable')).toBeTruthy();
 fetch.mockImplementation(mockFetch);await u.click(screen.getByRole('button',{name:'Try again'}));
 expect((await screen.findAllByRole('button',{name:/^Begin reading:/}))).toHaveLength(3);
});

test('Gemini failure shows safe diagnostics, preserves citations and prevents duplicate submissions',async()=>{
 const u=user();let finish;
 fetch.mockImplementation((url,options)=>url==='/api/ask'?new Promise(resolve=>{finish=resolve;}):mockFetch(url,options));
 await openReader();
 await u.click(screen.getByRole('button',{name:'Ask this book',exact:true}));
 await u.click(screen.getByRole('button',{name:'Answer settings'}));
 await u.click(screen.getByRole('button',{name:'AI explanation',exact:true}));
 await u.type(screen.getByLabelText('Ask about the page, a teaching, a character…'),'Explain this page');
 const form=document.getElementById('ask-form');
 await u.click(within(form).getByRole('button',{name:'Explore'}));
 expect(await screen.findByText(/Finding relevant passages/)).toBeTruthy();
 expect(within(form).getByRole('button',{name:'Stop'})).toBeTruthy();
 fireEvent.submit(form);expect(fetch.mock.calls.filter(([url])=>url==='/api/ask')).toHaveLength(1);
 finish(await reply({status:'provider_unavailable',provider_error:'service_unavailable',
  provider_http_status:503,provider_code:'service_unavailable',request_stage:'verification',
  api_calls_attempted:3,retry_after_seconds:30,generated:false,claims:[],
  message:'The AI provider is unavailable. Your books remain readable.',
  detail:'Google’s Gemini service is temporarily unavailable. Please try again later.',
  evidence:[corpus.passages.find(p=>p.id==='gitaasitis:164')]},false,503));
 expect(await screen.findByText('AI explanation unavailable')).toBeTruthy();
 expect(screen.getByText('Wait at least 30 seconds before trying again.')).toBeTruthy();
 await u.click(screen.getByText('Diagnostic details'));
 expect(screen.getByText('Gemini HTTP 503 · service_unavailable')).toBeTruthy();
 expect(screen.getByText('Source verification · 3 API call(s)')).toBeTruthy();
 expect(document.querySelector('.claim')).toBeNull();
 expect(document.querySelector('.evidence-card')).toBeTruthy();
 expect(within(form).queryByRole('button',{name:'Stop'})).toBeNull();
 expect(screen.getByLabelText('Ask about the page, a teaching, a character…').disabled).toBe(false);
 await u.click(document.querySelector('.evidence-card'));
 expect(window.location.hash).toBe('#read/gitaasitis/164');
});
test('book notes are escaped and the earlier notebook is preserved separately',async()=>{
 localStorage.setItem('grantha-notebook','earlier notebook');
 localStorage.setItem('grantha-pdf-notebook',JSON.stringify({version:1,notes:{'gitascan:13':'<img src=x onerror=alert(1)>'},bookmarks:[],read:[]}));
 window.history.replaceState(null,'','/#study');render(<App/>);fireEvent.click(await screen.findByRole('button',{name:'Import my earlier notebook'}));fireEvent.click(await screen.findByRole('button',{name:'Notes',exact:true}));
 expect(await screen.findByText('<img src=x onerror=alert(1)>')).toBeTruthy();expect(document.querySelector('.notebook-card img')).toBeNull();
 expect(localStorage.getItem('grantha-notebook')).toBe('earlier notebook');
});

test('signup sends the CSRF token, opens the account and supports logout',async()=>{
 signedIn=false;const u=user();render(<App/>);
 await u.click(await screen.findByRole('button',{name:'Create account',exact:true}));
 await u.type(screen.getByLabelText('Your name'),'Ananya');
 await u.type(screen.getByLabelText('Email address'),'ananya@example.test');
 await u.type(screen.getByLabelText('Password',{exact:true}),'a-long-test-password');
 await u.type(screen.getByLabelText('Confirm password'),'a-long-test-password');
 await u.click(screen.getByRole('button',{name:'Create my account'}));
 await screen.findAllByRole('button',{name:/^Begin reading:/});
 const request=calls.find(x=>x.url==='/api/auth/signup');
 expect(request.options.headers['X-CSRF-Token']).toBe('test-csrf');
 expect(JSON.parse(request.options.body)).toEqual({name:'Ananya',email:'ananya@example.test',password:'a-long-test-password'});
 await u.click(screen.getByRole('button',{name:'My account'}));
 await u.click(await screen.findByRole('button',{name:'Sign out',exact:true}));
 expect(await screen.findByRole('heading',{name:'Welcome back.'})).toBeTruthy();
 expect(signedIn).toBe(false);
});

test('failed login stays on the form and a corrected submission can succeed',async()=>{
 signedIn=false;let rejected=false;
 fetch.mockImplementation((url,options)=>{
  if(url==='/api/auth/login'&&!rejected){rejected=true;return reply({error:'Email or password is incorrect.'},false,401);}
  return mockFetch(url,options);
 });
 const u=user();render(<App/>);await screen.findByRole('heading',{name:'Welcome back.'});
 await u.type(screen.getByLabelText('Email address'),'ananya@example.test');
 await u.type(screen.getByLabelText('Password',{exact:true}),'a-long-test-password');
 await u.click(document.querySelector('.auth-submit'));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent','Email or password is incorrect.');
 expect(screen.getByLabelText('Email address').value).toBe('ananya@example.test');
 await u.click(document.querySelector('.auth-submit'));
 expect((await screen.findAllByRole('button',{name:/^Begin reading:/}))).toHaveLength(3);
});

test('a notebook conflict retains the local draft without overwriting the other device',async()=>{
 const u=user();await openReader('gitascan/13');
 remoteNotebook={...remoteNotebook,notes:{'gitascan:13':'Saved by another device.'}};revision=1;
 await u.click(screen.getByRole('button',{name:'Notes',exact:true}));
 await u.type(screen.getByLabelText('Your reflection'),'My unsaved reflection.');
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('Notebook changed on another device.'));
 expect(screen.getByLabelText('Your reflection').value).toBe('My unsaved reflection.');
 expect(remoteNotebook.notes['gitascan:13']).toBe('Saved by another device.');
 expect(screen.getByRole('button',{name:'Export notebook'})).toBeTruthy();
});

test('native full screen retains the reader element during page navigation',async()=>{
 const u=user();await openReader();const reader=document.querySelector('.reader-workspace');
 Object.defineProperty(document,'fullscreenElement',{configurable:true,writable:true,value:null});
 reader.requestFullscreen=vi.fn(async()=>{document.fullscreenElement=reader;document.dispatchEvent(new Event('fullscreenchange'));});
 document.exitFullscreen=vi.fn(async()=>{document.fullscreenElement=null;document.dispatchEvent(new Event('fullscreenchange'));});
 try{
  await u.click(screen.getByRole('button',{name:'Full screen',exact:true}));
  expect(reader.requestFullscreen).toHaveBeenCalledOnce();
  expect(screen.getByRole('button',{name:'Exit full screen'}).getAttribute('aria-pressed')).toBe('true');
  let resolvePage;
  fetch.mockImplementation((url,options)=>url==='/api/passages/gitaasitis%3A165'?new Promise(resolve=>{resolvePage=resolve;}):mockFetch(url,options));
  await u.click(screen.getByRole('button',{name:'Next',exact:true}));
  await waitFor(()=>expect(resolvePage).toBeTypeOf('function'));
  expect(document.querySelector('.reader-workspace')).toBe(reader);
  expect(document.fullscreenElement).toBe(reader);
  resolvePage(await mockFetch('/api/passages/gitaasitis%3A165'));
  await waitFor(()=>expect(document.querySelector('.pdf-page-image').src).toContain('/pages/165/image'));
  expect(document.querySelector('.reader-workspace')).toBe(reader);
  await u.click(screen.getByRole('button',{name:'Exit full screen'}));
  expect(document.fullscreenElement).toBeNull();
 }finally{delete document.fullscreenElement;delete document.exitFullscreen;}
});

test('expanded reading fallback exits with Escape when native full screen is unavailable',async()=>{
 const u=user();await openReader();const reader=document.querySelector('.reader-workspace');
 reader.requestFullscreen=vi.fn().mockRejectedValue(new Error('Unavailable'));
 await u.click(screen.getByRole('button',{name:'Full screen',exact:true}));
 await waitFor(()=>expect(reader.classList.contains('focus-reader')).toBe(true));
 expect(document.body.style.overflow).toBe('hidden');
 fireEvent.keyDown(document,{key:'Escape'});
 await waitFor(()=>expect(reader.classList.contains('focus-reader')).toBe(false));
 expect(document.body.style.overflow).not.toBe('hidden');
 expect(document.activeElement).toBe(screen.getByRole('button',{name:'Full screen',exact:true}));
});

test('bookmark survives a lost acknowledgement and reader reload',async()=>{
 const u=user();let lost=false;
 fetch.mockImplementation(async(url,options={})=>{const response=await mockFetch(url,options);if(url==='/api/me/notebook'&&options.method==='PUT'&&!lost){lost=true;throw new Error('Connection interrupted after commit');}return response;});
 window.history.replaceState(null,'','/#read/gitascan/13');const first=render(<App/>);
 await u.click(await screen.findByRole('button',{name:'Save page'}));
 await screen.findByText('Bookmark saved to your account.',{},{timeout:4000});
 expect(remoteNotebook.bookmarks).toEqual(['gitascan:13']);
 first.unmount();render(<App/>);
 expect((await screen.findByRole('button',{name:'Saved',exact:true})).getAttribute('aria-pressed')).toBe('true');
 await u.click(within(document.querySelector('.reader-tabs')).getByRole('button',{name:/Saved pages/}));
 expect(screen.getByRole('button',{name:'PDF page 13'})).toBeTruthy();
 await u.click(screen.getByRole('button',{name:'Remove bookmark for page 13'}));
 await waitFor(()=>expect(remoteNotebook.bookmarks).toEqual([]));
},10000);

test('bookmark edits merge with a bookmark added in another tab',async()=>{
 const u=user();await openReader('gitascan/13');remoteNotebook={...remoteNotebook,bookmarks:['gitaasitis:164']};revision++;
 await u.click(screen.getByRole('button',{name:'Save page'}));
 await waitFor(()=>expect(remoteNotebook.bookmarks).toEqual(expect.arrayContaining(['gitascan:13','gitaasitis:164'])));
 expect(screen.queryByRole('alert')).toBeNull();
});

test('home assistant searches all books without requiring an open page',async()=>{
 const u=user();render(<App/>);const box=await screen.findByLabelText('What would you like to understand?');
 await u.type(box,'What does the Gita say about duty?');await u.click(within(document.getElementById('home-ask-form')).getByRole('button',{name:'Explore'}));
 await screen.findByText('Matching book pages.');const body=JSON.parse(calls.find(x=>x.url==='/api/ask').options.body);
 expect(body).toMatchObject({scope:'all',books:null,async:true});expect(body.page_id).toBeUndefined();expect(document.querySelector('.evidence-card')).toBeTruthy();
});

test('asynchronous answer continues when its panel closes and the page changes',async()=>{
 const u=user();let polls=0;
 fetch.mockImplementation((url,options={})=>{
  if(url==='/api/ask')return reply({status:'processing',job_id:'test-job',stage:'generation'});
  if(url==='/api/ask/jobs/test-job')return reply(++polls===1?{status:'processing',job_id:'test-job',stage:'verification'}:{status:'answered',generated:true,claims:[{text:'A checked answer from the requested page.',citation_ids:['gitaasitis:164']}],evidence:[]});
  return mockFetch(url,options);
 });
 await openReader();await u.click(screen.getByRole('button',{name:'Ask this book',exact:true}));
 await u.type(screen.getByLabelText('Ask about the page, a teaching, a character…'),'Explain this page');await u.click(within(document.getElementById('ask-form')).getByRole('button',{name:'Explore'}));
 await u.click(screen.getByRole('button',{name:'Close questions'}));await u.click(screen.getByRole('button',{name:'Next',exact:true}));
 await waitFor(()=>expect(window.location.hash).toBe('#read/gitaasitis/165'));await u.click(screen.getByRole('button',{name:'Ask this book',exact:true}));
 expect(await screen.findByText('A checked answer from the requested page.',{},{timeout:6000})).toBeTruthy();
 expect(fetch.mock.calls.filter(([url])=>url==='/api/ask')).toHaveLength(1);expect(document.querySelector('.user-question').textContent).toContain('PDF 164');
},10000);

test('lost question acknowledgement reconnects without repeating the generation request',async()=>{
 const u=user();let request;
 fetch.mockImplementation((url,options={})=>{
  if(url==='/api/ask'){request=JSON.parse(options.body).request_id;return Promise.reject(new Error('Connection lost'));}
  if(url===`/api/ask/requests/${request}`)return reply({status:'answered',generated:true,claims:[{text:'Recovered the completed answer.',citation_ids:['gitaasitis:164']}],evidence:[]});
  return mockFetch(url,options);
 });
 await openReader();await u.click(screen.getByRole('button',{name:'Ask this book',exact:true}));
 await u.type(screen.getByLabelText('Ask about the page, a teaching, a character…'),'Explain this page');await u.click(within(document.getElementById('ask-form')).getByRole('button',{name:'Explore'}));
 expect(await screen.findByText('Recovered the completed answer.',{},{timeout:4000})).toBeTruthy();expect(fetch.mock.calls.filter(([url])=>url==='/api/ask')).toHaveLength(1);
},10000);

test('stopping a question calls its cancellation endpoint and never displays a draft',async()=>{
 const u=user();let cancelled=false;
 fetch.mockImplementation((url,options={})=>{
  if(url==='/api/ask')return reply({status:'processing',job_id:'cancel-test',stage:'generation'});
  if(url==='/api/ask/jobs/cancel-test/cancel'){cancelled=true;return reply({status:'cancelling'});}
  if(url==='/api/ask/jobs/cancel-test')return reply(cancelled?{status:'cancelled',claims:[],generated:false,message:'Question stopped.'}:{status:'processing',stage:'generation'});
  return mockFetch(url,options);
 });
 await openReader();await u.click(screen.getByRole('button',{name:'Ask this book',exact:true}));
 await u.type(screen.getByLabelText('Ask about the page, a teaching, a character…'),'Explain this page');await u.click(within(document.getElementById('ask-form')).getByRole('button',{name:'Explore'}));
 await u.click(await screen.findByRole('button',{name:'Stop',exact:true}));expect(await screen.findByText('Question stopped.',{},{timeout:4000})).toBeTruthy();expect(cancelled).toBe(true);expect(document.querySelector('.claim')).toBeNull();
},10000);


test('reader panels resize with keys, expand, swap and retain the question draft',async()=>{
 vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({width:1200,height:1000,top:0,left:0,right:1200,bottom:1000});
 const u=user();await openReader();await u.click(screen.getByRole('button',{name:'Ask this book'}));
 const box=screen.getByLabelText('Ask about the page, a teaching, a character…');
 await u.type(box,'Explain this teaching.');
 const divider=screen.getByRole('separator',{name:'Resize book and AI panels'});
 divider.focus();const before=Number(divider.getAttribute('aria-valuenow'));
 await u.keyboard('{ArrowLeft}');
 expect(Number(divider.getAttribute('aria-valuenow'))).toBeLessThan(before);
 expect(window.location.hash).toContain('gitaasitis/164');
 await u.click(screen.getByRole('button',{name:'Expand AI',exact:true}));
 expect(document.getElementById('split-book').hidden).toBe(true);
 expect(box.value).toBe('Explain this teaching.');
 await u.click(screen.getByRole('button',{name:'Expand book',exact:true}));
 expect(document.getElementById('split-ai').hidden).toBe(true);
 await u.click(screen.getByRole('button',{name:'Both panels',exact:true}));
 await u.selectOptions(screen.getByRole('combobox',{name:'Panel layout'}),'vertical');
 expect(screen.getByRole('separator').getAttribute('aria-orientation')).toBe('horizontal');
 await u.click(screen.getByRole('button',{name:/Swap panels/}));
 expect(document.querySelector('.split-surface').dataset.reversed).toBe('true');
 expect(box.value).toBe('Explain this teaching.');
 const saved=JSON.parse(localStorage.getItem('grantha-reader-layout-v1'));
 expect(saved.axis).toBe('vertical');expect(saved.reversed).toBe(true);
 await u.click(screen.getByRole('button',{name:'Reset layout'}));
 expect(screen.getByRole('separator').getAttribute('aria-orientation')).toBe('vertical');
 expect(document.querySelector('.split-surface').dataset.reversed).toBe('false');
});

test('saved reader layout is restored on opening a book',async()=>{
 localStorage.setItem('grantha-reader-layout-v1',JSON.stringify({axis:'vertical',reversed:true,horizontal:55,vertical:60}));
 const u=user();await openReader();await u.click(screen.getByRole('button',{name:'Ask this book'}));
 expect(screen.getByRole('combobox',{name:'Panel layout'}).value).toBe('vertical');
 expect(document.querySelector('.split-surface').dataset.reversed).toBe('true');
 expect(screen.queryByRole('separator')).toBeNull();
 expect(document.getElementById('split-book').hidden).toBe(true);
 expect(document.getElementById('split-ai').hidden).toBe(false);
});


test('reading theme reaches the root and stays active on the collection',async()=>{
 const u=user();await openReader();await u.selectOptions(screen.getByRole('combobox',{name:'Reading theme'}),'night');
 expect(document.documentElement.dataset.readingTheme).toBe('night');
 await u.click(within(screen.getByRole('navigation')).getByRole('button',{name:'Library',exact:true}));
 expect(document.documentElement.dataset.readingTheme).toBe('night');
 expect(localStorage.getItem('grantha-reading-theme')).toBe('night');
});
test('a narrow reader switches to full-height book or answer views',async()=>{
 vi.spyOn(HTMLElement.prototype,'getBoundingClientRect').mockReturnValue({width:370,height:600,top:0,left:0,right:370,bottom:600});
 const u=user();await openReader();await u.click(screen.getByRole('button',{name:'Ask this book'}));
 expect(screen.queryByRole('separator')).toBeNull();expect(document.getElementById('split-book').hidden).toBe(true);
 await u.click(screen.getByRole('button',{name:'Expand book'}));expect(document.getElementById('split-ai').hidden).toBe(true);
});


test('zoom buttons and keys work both ways and retain scale through fullscreen',async()=>{
 const u=user();await openReader();const zoom=screen.getByRole('combobox',{name:'Zoom'});expect(zoom.value).toBe('page');
 await u.click(screen.getByRole('button',{name:'Zoom in',exact:true}));expect(zoom.value).toBe('125');
 await u.click(screen.getByRole('button',{name:'Zoom out',exact:true}));expect(zoom.value).toBe('100');
 await u.selectOptions(zoom,'400');expect(screen.getByRole('button',{name:'Zoom in',exact:true}).disabled).toBe(true);
 const frame=screen.getByLabelText('Book page. Plus and minus zoom; zero fits the page.');frame.focus();fireEvent.keyDown(frame,{key:'-'});expect(zoom.value).toBe('300');
 await u.click(screen.getByRole('button',{name:'Full screen',exact:true}));expect(zoom.value).toBe('300');
 frame.focus();fireEvent.keyDown(frame,{key:'0'});expect(zoom.value).toBe('page');
 await u.selectOptions(zoom,'25');expect(screen.getByRole('button',{name:'Zoom out',exact:true}).disabled).toBe(true);
});
test('provider failure offers a separate context-free connection check',async()=>{
 fetch.mockImplementation((url,options)=>{
  if(url==='/api/ask')return reply({status:'provider_unavailable',provider_error:'network_timeout',generated:false,claims:[],evidence:[],message:'Unavailable',response_mode:'generate_content_stream',api_calls_attempted:1,request_attempts:[{number:1,phase:'connecting_or_waiting_for_headers',outcome:'network_timeout',elapsed_seconds:180}]});
  if(url==='/api/ai/check')return reply({result:'ok',api_calls_attempted:1});return mockFetch(url,options);
 });
 const u=user();await openReader();await u.click(screen.getByRole('button',{name:'Ask this book',exact:true}));
 await u.type(screen.getByPlaceholderText('What would you like to understand?'),'Explain duty');await u.click(screen.getByRole('button',{name:'Explore',exact:true}));
 await u.click(await screen.findByRole('button',{name:'Test Gemini connection'}));expect(await screen.findByText('Gemini answered the small connection check.')).toBeTruthy();
 expect(fetch.mock.calls.filter(([url])=>url==='/api/ai/check')).toHaveLength(1);
});
