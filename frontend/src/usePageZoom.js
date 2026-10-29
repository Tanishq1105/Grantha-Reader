import {useLayoutEffect,useRef,useState} from 'react';
export const ZOOM_LEVELS=[25,50,75,100,125,150,175,200,250,300,400];
export default function usePageZoom(frame,source,active,zoom,setZoom){
 const [bounds,setBounds]=useState({width:1,height:1}),[natural,setNatural]=useState({width:900,height:1300});
 const previous=useRef(null),drag=useRef(null);
 useLayoutEffect(()=>{
  const node=frame.current;if(!node||!active)return;
  const measure=()=>{const style=getComputedStyle(node),width=Math.max(1,node.clientWidth-parseFloat(style.paddingLeft||0)-parseFloat(style.paddingRight||0)),height=Math.max(1,node.clientHeight-parseFloat(style.paddingTop||0)-parseFloat(style.paddingBottom||0));setBounds(old=>old.width===width&&old.height===height?old:{width,height});};
  measure();const observer=typeof ResizeObserver==='function'?new ResizeObserver(measure):null;
  observer?.observe(node);window.addEventListener('resize',measure);return()=>{observer?.disconnect();window.removeEventListener('resize',measure);};
 },[frame,source,active]);
 const fit=Math.min(bounds.width/natural.width,bounds.height/natural.height),baseWidth=natural.width*fit,baseHeight=natural.height*fit;
 const percent=zoom==='page'?100:zoom==='width'?Math.round(bounds.width/baseWidth*100):Number(zoom),factor=zoom==='width'?bounds.width/baseWidth:percent/100;
 const width=Math.max(1,baseWidth*factor),height=Math.max(1,baseHeight*factor),stageWidth=Math.max(bounds.width,width),stageHeight=Math.max(bounds.height,height);
 useLayoutEffect(()=>{
  const node=frame.current;if(!node||!active)return;const old=previous.current;
  if(old&&old.source===source){const x=(node.scrollLeft+old.bounds.width/2-(old.stageWidth-old.width)/2)/old.width,y=(node.scrollTop+old.bounds.height/2-(old.stageHeight-old.height)/2)/old.height;node.scrollLeft=Math.max(0,(stageWidth-width)/2+x*width-bounds.width/2);node.scrollTop=Math.max(0,(stageHeight-height)/2+y*height-bounds.height/2);}
  else{node.scrollLeft=0;node.scrollTop=0;}
  previous.current={source,width,height,stageWidth,stageHeight,bounds};
 },[source,active,width,height,stageWidth,stageHeight,bounds,frame]);
 function step(direction){const levels=direction>0?ZOOM_LEVELS:ZOOM_LEVELS.toReversed(),next=levels.find(n=>direction>0?n>percent:n<percent);setZoom(String(next??(direction>0?400:25)));}
 function imageLoaded(event){const image=event.currentTarget;if(image.naturalWidth&&image.naturalHeight)setNatural({width:image.naturalWidth,height:image.naturalHeight});}
 const canPan=width>bounds.width+1||height>bounds.height+1;
 const handlers={
  onPointerDown:event=>{if(!canPan||event.pointerType!=='mouse'||event.button!==0||event.target.closest('button,a,input,select,textarea,summary'))return;const node=frame.current;node.focus({preventScroll:true});drag.current={x:event.clientX,y:event.clientY,left:node.scrollLeft,top:node.scrollTop};node.setPointerCapture?.(event.pointerId);event.preventDefault();},
  onPointerMove:event=>{if(!drag.current)return;const node=frame.current;node.scrollLeft=drag.current.left+drag.current.x-event.clientX;node.scrollTop=drag.current.top+drag.current.y-event.clientY;},
  onPointerUp:event=>{drag.current=null;if(frame.current?.hasPointerCapture?.(event.pointerId))frame.current.releasePointerCapture(event.pointerId);},onPointerCancel:()=>{drag.current=null;}
 };
 return {percent,step,imageLoaded,canPan,handlers,stageStyle:{width:stageWidth,height:stageHeight},imageStyle:{width,height,maxWidth:'none',maxHeight:'none'}};
}
