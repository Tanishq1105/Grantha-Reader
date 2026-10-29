"""Recover this edition's missing PDF Unicode mappings from verified font GSUB."""
from pathlib import Path
import hashlib
import json
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
CLUSTER = r'[क-हक़-य़ऩऱळ](?:़)?(?:्[क-हक़-य़ऩऱळ](?:़)?)*'
PRE_I = re.compile('\ue001' + r'([ंँ\ue000]*)(' + CLUSTER + r')\ue002?')
REPHA = re.compile('(' + CLUSTER + r'[ािीुूृॄॅेैॉोौंँः॒॑]*' + ')\ue000')


class DevanagariDecoder:
    def __init__(self, doc):
        manifest = json.loads((ROOT / 'data/devanagari_glyph_map.json').read_text(encoding='utf-8'))
        self.fonts = {}
        self.unresolved = 0
        used = {tuple(f) for page in doc for f in page.get_fonts() if 'NotoSansDevanagari' in f[3]}
        for entry in used:
            digest = hashlib.sha256(doc.extract_font(entry[0])[3]).hexdigest()
            if digest not in manifest['font_mappings']:
                raise ValueError('Unknown Mahabharata font: rebuild and verify its glyph map first.')
            self.fonts[entry[3].split('+')[-1]] = manifest['font_mappings'][digest]

    def tokens(self, value, font):
        spec = self.fonts.get(font.split('+')[-1])
        if spec is None:
            return value
        mapping = spec['glyphs']
        output = []
        for char in value:
            code = ord(char)
            # Valid PDF Unicode is retained. Missing mappings in these exact
            # files are exposed by MuPDF as glyph IDs below U+0900.
            if 128 <= code < 0x900:
                if str(code) in spec.get('i_forms', {}):
                    output.append('\ue001' + spec['i_forms'][str(code)])
                    continue
                if str(code) in spec.get('i_tails', []):
                    output.append('\ue002')
                    continue
                replacement = mapping.get(str(code))
                if replacement is None:
                    self.unresolved += 1
                    replacement = '\ufffd'
                output.append(replacement.replace('ि', '\ue001'))
            else:
                output.append(char)
        return ''.join(output)

    def line(self, spans):
        result = ''.join(self.tokens(value, font) for value, font in spans)
        result = PRE_I.sub(lambda m: m[2] + 'ि' + m[1], result)
        result = REPHA.sub(lambda m: 'र्' + m[1], result)
        self.unresolved += sum(result.count(c) for c in ['\ue000', '\ue001', '\ue002', '\ufffd'])
        result = result.replace('\ue000', '\ufffd').replace('\ue001', '\ufffd').replace('\ue002', '\ufffd')
        return unicodedata.normalize('NFC', result)

    def __call__(self, value, font):
        return self.line([(value, font)])
