// Rebase this tab's edits without discarding another tab's bookmarks or notes.
export function mergeNotebook(base,local,remote){
 const mergeSet=key=>{const before=new Set(base[key]),after=new Set(local[key]),result=new Set(remote[key]);for(const id of before)if(!after.has(id))result.delete(id);for(const id of after)if(!before.has(id))result.add(id);return [...result];};
 const notes={...remote.notes};
 for(const id of new Set([...Object.keys(base.notes),...Object.keys(local.notes)])){
  if(local.notes[id]===base.notes[id])continue;
  if(remote.notes[id]!==base.notes[id]&&remote.notes[id]!==local.notes[id]){const e=new Error('Notebook changed on another device. The same note was edited in both places; export your draft before reloading.');e.code='notebook_conflict';throw e;}
  if(Object.hasOwn(local.notes,id))notes[id]=local.notes[id];else delete notes[id];
 }
 return {version:1,notes,bookmarks:mergeSet('bookmarks'),read:mergeSet('read'),lastPage:local.lastPage!==base.lastPage?local.lastPage:remote.lastPage};
}
