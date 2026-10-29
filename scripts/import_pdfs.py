"""Index the supplied PDF editions, with resumable OCR and page citations.

python scripts/import_pdfs.py --tessdata /path/to/tessdata --workers 4
Original PDFs are never rewritten. No website text or generated text is imported.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import hashlib
import json
import re
import sys
from datetime import datetime,timezone
import pymupdf
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.pdf_extract import native_text,ocr_text,archive_text
from backend.devanagari import DevanagariDecoder

def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temporary.replace(path)

def ocr_one(job):
    file,index,tessdata,cache=job
    with pymupdf.open(file) as doc:result=ocr_text(doc[index],tessdata)
    atomic_json(Path(cache),result)
    return index,result

def outlines(book,doc):
    if book.get('toc_override'):return book['toc_override']
    items=[]
    for level,title,page in doc.get_toc():
        if not 1<=page<=len(doc) or re.fullmatch(r'0*\d+',title):continue
        items.append({'level':level,'title':title,'page':page})
    return items

def references(book,toc):
    aliases={}
    if book['id']=='gitaasitis':
        for item in toc:
            m=re.fullmatch(r'Texts?\s+(\d+)\.(\d+)(?:\s*[-–]\s*(\d+))?',item['title'],re.I)
            if m:
                chapter,start,end=int(m[1]),int(m[2]),int(m[3] or m[2])
                for verse in range(start,end+1):aliases[f'{chapter}.{verse}']=item['page']
    elif book['id']=='ramayana':
        kanda=None
        for item in toc:
            m=re.match(r'Book\s+(\d+)\b',item['title'])
            if m:kanda=int(m[1])
            m=re.match(r'^(\d+)\s+',item['title'])
            if m and item['level']>1 and kanda:aliases[f'{kanda}.{int(m[1])}']=item['page']
    return aliases

def roman(value):
    values={'I':1,'V':5,'X':10,'L':50,'C':100,'D':500,'M':1000}
    return sum(-values[x] if i+1<len(value) and values[x]<values[value[i+1]] else values[x] for i,x in enumerate(value))

def verified_anchors(book,toc,rows):
    """Match reference anchors to actual printed headings, not PDF bookmarks.

    This verifies heading/page association only, not scholarly text accuracy.
    Excerpt offsets exclude preceding/following verses on boundary pages.
    """
    expected=references(book,toc);marks=[];chapter=None;aliases={};spans={};boundaries={}
    if book['id']=='gitaasitis':
        major={int(m[1]):item for item in toc if (m:=re.match(r'Ch\s+(\d+)\b',item['title']))}
        front=[x for x in toc if x['page']<42]
        fresh=list(front)
        for index,row in sorted(rows.items()):
            text=row['text'];m=re.search(r'\bCHAPTER\s+(\d+)\b',text)
            if m:
                chapter=int(m[1]);fresh.append({**major[chapter],'page':index+1,'chapter':chapter})
                boundaries[chapter]={'page':index+1,'offset':text.rfind('\n',0,m.start())+1}
            if chapter is None:continue
            for m in re.finditer(r'(?:^|\n)\s*TEXTS?\s+(\d+)(?:\s*[-–—]\s*(\d+))?\b',text):
                start,end=int(m[1]),int(m[2] or m[1]);refs=[f'{chapter}.{n}' for n in range(start,end+1)]
                if any(r in aliases for r in refs):raise ValueError('Duplicate printed verse heading')
                for ref in refs:aliases[ref]=index+1
                marks.append({'page':index+1,'offset':m.start(),'refs':refs})
                label='Text '+refs[0]+(f'–{end}' if end!=start else '')
                fresh.append({'level':2,'title':label,'page':index+1,'reference':refs[0]})
        if set(aliases)!=set(expected):raise ValueError('Printed Gita reference coverage differs from outline; review before importing.')
        toc=fresh
    elif book['id']=='ramayana':
        major=[(int(m[1]),item['page']) for item in toc if (m:=re.match(r'Book\s+(\d+)\b',item['title']))]
        boundaries={k:{'page':page,'offset':0} for k,page in major}
        for index,row in sorted(rows.items()):
            kanda=next((k for k,p in reversed(major) if p<=index+1),None)
            if kanda is None:continue
            for m in re.finditer(r'(?:^|\n)\s*Canto\s+([IVXLCDM]+)\b',row['text']):
                ref=f'{kanda}.{roman(m[1])}'
                override=book.get('heading_overrides',{}).get(str(index+1))
                if override and m[1]==override['printed']:ref=override['reference']
                if ref in expected and ref not in aliases:
                    aliases[ref]=index+1;marks.append({'page':index+1,'offset':m.start(),'refs':[ref]})
        if set(aliases)!=set(expected):raise ValueError('Printed Ramayana canto coverage differs from outline; review before importing.')
        kanda=None
        for item in toc:
            m=re.match(r'Book\s+(\d+)\b',item['title'])
            if m:kanda=int(m[1])
            m=re.match(r'^(\d+)\s+',item['title'])
            if item['level']>1 and m and kanda:item['page']=aliases[f'{kanda}.{int(m[1])}']
    else:return toc,{},{}
    marks.sort(key=lambda x:(x['page'],x['offset']))
    for i,mark in enumerate(marks):
        following=marks[i+1] if i+1<len(marks) else {'page':len(rows),'offset':len(rows[len(rows)-1]['text'])}
        if i+1<len(marks) and mark['refs'][0].split('.')[0]!=marks[i+1]['refs'][0].split('.')[0]:
            following=boundaries[int(marks[i+1]['refs'][0].split('.')[0])]
        end_page=book.get('reference_end_pages',{}).get(mark['refs'][0])
        if end_page is not None and end_page<=following['page']:
            following={'page':end_page,'offset':len(rows[end_page-1]['text'])}
        segments=[]
        for page in range(mark['page'],following['page']+1):
            start=mark['offset'] if page==mark['page'] else 0
            end=following['offset'] if page==following['page'] else len(rows[page-1]['text'])
            if rows[page-1]['text'][start:end].strip():segments.append({'page':page,'start':start,'end':end})
        for ref in mark['refs']:spans[ref]=segments
    changed=sum(aliases[r]!=expected[r] for r in aliases)
    print(f"{book['id']}: {len(aliases)} printed reference headings matched; {changed} bookmark targets corrected",flush=True)
    return toc,aliases,spans

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tessdata',type=Path)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--cache',type=Path,default=ROOT/'data/ocr_cache_v2')
    parser.add_argument('--reuse-existing',action='store_true',help='Reuse unchanged indexed editions, avoiding repeat OCR.')
    parser.add_argument('--rebuild',nargs='*',default=[])
    args=parser.parse_args()
    config=json.loads((ROOT/'data/pdf_books.json').read_text(encoding='utf-8'))
    books=[];passages=[];sources=[]
    existing=json.loads((ROOT/'data/corpus.json').read_text(encoding='utf-8')) if args.reuse_existing and (ROOT/'data/corpus.json').exists() else {}
    previous={b['id']:b for b in existing.get('books',[])}
    for spec in config['books']:
        book=dict(spec);file=ROOT/'data/pdfs'/book['stored_filename']
        if hashlib.sha256(file.read_bytes()).hexdigest()!=book['pdf_sha256']:raise ValueError('PDF hash mismatch: '+book['id'])
        old=previous.get(book['id'])
        if old and old['pdf_sha256']==book['pdf_sha256'] and book['id'] not in args.rebuild:
            book={**old,**book};books.append(book)
            passages.extend(p for p in existing['passages'] if p['book_id']==book['id'])
            sources.append({**next(s for s in existing['sources'] if s['book_id']==book['id']),'origin':book.get('origin','user_upload')})
            print(book['id']+': retained existing index',flush=True);continue
        with pymupdf.open(file) as doc:
            book['page_count']=len(doc)
            toc=outlines(book,doc);aliases=references(book,toc)
            rows={};jobs=[]
            decoder=DevanagariDecoder(doc) if book['extraction']=='glyph_decoded' else None
            for n,page in enumerate(doc):
                cache=args.cache/book['pdf_sha256']/f'{n+1:04}.json'
                if book['extraction']=='ocr':
                    if cache.exists():rows[n]=json.loads(cache.read_text(encoding='utf-8'))
                    else:jobs.append((str(file),n,str(args.tessdata),str(cache)))
                else:
                    if decoder:decoder.unresolved=0
                    rows[n]=archive_text(page) if book['extraction']=='archive_ocr' else native_text(page,decoder)
                    if decoder:rows[n].update(extraction='glyph_decoded',review_status='font_decoded_unreviewed',unresolved_glyphs=decoder.unresolved)

            if jobs:
                if not args.tessdata or not args.tessdata.is_dir():raise ValueError('This scanned PDF needs --tessdata with hin, san and eng models.')
                print(f"{book['id']}: OCR {len(jobs)} pages ({len(rows)} cached)",flush=True)
                with ProcessPoolExecutor(max_workers=max(1,min(args.workers,8))) as pool:
                    for i,future in enumerate(as_completed([pool.submit(ocr_one,j) for j in jobs]),1):
                        n,result=future.result();rows[n]=result
                        if i%20==0 or i==len(jobs):print(f'OCR {i}/{len(jobs)}',flush=True)
            toc,aliases,reference_spans=verified_anchors(book,toc,rows)
            book['reference_spans']=reference_spans
            major=[x for x in toc if x['level']==1]
            book['toc']=toc;book['sections']=major
            book['indexed_pages']=sum(len(x['text'].strip())>=60 for x in rows.values())
            book['passage_count']=len(doc)
            book['extraction_note']=book.get('extraction_note') or ('OCR search text is unreviewed; compare every quotation with the original page.' if book['extraction']=='ocr' else 'English and Roman transliteration extracted with documented font decoding. Legacy Sanskrit fonts are visible in the PDF but excluded from the text index.')
            book['cover_url']='/api/books/'+book['id']+'/cover'
            book['pdf_url']='/api/books/'+book['id']+'/pdf'
            books.append(book)
            sources.append({'id':book['id'],'book_id':book['id'],'title':book['title'],'edition':book['edition'],'source_type':book['source_type'],'origin':book.get('origin','user_upload'),**{k:book[k] for k in ('catalog_url','download_url','translator','publication_year','languages') if k in book},'filename':book['filename'],'pdf_sha256':book['pdf_sha256'],'page_count':len(doc),'rights':book['rights'],'extraction_note':book['extraction_note'],'review_status':'Not independently proofread; original pages remain available.'})
            for n in range(len(doc)):
                page=n+1;item=rows[n];section=next((s for s in reversed(major) if s['page']<=page),None)
                refs=[ref for ref,p in aliases.items() if p==page]
                label=next((s['title'] for s in reversed(toc) if s['page']<=page),f'PDF page {page}')
                non_body=next((r for r in book.get('non_body_ranges',[]) if r['start']<=page<=r['end']),None)
                if non_body:label=non_body['label'];section={'title':label}
                text=item['text']
                passages.append({'id':f"{book['id']}:{page}",'book_id':book['id'],'page':page,'ordinal':n,'ref':str(page),'refs':refs,'ref_label':f'PDF page {page}','section':(book['title'] if book.get('outline_note','').startswith('Selected') else section['title'] if section else 'Front matter'),'heading':(next((t['title'] for t in toc if t['page']==page),f'PDF page {page}') if book.get('outline_note','').startswith('Selected') else label),'heading_note':book.get('heading_overrides',{}).get(str(page),{}).get('note'),'text':text,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'source_id':book['id'],'source_url':f"/api/books/{book['id']}/pdf#page={page}",'page_url':f"/api/books/{book['id']}/pages/{page}/image",**{k:v for k,v in item.items() if k!='text'}})
            print(f"{book['id']}: {len(doc)} pages, {book['indexed_pages']} text-indexed, {len(aliases)} reference anchors",flush=True)
    output={'schema_version':2,'source_type':'uploaded_pdf','generated_at':datetime.now(timezone.utc).isoformat(),'books':books,'sources':sources,'passages':passages}
    atomic_json(ROOT/'data/corpus.json',output)
    atomic_json(ROOT/'data/source_manifest.json',{'schema_version':2,'sources':sources,'books':books})
    print(f'Imported {len(books)} PDF editions and {len(passages)} pages.',flush=True)

if __name__=='__main__':main()
