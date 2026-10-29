"""Build a deterministic glyph map for the supplied Mahabharata PDFs.

Requires fonttools and two reference Noto fonts from the recorded upstream
commit. Every used embedded glyph outline must match before a map is written.
The PDFs and their printed wording are never edited.
"""
import argparse
from pathlib import Path
from io import BytesIO
import hashlib
import json
from fontTools.ttLib import TTFont
from fontTools.pens.recordingPen import DecomposingRecordingPen
import pymupdf
import uharfbuzz as hb
from itertools import product

ROOT = Path(__file__).resolve().parents[1]
COMMIT = 'ad153f5a14c838afb16c83f0a02784c7605f1e21'


def glyphs(font):
    gs = font.getGlyphSet()
    result = {}
    for i, name in enumerate(font.getGlyphOrder()):
        pen = DecomposingRecordingPen(gs)
        gs[name].draw(pen)
        if pen.value:
            result[i] = pen.value
    return result


def decode_map(font):
    base = {g: chr(c) for c, g in font.getBestCmap().items()}
    substitutions = []
    lookups = font['GSUB'].table.LookupList.Lookup
    # Repha is drawn after its consonant cluster. Preserve that distinction
    # until the extraction step restores Unicode's logical character order.
    for feature in font['GSUB'].table.FeatureList.FeatureRecord:
        if feature.FeatureTag == 'rphf':
            for index in feature.Feature.LookupListIndex:
                for sub in lookups[index].SubTable:
                    for rules in getattr(sub, 'ligatures', {}).values():
                        for rule in rules:
                            base[rule.LigGlyph] = '\ue000'
    for lookup in lookups:
        for sub in lookup.SubTable:
            for a, b in getattr(sub, 'mapping', {}).items():
                if isinstance(b, str):
                    substitutions.append((b, [a]))
            for a, rules in getattr(sub, 'ligatures', {}).items():
                for rule in rules:
                    substitutions.append((rule.LigGlyph, [a, *rule.Component]))
    for _ in range(20):
        changed = False
        for dst, src in substitutions:
            if dst not in base and all(s in base for s in src):
                base[dst] = ''.join(base[s] for s in src)
                changed = True
        if not changed:
            break
    return {str(i): base[name] for i, name in enumerate(font.getGlyphOrder()) if name in base}


def prebase_i_forms(path):
    """Recover contextual i/repha/anusvara forms by forward shaping.

    Noto uses the same trailing outline for different marks. The preceding
    i-form determines their meaning, so a one-glyph reverse map is insufficient.
    """
    font = hb.Font(hb.Face(path.read_bytes()))
    canonical = decode_map(TTFont(path))
    consonants = list('कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह')
    clusters = consonants + ['्'.join(x) for x in product(consonants, repeat=2)]
    clusters += ['्'.join(x) for x in product('कतमशस', repeat=3)]
    samples, endings = [], {}
    for cluster in clusters:
        if cluster.startswith('र्'):
            continue
        for reph, nasal in product((False, True), repeat=2):
            buf = hb.Buffer()
            buf.add_str(('र्' if reph else '') + cluster + 'ि' + ('ं' if nasal else ''))
            buf.guess_segment_properties()
            hb.shape(font, buf)
            ids = [g.codepoint for g in buf.glyph_infos]
            prefix = str(ids[0])
            if canonical.get(prefix) != 'ि':
                continue
            flags = ('\ue000' if reph else '') + ('ं' if nasal else '')
            samples.append((prefix, str(ids[-1]), flags))
            if flags:
                endings.setdefault(str(ids[-1]), set()).add(flags)
    tails = {gid for gid, meanings in endings.items() if len(meanings) > 1}
    forms = {}
    for prefix, tail, flags in samples:
        flags = flags if tail in tails else ''
        if prefix in forms and forms[prefix] != flags:
            raise ValueError('Ambiguous i-form in reference font.')
        forms[prefix] = flags
    return forms, sorted(tails)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--font-directory', type=Path, required=True)
    args = parser.parse_args()
    references = {}
    for style in ['Regular', 'Bold']:
        path = args.font_directory / f'NotoSansDevanagari-{style}-old.ttf'
        font = TTFont(path)
        references[style] = (font, glyphs(font), decode_map(font), hashlib.sha256(path.read_bytes()).hexdigest(), prebase_i_forms(path))
    mappings = {}
    for path in sorted((ROOT / 'data/pdfs').glob('mahabharata*.pdf')):
        with pymupdf.open(path) as doc:
            used = {tuple(font) for page in doc for font in page.get_fonts() if 'NotoSansDevanagari' in font[3]}
            for entry in used:
                data = doc.extract_font(entry[0])[3]
                digest = hashlib.sha256(data).hexdigest()
                if digest in mappings:
                    continue
                style = 'Bold' if 'Bold' in entry[3] else 'Regular'
                font, expected, chars, reference_hash, (iforms, tails) = references[style]
                embedded = TTFont(BytesIO(data))
                actual = glyphs(embedded)
                if embedded['head'].unitsPerEm != font['head'].unitsPerEm or any(expected.get(i) != v for i, v in actual.items()):
                    raise ValueError(f'Font outline mismatch: {path.name}, {entry[3]}')
                mappings[digest] = {'glyphs': chars, 'i_forms': iforms, 'i_tails': tails, 'style': style, 'verified_outline_count': len(actual), 'reference_sha256': reference_hash}
    output = {'upstream': f'https://github.com/notofonts/noto-fonts/tree/{COMMIT}/hinted', 'font_mappings': mappings}
    (ROOT / 'data/devanagari_glyph_map.json').write_text(json.dumps(output, ensure_ascii=False), encoding='utf-8')
    print(f'Verified {len(mappings)} embedded fonts. Text still requires proofreading.')


if __name__ == '__main__':
    main()
