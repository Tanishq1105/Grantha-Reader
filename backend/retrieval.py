"""Exact references, work-name selection and Unicode lexical fallback.

Lexical scores rank passages, not probability of truth. Results are evidence
candidates. Only the optional explanation layer makes generated claims.
"""
import math
import re
import unicodedata
from collections import Counter, defaultdict

STOP = set("a an the is are was were of to in for on and or with about what why how who which does do did can could would should tell me explain says say according text scripture book please this that it its as be by not from have has these those all any you your i my we our at into meaning verse chapter show find may much many want know gives give means mentioned mentions teach teaches saying".split())
STOP.update("क्या क्यों कैसे कौन में का की के को से और है हैं करें मुझे बताओ बताइए बारे अर्थ श्लोक अध्याय यह वह न च एव इति किम् कथम्".split())
STOP.update("gita bhagavad bhagavadgita upanishad upanishads said taught regarding related discusses discuss scripture scriptures read passage passages".split())
SYNONYMS = {
    "कर्म": ["action", "duty", "karma"], "कर्मणि": ["action", "karma"], "कर्मण्य": ["action", "karma"],
    "धर्म": ["duty", "dharma"], "आत्मा": ["self", "atman"], "आत्मन्": ["self", "atman"],
    "मन": ["mind"], "मनः": ["mind"], "ज्ञान": ["knowledge"], "ज्ञानम्": ["knowledge"],
    "भक्ति": ["devotion"], "मोक्ष": ["liberation", "freedom"], "मुक्ति": ["liberation", "freedom"],
    "योग": ["yoga"], "फल": ["results", "result", "fruit"], "ध्यान": ["meditation"],
    "शांति": ["peace"], "शान्ति": ["peace"], "सत्य": ["truth"], "सत्यम्": ["truth"],
    "ब्रह्म": ["brahman"], "ब्रह्मन्": ["brahman"], "ब्रह्मा": ["brahma"],
    "मृत्यु": ["death"], "प्राण": ["prana", "breath"], "ओम": ["om"], "ॐ": ["om"],
    "नचिकेता": ["naciketas"], "कृष्ण": ["krishna", "krsna"],
    "karma": ["action", "duty"], "atman": ["self"], "moksha": ["liberation", "freedom"],
    "bhakti": ["devotion"], "dharma": ["duty"], "jnana": ["knowledge"],
}

def normalize(text):
    text = unicodedata.normalize("NFC", str(text)).lower()
    # Strip Latin diacritics only. Devanagari vowel signs must remain intact.
    text = "".join("".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c)) if "LATIN" in unicodedata.name(ch, "") else ch for ch in text)
    text = re.sub(r"[\u0951-\u0954\u1cd0-\u1cff\ua8e0-\ua8f1]", "", text)
    return text.translate(str.maketrans("०१२३४५६७८९", "0123456789"))

def tokenize(text):
    return [w for w in re.findall(r"[a-z0-9\u0900-\u097f]+", normalize(text)) if w not in STOP and len(w) > 1]

# Query aliases assist retrieval only; they never replace or translate page text.
STOP.update("ramayana valmiki edition page pages pdf these explain summarise summarize summary tell said go going went please help understand context happen happened happens reason reasons would describe much also book books upload uploaded question why why?".split())
STOP.update("मुझे बताओ बताएं बताइये समझाएं समझाइए पृष्ठ पन्ना पुस्तक ग्रंथ रामायण गीता इसके इससे इसमें हुआ हुए बताए वर्णन कृपया जाता गए गया".split())
SYNONYMS.update({"राम":["rama"],"रामः":["rama"],"रावण":["ravana"],"सीता":["sita"],"सीतां":["sita"],"हनुमान":["hanuman","hanumantha"],"लक्ष्मण":["laksmana","lakshmana"],"अर्जुन":["arjuna"],"अर्जुनः":["arjuna"],"वनवास":["exile","forest","banishment"],"क्यों":["why"],"स्वधर्म":["duty"],"फलों":["fruits","results"],"समर्पण":["surrender"],"krishna":["krsna","kṛṣṇa"],"hanuman":["hanuman","hanumantha"],"lakshmana":["laksmana"],"ravana":["ravana"],"duty":["dharma","कर्तव्य","कर्म"],"action":["karma","कर्म"],"self":["atman","आत्मा"]})

SYNONYMS.update({"कर्तव्य":["duty","action"],"अनासक्ति":["detachment","attachment"],"आसक्ति":["attachment"],"निष्काम":["selfless","desire","action"],"कर्मफल":["fruits","results","action"],"कर्मफलेषु":["fruits","results","action"],"ईश्वर":["god","lord"],"परमात्मा":["supersoul","self"],"अहंकार":["ego","pride"],"दुख":["sorrow","suffering"],"दुःख":["sorrow","suffering"],"मृत्युः":["death"],"आत्मनः":["self","atman"],"उपनिषदों":["upanishads"],"आत्मविषये":["self","atman"],"कर्तव्यविषये":["duty"],"वनं":["forest","exile"],"वनम्":["forest","exile"]})
STOP.update("शब्दों सरल समझाएँ बातें मुख्य मिला सरलतया विवृणोतु मुख्यविषयाः अस्य पृष्ठस्य किमर्थं गतः उक्तम् गीतायां उपनिषत्सु कः के। है। है?".split())


