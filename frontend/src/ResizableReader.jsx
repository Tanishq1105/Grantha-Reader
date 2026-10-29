import {Children, useEffect, useRef, useState} from 'react';
import {useApp, readLocal} from './state.jsx';

const KEY = 'grantha-reader-layout-v1';
const defaults = {axis:'horizontal', reversed:false, horizontal:56, vertical:50};
const copy = {
 en:{layout:'Panel layout', side:'Side by side', stack:'Stacked', both:'Both panels', book:'Expand book', ai:'Expand AI', swap:'Swap panels', reset:'Reset layout', resize:'Resize book and AI panels', hint:'Drag the divider. Use arrow keys when focused; double-click to reset.', narrow:'Switch between book and answer'},
 hi:{layout:'पैनल व्यवस्था', side:'साथ-साथ', stack:'ऊपर-नीचे', both:'दोनों पैनल', book:'पुस्तक बढ़ाएँ', ai:'AI बढ़ाएँ', swap:'स्थान बदलें', reset:'व्यवस्था रीसेट करें', resize:'पुस्तक और AI का आकार बदलें', hint:'विभाजक खींचें या तीर कुंजियाँ दबाएँ। रीसेट के लिए दो बार क्लिक करें।', narrow:'पुस्तक या उत्तर चुनें'},
 sa:{layout:'पटलविन्यासः', side:'पार्श्वयोः', stack:'उपरि अधः', both:'उभे पटले', book:'ग्रन्थं विस्तारयतु', ai:'AI विस्तारयतु', swap:'स्थानं परिवर्तयतु', reset:'विन्यासं पुनः स्थापयतु', resize:'ग्रन्थस्य AI इत्यस्य च आकारं परिवर्तयतु', hint:'विभाजकं कर्षतु अथवा बाणकुञ्जीः नुदतु।', narrow:'ग्रन्थम् अथवा उत्तरं चिनोतु'},
};
function initialLayout(){
 try{
  const value=JSON.parse(readLocal(KEY,'null'));
  if(!value || !['horizontal','vertical'].includes(value.axis))return defaults;
  return {axis:value.axis,reversed:value.reversed===true,
   horizontal:Number.isFinite(value.horizontal)?Math.max(20,Math.min(80,value.horizontal)):56,
   vertical:Number.isFinite(value.vertical)?Math.max(20,Math.min(80,value.vertical)):50};
 }catch{return defaults;}
}

