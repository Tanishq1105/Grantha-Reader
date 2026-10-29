"""Deterministic PDF extraction. The unmodified page is the reading authority.

Legacy Sanskrit glyph fonts are omitted from native extraction, never guessed.
The two documented Roman-font maps repair encoded IAST glyphs, not translations.
Scanned pages use Tesseract; their text remains explicitly unreviewed OCR.
"""
import csv
import io
import os
import re
import subprocess
from collections import OrderedDict
import pymupdf

GOUDY = str.maketrans({'ä':'ā','Ä':'Ā','é':'ī','É':'Ī','ü':'ū','Ü':'Ū','å':'ṛ','Å':'Ṛ','è':'ṝ','È':'Ṝ','ë':'ṇ','Ë':'Ṇ','ì':'ṅ','Ì':'Ṅ','ï':'ñ','Ï':'Ñ','ò':'ḍ','Ò':'Ḍ','ö':'ṭ','Ö':'Ṭ','ç':'ś','Ç':'Ś','ñ':'ṣ','Ñ':'Ṣ','ù':'ḥ','Ù':'Ḥ','à':'ṁ','À':'Ṁ'})
NALANDA = str.maketrans({'å':'ā','Å':'Ā','∂':'ī','∫':'Ī','æ':'ṛ','Æ':'Ṛ','ƒ':'ṇ','¶':'ṣ','Œ':'ḍ','‹':'ś','›':'Ś','≈':'ṃ','ì':'“','î':'”','í':'’','ó':'—','œ':'Ḍ','∆':'ṅ'})

def archive_text(page):
    """Preserve the archive OCR layer's reading order, without decoding images."""
    text=page.get_text('text',sort=False,flags=pymupdf.TEXTFLAGS_TEXT)
    text=re.sub(r'[ \t]+',' ',text).strip()
    return {'text':text,'extraction':'archive_ocr','ocr_confidence':None,'legacy_sanskrit_omitted':False,'review_status':'ocr_unreviewed'}

def font_text(text, font):
    if 'ScaGoudy' in font:
        return text.translate(GOUDY)
    if 'Nalanda' in font:
        return text.replace('§R','Ṛ').replace('§S','Ṣ').replace('°N','Ṇ').translate(NALANDA)
    return text

def native_text(page, decoder=None):
    lines=[];seen={};omitted=False;single_column=False
    for block in page.get_text('dict',sort=False,flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
        for line in block.get('lines',[]):
            spans=[];bounds=[];baselines=[];original_spans=[]
            for span in line['spans']:
                font=span['font']
                if 'ScaGoudy' in font:single_column=True
                if any(name in font for name in ('Chanakya','Indevr','Dingbits','Dingbats')):
                    omitted=True;continue
                spans.append(font_text(span['text'],font));original_spans.append((span['text'],font));bounds.append(span['bbox']);baselines.append(span['origin'][1])
            value=(decoder.line(original_spans) if decoder else ''.join(spans)).strip()
            if not value or value.startswith('Copyright © 1998 The Bhaktivedanta'):continue
            x=min(b[0] for b in bounds);y=min(baselines);right=max(b[2] for b in bounds)
            if any(abs(x-oldx)<2 and abs(y-oldy)<2 for oldx,oldy in seen.get(value,[])):continue
            seen.setdefault(value,[]).append((x,y))
            lines.append({'x':x,'y':y,'right':right,'text':value})
    # Read left column then right within bands separated by full-width headings.
    # Sorting only by y would splice simultaneous lines of two columns together;
    # PDF object order can place a canto heading after its first paragraphs.
    middle=page.rect.width/2
    full=sorted([l for l in lines if l['x']<middle-2 and l['right']>middle+2],key=lambda l:(l['y'],l['x']))
    remaining=[l for l in lines if l not in full];ordered=[]
    for heading in full+[{'y':float('inf')}]:
        band=[l for l in remaining if l['y']<heading['y']-1]
        remaining=[l for l in remaining if l not in band]
        ordered.extend(sorted(band,key=lambda l:(0 if l['x']<middle else 1,l['y'],l['x'])))
        if 'text' in heading:ordered.append(heading)
    ordered.extend(sorted(remaining,key=lambda l:(l['y'],l['x'])))
    if single_column:ordered=sorted(lines,key=lambda l:(round(l['y'],1),l['x']))
    text='\n'.join(l['text'] for l in ordered)
    text=re.sub(r'[ \t]+',' ',text).strip()
    return {'text':text,'extraction':'pdf_text','ocr_confidence':None,'legacy_sanskrit_omitted':omitted,'review_status':'extracted_unreviewed'}

def ocr_text(page, tessdata, languages='hin+san+eng', dpi=220):
    pix=page.get_pixmap(dpi=dpi,colorspace=pymupdf.csRGB,alpha=False)
    command=['tesseract','stdin','stdout','--tessdata-dir',str(tessdata),'-l',languages,'--psm','3','-c','tessedit_create_tsv=1']
    completed=subprocess.run(command,input=pix.tobytes('png'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=180,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
    if completed.returncode:raise RuntimeError('Tesseract failed: '+completed.stderr.decode('utf-8','replace')[-500:])
    output=completed.stdout.decode('utf-8')
    if not output.startswith('level\tpage_num\t'):
        raise RuntimeError('Tesseract did not return TSV; refusing to publish an empty OCR index.')
    lines=OrderedDict();confidence=[]
    for row in csv.DictReader(io.StringIO(output),delimiter='\t',quoting=csv.QUOTE_NONE):
        text=(row.get('text') or '').strip()
        if not text or row.get('level')!='5':continue
        key=tuple(row.get(k) for k in ('block_num','par_num','line_num'))
        lines.setdefault(key,[]).append(text)
        try:confidence.append(float(row['conf']))
        except (ValueError,TypeError):pass
    return {'text':'\n'.join(' '.join(words) for words in lines.values()),'extraction':'ocr','ocr_confidence':round(sum(confidence)/len(confidence),1) if confidence else 0,'legacy_sanskrit_omitted':False,'review_status':'ocr_unreviewed'}
