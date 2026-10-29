import {createContext, useContext} from 'react';

export const AppContext = createContext(null);
export const useApp = () => useContext(AppContext);
export function readLocal(key, fallback=null) {
  try {return localStorage.getItem(key) ?? fallback;} catch {return fallback;}
}
export const lastPassage = () => readLocal('grantha-pdf-last', 'gitascan:13');
export const navigate = path => {window.location.hash = path;};
export const readPassage = id => navigate('read/'+id.replace(':','/'));
export function parseRoute(hash) {
  let parts;
  try {parts=decodeURIComponent(hash.replace(/^#/, '')).split('/');} catch {return {page:'library'};}
  if (parts[0] === 'read') return {page:'reader', id:(parts[1] || 'gitascan')+':'+(parts[2] || '13')};
  if(parts[0]==='study')return {page:'study',tab:parts[1]};
  return {page:['study', 'sources','account'].includes(parts[0]) ? parts[0] : 'library'};
}
