import test from 'node:test';
import assert from 'node:assert/strict';
import {escapeHTML, safeURL, normalizeRef, validNotebook, emptyNotebook} from '../frontend/lib.js';

test('text and URLs cannot inject markup or JavaScript',()=>{
  assert.equal(escapeHTML('<script>"x"</script>'),'&lt;script&gt;&quot;x&quot;&lt;/script&gt;');
  assert.equal(safeURL('javascript:alert(1)'),'#');
  assert.equal(safeURL('https://example.com/book.pdf#page=164'),'https://example.com/book.pdf#page=164');
});
test('Devanagari reference digits are normalized without changing verse structure',()=>{
  assert.equal(normalizeRef(' २:४७ '),'2.47');
  assert.equal(normalizeRef('१.१.३'),'1.1.3');
});
test('notebook import checks identity and rejects untrusted structures',()=>{
  assert.deepEqual(validNotebook(emptyNotebook(),['gitaasitis']),emptyNotebook());
  const value={version:1,notes:{'gitaasitis:164':'A thought'},bookmarks:['gitaasitis:164','gitaasitis:164'],read:[]};
  assert.equal(validNotebook(value,['gitaasitis']).bookmarks.length,1);
  assert.throws(()=>validNotebook({...value,bookmarks:['<script>']},['gitaasitis']));
  assert.throws(()=>validNotebook({...value,notes:JSON.parse('{"__proto__":"bad"}')},['gitaasitis']));
  assert.throws(()=>validNotebook({...value,notes:{'gitaasitis:164':null}},['gitaasitis']));
});