STOP.update("mahabharata mahabharat rigveda samaveda yajurveda atharvaveda veda vedas महाभारत महाभारतम् ऋग्वेद सामवेद यजुर्वेद अथर्ववेद वेद वेदों वेदेषु कहा कहता कहती कहते होता होती होते हमें चाहिए हूँ हों when am".split())
SYNONYMS.update({"worrying":["worry","anxiety","anxious"],"outcomes":["results","fruits"],"outcome":["result","fruit"],"working":["work","action"]})

def infer_books(query,books):
    """Explicit work names narrow an otherwise collection-wide question."""
    q=normalize(query);categories=set();prefixes=[]
    for category,pattern in [('gita',r'\b(?:gita|bhagavadgita)\b|गीता'),('ramayana',r'\bramayana\b|रामायण'),('mahabharata',r'\bmahabharat(?:a)?\b|महाभारत'),('upanishads',r'\bupanishads?\b|उपनिषद|उपनिषत')]:
        if re.search(pattern,q):categories.add(category)
    for prefix,pattern in [('rigveda',r'\brig\s*veda\b|ऋग्वेद'),('samaveda',r'\bsama\s*veda\b|सामवेद'),('yajurveda',r'\byajur\s*veda\b|यजुर्वेद'),('atharvaveda',r'\batharva\s*veda\b|अथर्ववेद')]:
        if re.search(pattern,q):prefixes.append(prefix)
    if not prefixes and re.search(r'\bvedas?\b|वेदों|वेदेषु',q):categories.add('vedas')
    matches=[b['id'] for b in books if b.get('category') in categories or any(b['id'].startswith(p) for p in prefixes)]
    return matches or None

class Retriever:
    def __init__(self,store):
        self.store=store;self.df=Counter();self.docs={};self.postings=defaultdict(list)
        for p in store.passages:
            if len(p['text'].strip())<60:continue
            counts=Counter(tokenize(p['text']+' '+p.get('heading','')))
            self.docs[p['id']]=(counts,sum(counts.values()));self.df.update(counts.keys())
            for token in counts:self.postings[token].append(p['id'])
        self.avg=sum(n for _,n in self.docs.values())/max(1,len(self.docs))

    @staticmethod
    def has_explicit_reference(query):
        q=normalize(query)
        return bool(re.search(r'\b(?:page|p\.)\s*\d+|(?:पृष्ठ|पन्ना)\s*\d+|(?<!\d)\d+[.:]\d+(?!\d)',q))

    def exact(self,query,book_ids):
        q=normalize(query)
        page=re.search(r'(?:\bpage\s*|\bp\.\s*|पृष्ठ\s*|पन्ना\s*)(\d+)',q)
        reference=re.search(r'(?<!\d)(\d+[.:]\d+(?:[.:]\d+)?)(?!\d)',q)
        if not page and not reference:return None
        ids=list(book_ids or [b['id'] for b in self.store.books])
        if re.search(r'ramayana|रामायण|valmiki',q):ids=[x for x in ids if x=='ramayana']
        elif re.search(r'as it is|prabhupada|यथारूप',q):ids=[x for x in ids if x=='gitaasitis']
        elif re.search(r'gita|गीता',q):ids=[x for x in ids if x.startswith('gita')]
        if page:return [self.store.by_id[f'{bid}:{int(page[1])}'] for bid in ids if f'{bid}:{int(page[1])}' in self.store.by_id]
        ref=reference[1].replace(':','.')
        results=[]
        for bid in ids:
            b=next(b for b in self.store.books if b['id']==bid)
            for span in b.get('reference_spans',{}).get(ref,[]):
                p=self.store.by_id[f"{bid}:{span['page']}"]
                excerpt=p['text'][span['start']:span['end']]
                results.append({**p,'reference_excerpt':excerpt,'matched_reference':ref})
        return results

    def search(self,query,book_ids=None,limit=8):
        exact=self.exact(query,book_ids)
        if exact is not None:return [{'passage':p,'score':1.0,'match':'exact_reference'} for p in exact[:limit]],'exact'
        base=list(dict.fromkeys(tokenize(query)))
        if not base:return [],'lexical'
        expansions={t:list(dict.fromkeys([t]+[normalize(s) for s in SYNONYMS.get(t,[])])) for t in base}
        supported=[t for t in base if any(self.df.get(x,0) for x in expansions[t])]
        # Missing subject terms must not be outweighed by incidental matches
        # such as "current" and "price" in an unrelated question.
        if len(supported)/len(base)<0.75:return [],'lexical'
        terms=list(dict.fromkeys(x for t in base for x in expansions[t]))
        candidate_ids=set(pid for t in terms for pid in self.postings.get(t,[]));ranked=[];n=len(self.docs)
        for pid in candidate_ids:
            p=self.store.by_id[pid]
            if book_ids and p['book_id'] not in book_ids:continue
            counts,length=self.docs[pid];score=0
            coverage=sum(any(counts.get(x,0) for x in expansions[t]) for t in supported)
            if len(supported)>1 and coverage/len(supported)<0.5:continue
            for term in terms:
                tf=counts.get(term,0)
                if tf:
                    idf=math.log(1+(n-self.df[term]+0.5)/(self.df[term]+0.5))
                    score+=idf*tf*2.2/(tf+1.2*(0.25+0.75*length/max(self.avg,1)))
            score*=0.5+coverage/max(1,len(supported))
            if score>0:ranked.append({'passage':p,'score':round(score,4),'match':'lexical'})
        ranked.sort(key=lambda x:(-x['score'],x['passage']['id']))
        return ranked[:limit],'lexical'
