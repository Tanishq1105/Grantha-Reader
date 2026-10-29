import {useState} from 'react';
import {api} from './api.js';
import {Icon} from './components.jsx';

const copy={
 en:{login:'Sign in',signup:'Create account',welcome:'Welcome back.',start:'Begin your study.',intro:'Your books, reflections and reading progress, together in one place.',name:'Your name',email:'Email address',password:'Password',confirm:'Confirm password',hint:'At least 12 characters',button:'Create my account',switch:'New to Grantha?',already:'Already have an account?',saving:'Please wait…',mismatch:'The passwords do not match.'},
 hi:{login:'लॉग इन',signup:'खाता बनाएँ',welcome:'फिर से स्वागत है।',start:'अध्ययन शुरू करें।',intro:'आपकी पुस्तकें, टिप्पणियाँ और पढ़ने की प्रगति, एक जगह।',name:'आपका नाम',email:'ईमेल पता',password:'पासवर्ड',confirm:'पासवर्ड फिर लिखें',hint:'कम से कम 12 अक्षर',button:'मेरा खाता बनाएँ',switch:'पहली बार आए हैं?',already:'पहले से खाता है?',saving:'कृपया प्रतीक्षा करें…',mismatch:'दोनों पासवर्ड समान नहीं हैं।'},
 sa:{login:'प्रविशतु',signup:'खातं रचयतु',welcome:'पुनः स्वागतम्।',start:'स्वाध्यायम् आरभताम्।',intro:'ग्रन्थाः, टिप्पण्यः, पठनप्रगतिश्च एकत्र।',name:'नाम',email:'ईमेल',password:'गुप्तशब्दः',confirm:'गुप्तशब्दं पुनर्लिखतु',hint:'न्यूनतमं १२ वर्णाः',button:'खातं रचयतु',switch:'नूतनः पाठकः?',already:'खातम् अस्ति?',saving:'प्रतीक्षताम्…',mismatch:'गुप्तशब्दौ समानौ न स्तः।'}
};

export default function Auth({lang,setLang,onAuth,signupEnabled=true}){
 const [signup,setSignup]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const c=copy[lang] || copy.en;
 async function submit(event){
  event.preventDefault();if(busy)return;setError('');
  const data=Object.fromEntries(new FormData(event.currentTarget));
  if(signup && data.password!==data.confirm){setError(c.mismatch);return;}
  delete data.confirm;setBusy(true);
  try{const result=await api(signup?'/auth/signup':'/auth/login',{method:'POST',body:JSON.stringify(data)});onAuth(result.user);}
  catch(e){setError(e.message);}finally{setBusy(false);}
 }
 return <div className="auth-page">
  <header className="auth-header"><a className="brand" href="#library"><span className="brand-mark">ग</span><span>GRANTHA<small>THE READING ROOM</small></span></a><label><span className="sr-only">Language</span><select value={lang} onChange={e=>setLang(e.target.value)}><option value="en">English</option><option value="hi">हिन्दी</option><option value="sa">संस्कृतम्</option></select></label></header>
  <div className="auth-layout"><section className="auth-story"><p className="eyebrow">READ · REFLECT · RETURN</p><h1>A quiet place for<br/><em>timeless questions.</em></h1><p>Explore the Gītā, Rāmāyaṇa, Mahābhārata, Upanishads and Vedas. Read the original book pages and follow every answer back to its source.</p><div className="auth-book-art" aria-hidden="true"><span>स्वाध्याय</span><small>THE READING ROOM</small></div><div className="auth-benefits"><span><Icon name="book"/> Original book pages</span><span><Icon name="save"/> Your saved place</span><span><Icon name="pen"/> Personal reflections</span></div></section>
  <section className="auth-card" aria-labelledby="auth-title"><p className="eyebrow">YOUR PERSONAL READING ROOM</p><h2 id="auth-title">{signup?c.start:c.welcome}</h2><p>{c.intro}</p>
   <div className="auth-tabs"><button type="button" aria-pressed={!signup} onClick={()=>{setSignup(false);setError('');}}>{c.login}</button>{signupEnabled&&<button type="button" aria-pressed={signup} onClick={()=>{setSignup(true);setError('');}}>{c.signup}</button>}</div>
   <form key={signup?'signup':'login'} onSubmit={submit}>
    {signup&&<label htmlFor="auth-name">{c.name}<input id="auth-name" name="name" autoComplete="name" maxLength="80" required/></label>}
    <label htmlFor="auth-email">{c.email}<input id="auth-email" name="email" type="email" autoComplete="username" maxLength="254" required/></label>
    <label htmlFor="auth-password">{c.password}<input id="auth-password" name="password" aria-describedby={signup?'password-hint':undefined} type="password" autoComplete={signup?'new-password':'current-password'} minLength={signup?12:1} maxLength="128" required/></label>{signup&&<small id="password-hint" className="quiet">{c.hint}</small>}
    {signup&&<label htmlFor="auth-confirm">{c.confirm}<input id="auth-confirm" name="confirm" type="password" autoComplete="new-password" minLength="12" maxLength="128" required/></label>}
    {error&&<p className="form-error" role="alert">{error}</p>}
    <button className="primary auth-submit" disabled={busy}>{busy?c.saving:signup?c.button:c.login}<Icon name="arrow"/></button>
   </form><p className="auth-footnote">Your notes and reading progress are saved to your account on this app.</p>
  </section></div>
 </div>;
}
