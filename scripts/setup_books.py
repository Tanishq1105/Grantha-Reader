"""Restore exact PDFs for the small update ZIP; never substitute an edition."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import URLError
ROOT=Path(__file__).resolve().parents[1]
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def restore(books,destination,folders,download=False):
 destination.mkdir(parents=True,exist_ok=True);missing=[]
 for b in books:
  target=destination/b['stored_filename']
  if target.exists():
   if digest(target)==b['pdf_sha256']:print('Ready:',b['title']);continue
   print('Changed file left untouched:',target);missing.append(b['filename']);continue
  candidates=[d/sub/name for d in folders for sub in ['', 'data/pdfs','grantha/data/pdfs'] for name in [b['filename'],b['stored_filename']]]
  found=next((p for p in candidates if p.is_file() and digest(p)==b['pdf_sha256']),None)
  temp=target.with_suffix('.part')
  try:
   if found:shutil.copyfile(found,temp)
   elif download and b.get('origin')=='public_domain' and b.get('download_url'):
    print('Downloading:',b['title'],flush=True)
    with urlopen(Request(b['download_url'],headers={'User-Agent':'GranthaReader/3.0'}),timeout=90) as response,temp.open('wb') as output:shutil.copyfileobj(response,output,length=1024*1024)
   else:missing.append(b['filename']);continue
   if digest(temp)!=b['pdf_sha256']:raise ValueError('File differs from the indexed edition; not imported.')
   temp.replace(target);print('Restored:',b['title'])
  except (URLError,OSError,ValueError) as e:temp.unlink(missing_ok=True);print(b['title'],str(e));missing.append(b['filename'])
 return missing
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--from-dir',type=Path,action='append',default=[]);p.add_argument('--download-public',action='store_true');a=p.parse_args()
 missing=restore(json.loads((ROOT/'data/pdf_books.json').read_text(encoding='utf-8'))['books'],ROOT/'data/pdfs',a.from_dir,a.download_public)
 if missing:
  print('\nStill needed:');print('\n'.join(' - '+x for x in missing));print('Run again with --from-dir pointing to your old project or original PDF folder.');sys.exit(1)
 print('All 17 PDFs verified. For upgrades run: python -m backend.manage reload-corpus')
