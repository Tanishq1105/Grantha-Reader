import React from 'react';
import {safeURL} from '../lib.js';

const shapes = {
  sidebar: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></>,
  text: <path d="M4 5h16M12 5v15M8 20h8"/>,
  refresh: <path d="M20 7a9 9 0 1 0 1 9M20 3v5h-5"/>,
  new: <path d="M12 4v16M4 12h16"/>,
  stop: <rect x="6" y="6" width="12" height="12" rx="1"/>,
  expand: <path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>,
  minimize: <path d="M3 8h5V3m8 0v5h5M8 21v-5H3m13 5v-5h5"/>,
  book: <path d="M12 6c-3-2-6-2-9-1v14c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1Zm0 0v14"/>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  save: <path d="M6 3h12v18l-6-4-6 4z"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  leaf: <path d="M20 3C7 3 2 8 5 15s15 7 15-12ZM5 20 16 9"/>,
  link: <path d="m10 13 4-4m-6 7-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2-2 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0" transform="translate(1 0)"/>,
  close: <path d="m6 6 12 12M18 6 6 18"/>,
  pen: <path d="m15 4 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14z"/>,
  library: <path d="M4 4h4v16H4zm7 0h4v16h-4zm7 0 4 15-3 1-4-15"/>,
  sparkle: <path d="m12 3 2.3 6.7L21 12l-6.7 2.3L12 21l-2.3-6.7L3 12l6.7-2.3z"/>,
  copy: <><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V3H3v13h5"/></>,
};
export function Icon({name='book', className=''}) {
  return <svg className={'icon '+className} aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{shapes[name] || shapes.book}</svg>;
}
export function ExternalLink({href, children, ...props}) {
  return <a href={safeURL(href)} target="_blank" rel="noopener noreferrer" {...props}>{children}</a>;
}
export function Multiline({text}) {
  return String(text || '').split('\n').map((line, i) => <React.Fragment key={i}>{i > 0 && <br/>}{line}</React.Fragment>);
}
export function EmptyState({title, children}) {
  return <div className="empty-state">{title && <h2>{title}</h2>}{children}</div>;
}
