import pytest,pymupdf
from backend.db import ROOT
from backend.devanagari import DevanagariDecoder
from backend.pdf_extract import archive_text
from backend import grounding,providers
@pytest.mark.parametrize('volume,pages',[(1,2256),(2,2580),(3,2343),(4,3237),(5,2450),(6,2566)])
def test_mahabharata_source_text(app,volume,pages):
 s=app.extensions['store'];bid=f'mahabharata{volume}';assert len(s.by_book[bid])==pages
 p=s.by_id[f'{bid}:2'];assert 'श्रीमन्महर्षि वेदव्यासप्रणीत' in p['text'];assert p['unresolved_glyphs']==0 and p['extraction']=='glyph_decoded'
 for t in next(b for b in s.books if b['id']==bid)['toc'][1:]:assert 'प्रथमोऽध्यायः' in s.by_id[f"{bid}:{t['page']}"]['text']
def test_i_repha_and_anusvara():
 with pymupdf.open(ROOT/'data/pdfs/mahabharata1.pdf') as d:
  dec=DevanagariDecoder(d)
  for prefix,expected in [(585,'र्कि'),(573,'किं'),(597,'र्किं')]:assert dec(chr(prefix)+'क'+chr(606),'NotoSansDevanagari')==expected
  assert dec.unresolved==0
def test_unresolved_text_is_not_sent_to_gemini(app,monkeypatch):
 p=next(p for p in app.extensions['store'].passages if p.get('unresolved_glyphs'))
 monkeypatch.setattr(providers,'complete_json',lambda *a:pytest.fail('Unresolved page reached model'))
 assert grounding.explain('Explain this','hi',[p]) is None
@pytest.mark.parametrize('bid',['upanishads1','upanishads2','rigveda1','rigveda2','samaveda','yajurveda','atharvaveda1','atharvaveda2'])
def test_historical_edition_and_original_page(app,client,bid):
 b=next(b for b in app.extensions['store'].books if b['id']==bid);p=app.extensions['store'].by_id[f"{bid}:{b['start_page']}"]
 assert b['languages']==['en'] and b['translator'] and b['publication_year']<1920 and b['catalog_url'].startswith('https://archive.org/')
 assert p['extraction']=='archive_ocr' and p['ocr_confidence'] is None
 with pymupdf.open(ROOT/'data/pdfs'/b['stored_filename']) as d:assert archive_text(d[p['page']-1])['text']==p['text']
 assert client.get(p['page_url']+'?width=800').data.startswith(b'\x89PNG')
 r=client.post('/api/ask',json={'question':'Explain this page','books':[bid],'scope':'page','page_id':p['id'],'mode':'strict'}).json;assert r['status']=='sources_found' and r['evidence'][0]['id']==p['id']
def test_hindi_search_and_no_invented_references(client):
 r=client.get('/api/search',query_string={'q':'युधिष्ठिर','book':'mahabharata1'}).json;assert r['results'] and all(x['passage']['book_id']=='mahabharata1' for x in r['results'])
 r=client.get('/api/search',query_string={'q':'1.1','book':'upanishads1'}).json;assert r['method']=='exact' and not r['results']