export default function ResizableReader({children, askOpen, focus, onFocus}){
 const {lang}=useApp(), l=copy[lang]||copy.en;
 const [layout,setLayout]=useState(initialLayout),[size,setSize]=useState({width:1024,height:600}),[dragging,setDragging]=useState(false);
 const surface=useRef(null),drag=useRef(null);
 const [book,questions]=Children.toArray(children);
 const narrow=size.width<820, axis=layout.axis;
 const tabbed=narrow||(axis==='vertical'&&size.height<820);
 const available=Math.max(1,(axis==='horizontal'?size.width:size.height)-14);
 const minimum=Math.min(42,(axis==='horizontal'?360:380)/available*100);
 const ratio=Math.max(minimum,Math.min(100-minimum,layout[axis]));
 const expanded=askOpen?(tabbed&&focus==='both'?'ai':focus):'book', split=askOpen&&expanded==='both';
 useEffect(()=>{
  const element=surface.current;
  const measure=()=>{const r=element.getBoundingClientRect();if(r.width&&r.height)setSize({width:r.width,height:r.height});};
  measure();window.addEventListener('resize',measure);
  const observer=typeof ResizeObserver==='function'?new ResizeObserver(measure):null;
  observer?.observe(element);
  return()=>{observer?.disconnect();window.removeEventListener('resize',measure);};
 },[]);
 useEffect(()=>{try{localStorage.setItem(KEY,JSON.stringify(layout));}catch{}},[layout]);
 useEffect(()=>{drag.current=null;setDragging(false);},[axis,expanded,askOpen]);
 function resize(value){setLayout(old=>({...old,[axis]:Math.max(minimum,Math.min(100-minimum,value))}));}
 function start(event){
  if(event.button!==0)return;
  event.preventDefault();event.currentTarget.focus();
  event.currentTarget.setPointerCapture?.(event.pointerId);
  drag.current={pointerId:event.pointerId,position:axis==='horizontal'?event.clientX:event.clientY,ratio};setDragging(true);
 }
 function move(event){
  const current=drag.current;if(!current||current.pointerId!==event.pointerId)return;
  const position=axis==='horizontal'?event.clientX:event.clientY;
  resize(current.ratio+(position-current.position)/available*100);
 }
 function stop(event){
  if(drag.current?.pointerId!==event.pointerId)return;
  drag.current=null;setDragging(false);
  if(event.currentTarget.hasPointerCapture?.(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);
 }
 function key(event){
  const decrease=axis==='horizontal'?'ArrowLeft':'ArrowUp',increase=axis==='horizontal'?'ArrowRight':'ArrowDown';
  if(![decrease,increase,'Home','End'].includes(event.key))return;
  event.preventDefault();event.stopPropagation();
  resize(event.key==='Home'?minimum:event.key==='End'?100-minimum:ratio+(event.key===increase?1:-1)*(event.shiftKey?10:2));
 }
 const tracks=`minmax(0,${ratio}fr) 14px minmax(0,${100-ratio}fr)`;
 const style=split?(axis==='horizontal'?{gridTemplateColumns:tracks,gridTemplateRows:'minmax(0,1fr)'}:{gridTemplateRows:tracks,gridTemplateColumns:'minmax(0,1fr)'}):undefined;
 return <section className="reader-split" aria-label={l.layout}>
  {askOpen&&<div className="split-controls">
   <div className="split-focus-controls" aria-label={l.layout}>
    {[['both',l.both],['book',l.book],['ai',l.ai]].filter(([value])=>!tabbed||value!=='both').map(([value,label])=><button key={value} aria-pressed={expanded===value} onClick={()=>onFocus(value)}>{label}</button>)}
   </div>
   <label className={narrow?'split-setting-hidden':''}><span className="sr-only">{l.layout}</span><select aria-label={l.layout} value={layout.axis} onChange={e=>{setLayout(old=>({...old,axis:e.target.value}));onFocus('both');}}><option value="horizontal">{l.side}</option><option value="vertical">{l.stack}</option></select></label>
   <button className={'split-swap '+(tabbed?'split-setting-hidden':'')} onClick={()=>{setLayout(old=>({...old,reversed:!old.reversed}));onFocus('both');}} title={l.swap}>{axis==='horizontal'?'⇄':'⇅'} <span>{l.swap}</span></button>
   <button onClick={()=>{setLayout({...defaults});onFocus('both');}}>{l.reset}</button>
   {tabbed&&<span className="split-narrow-hint">{l.narrow}</span>}
  </div>}
  <div ref={surface} className={`split-surface ${split?'is-split':'is-expanded'} ${dragging?'is-dragging':''}`} data-axis={axis} data-reversed={layout.reversed} style={style}>
   <div id="split-book" className="split-pane split-book" hidden={expanded==='ai'} style={{order:layout.reversed?2:0}}>{book}</div>
   {split&&<div className="split-handle" role="separator" tabIndex="0" aria-label={l.resize} aria-controls={layout.reversed?'split-ai':'split-book'} aria-orientation={axis==='horizontal'?'vertical':'horizontal'} aria-valuemin={Math.round(minimum)} aria-valuemax={Math.round(100-minimum)} aria-valuenow={Math.round(ratio)} title={l.hint} style={{order:1}} onPointerDown={start} onPointerMove={move} onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={()=>{drag.current=null;setDragging(false);}} onKeyDown={key} onDoubleClick={()=>resize(axis==='horizontal'?56:50)}><span/></div>}
   {askOpen&&<div id="split-ai" className="split-pane split-ai" hidden={expanded==='book'} style={{order:layout.reversed?0:2}}>{questions}</div>}
  </div>
 </section>;
}
