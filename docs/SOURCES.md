# Sources: the supplied books

The active collection contains 17 PDF volumes and 23,348 physical pages: nine user-supplied PDFs and eight historical published book scans. File bytes are retained unchanged. No web-page scripture text or generated translations were added. The original three editions and their reference corrections are documented below.

| ID | Uploaded filename | Stored file | PDF pages | Indexed pages |
| --- | --- | --- | ---: | ---: |
| `gitascan` | Bhagavad Gita.pdf | data/pdfs/gitascan.pdf | 428 | 421 |
| `gitaasitis` | bhagavad-gita-as-it-is.pdf | data/pdfs/gitaasitis.pdf | 1,029 | 1,027 |
| `ramayana` | Valmiki_Ramayana_Gita_Press.pdf | data/pdfs/ramayana.pdf | 2,303 | 2,300 |

“Indexed” means at least 60 extracted characters on the page; it does not certify text accuracy. Every physical page is readable, including covers, blank pages, front matter and publisher notices. Page numbering in citations is one-based PDF numbering.

## Scanned Gītā

The title page names Ashok Kaushik as editor. Original pages contain Sanskrit, Hindi and English. This file has no useful native text layer, so the search index was produced with Tesseract using Hindi, Sanskrit and English models at 220 dpi. The OCR cache is a build aid; the completed searchable corpus is bundled.

Each page retains `extraction: ocr`, mean word confidence and `review_status: ocr_unreviewed`. This is not a reviewed digital edition. Sanskrit characters, punctuation, verse numbers and Hindi words can be misrecognized. The page image is the original authority for reading. No generative model corrected or filled missing text.

All 18 chapter starts were visually checked against printed headings: PDF pages 13, 38, 80, 105, 132, 150, 178, 196, 214, 235, 257, 289, 301, 321, 337, 351, 366 and 382. Individual OCR verse numbers are not treated as certified anchors. A request for verse 2.47 within this scan does not silently retrieve the other edition.

## Bhagavad-gītā As It Is

Attribution: A. C. Bhaktivedanta Swami Prabhupāda / BBT. The upload includes Sanskrit, Roman transliteration, word meanings, English translation and purports. These layers express the supplied edition and its commentary; they are not interchangeable with the other Gītā book.

The PDF's ScaGoudy Roman font uses legacy character encodings. `backend/pdf_extract.py` applies a fixed character map, arranges lines in reading order and removes duplicate shadowed headings. Unusable Indevr Sanskrit glyph spans are excluded from searchable text; the original Sanskrit remains visible on the page. Repeated download/copyright footers are omitted from the text index, while every original PDF notice remains intact.

**700 reference aliases** are matched to actual printed TEXT/TEXTS headings, including grouped verses. The key set is checked against the supplied outline. Printed-heading matching corrected 580 verse bookmark targets. This verifies reference association, not every word of the transcription.

For example, **2.47 begins on PDF page 163, continues through 164 and ends on 165 before TEXT 48**. The original PDF bookmark pointed to page 162. Search supplies bounded excerpts from the correct continuation pages; opening a citation shows the full original page. Chapter boundaries stop before the next chapter heading. Verse 18.78 ends on PDF page 1028; the download-information page 1029 is separately readable, not included in that verse's span.

## Vālmīki Rāmāyaṇa, Gita Press

The supplied combined file contains Sanskrit text and English translation, with both volumes and seven kāṇḍas. It includes 645 indexed canto aliases in `kanda.canto` format. Kāṇḍas start at PDF pages 59, 283, 715, 929, 1192, 1460 and 2012.

English Nalanda-family font codes are decoded with a deterministic map. Two-column text is read left column then right within bands separated by full-width headings. Sanskrit Chanakya glyph codes are not reliable Unicode text and are excluded from this index. Read Sanskrit in the original page image.

Two printing inconsistencies are explicitly annotated in navigation metadata:

| Reference | PDF page | Printed English heading | Basis for the indexed reference |
| --- | ---: | --- | --- |
| 4.63 | 1154 | Canto XLIII | Sanskrit heading and ending colophon identify canto 63 |
| 7.46 | 2168 | Canto LVI | Sanskrit heading and ending colophon identify canto 46 |

The corresponding printed pages and extracted wording are unchanged. The reader displays the annotation on those pages. Canto 4.67 ends with its colophon on PDF page 1168. Volume II title/contents pages 1169–1191 are separately identified and excluded from that canto. Kāṇḍa boundary headings are not attached to the preceding canto.

## Integrity

The original file SHA-256 values are recorded in `data/pdf_books.json`, `data/corpus.json` and the Sources screen. Every page's extracted text also has a SHA-256. Hashes detect changes; they do not establish authenticity or scholarly accuracy. Both native extraction and OCR require proofreading for exact quotations, especially Sanskrit.

## Rebuild the index

The ready-to-run download already includes `data/corpus.json`; normal reading does not need OCR tools. To regenerate extraction deliberately:

1. Install the Python requirements and the Tesseract executable.
2. Obtain `hin.traineddata`, `san.traineddata` and `eng.traineddata` from the official [Tesseract tessdata_fast repository](https://github.com/tesseract-ocr/tessdata_fast). Put all three in one directory. Model files and Tesseract are not bundled here.
3. Keep the exact original PDFs in `data/pdfs/` and run:

```bash
python scripts/import_pdfs.py --tessdata /absolute/path/to/tessdata --workers 4
python -m backend.manage reload-corpus
```

On Windows, use your Windows path to the models and ensure `tesseract.exe` is on PATH. The script resumes completed page OCR from `data/ocr_cache_v2/`. Changing OCR settings or models requires a fresh cache directory via `--cache`. OCR takes time; the first scan contains 428 pages. Native extraction does not use OCR.

Restart the backend after replacement. Rebuild optional embeddings after any corpus change. OCR output can vary by model/tool version and should be reviewed before replacing an existing index. The importer rejects a PDF whose hash differs from the configured edition, incomplete heading coverage, duplicate headings and malformed OCR output.

`tests/fixtures/pdf-sample.json` is a small selection of actual bundled pages for UI tests, not an alternative book source. To add another book, select and identify its edition, preserve the original file, add a deliberate importer/reference strategy and verify its page mapping. There is no unrestricted upload/admin UI in this version.

## Expanded collection — version 3

| Edition | Year | PDF pages | Archive record |
| --- | --- | ---: | --- |
| Mahābhārata · Volume 1 — Gita Press · Sanskrit & Hindi · Ādi & Sabhā | As supplied | 2256 | User-supplied PDF |
| Mahābhārata · Volume 2 — Gita Press · Sanskrit & Hindi · Vana & Virāṭa | As supplied | 2580 | User-supplied PDF |
| Mahābhārata · Volume 3 — Gita Press · Sanskrit & Hindi · Udyoga & Bhīṣma | As supplied | 2343 | User-supplied PDF |
| Mahābhārata · Volume 4 — Gita Press · Sanskrit & Hindi · Droṇa, Karṇa, Śalya, Sauptika & Strī | As supplied | 3237 | User-supplied PDF |
| Mahābhārata · Volume 5 — Gita Press · Sanskrit & Hindi · Śānti | As supplied | 2450 | User-supplied PDF |
| Mahābhārata · Volume 6 — Gita Press · Sanskrit & Hindi · Anuśāsana, Āśvamedhika, Āśramavāsika, Mausala, Mahāprasthānika & Svargārohaṇa | As supplied | 2566 | User-supplied PDF |
| The Upanishads · Part I — F. Max Müller · English translation · 1879 | 1879 | 468 | [Book scan](https://archive.org/details/upanishads01ml) |
| The Upanishads · Part II — F. Max Müller · English translation · 1884 | 1884 | 452 | [Book scan](https://archive.org/details/upanishads02ml) |
| Hymns of the Ṛgveda · Volume I — Ralph T. H. Griffith · English translation · 1896 | 1896 | 720 | [Book scan](https://archive.org/details/in.ernet.dli.2015.104118) |
| Hymns of the Ṛgveda · Volume II — Ralph T. H. Griffith · English translation · 1897 | 1897 | 688 | [Book scan](https://archive.org/details/in.ernet.dli.2015.195722) |
| Hymns of the Sāmaveda — Ralph T. H. Griffith · English translation · 1907 | 1907 | 394 | [Book scan](https://archive.org/details/hymnsofsmaveda00grifiala) |
| Texts of the White Yajurveda — Ralph T. H. Griffith · English translation · 1899 | 1899 | 371 | [Book scan](https://archive.org/details/in.ernet.dli.2015.215626) |
| Hymns of the Atharvaveda · Volume I — Ralph T. H. Griffith · English translation · 1916 | 1916 | 550 | [Book scan](https://archive.org/details/hymnsoftheatharv029640mbp) |
| Hymns of the Atharvaveda · Volume II — Ralph T. H. Griffith · English translation · 1917 | 1917 | 513 | [Book scan](https://archive.org/details/hymnsoftheatharv029485mbp) |

Mahābhārata volumes 1–6 contain, respectively: Ādi/Sabhā; Vana/Virāṭa; Udyoga/Bhīṣma; Droṇa/Karṇa/Śalya/Sauptika/Strī; Śānti; and Anuśāsana/Āśvamedhika/Āśramavāsika/Mausala/Mahāprasthānika/Svargārohaṇa. They have Sanskrit and Hindi on the actual pages. Title pages were checked against their printed lists.

The twelve Upanishads are Chāndogya, Kena, Aitareya, Kauṣītaki, Īśā, Kaṭha, Muṇḍaka, Taittirīya, Bṛhadāraṇyaka, Śvetāśvatara, Praśna and Maitrāyaṇīya. Part I includes the broader Aitareya Āraṇyaka. Māṇḍūkya and all 108 Upanishads are not claimed. Griffith's White Yajurveda is a specific Śukla/Vājasaneyi edition. Historical translation choices and commentary belong to their respective translators.

### Mahābhārata text recovery

The embedded Noto Devanagari subset fonts have missing Unicode mappings. Glyph outlines were matched against Noto fonts at upstream commit `ad153f5a14c838afb16c83f0a02784c7605f1e21`, then GSUB mappings and forward shaping were used to recover character order. Contextual short-i, repha and anusvāra forms are distinguished; unresolved glyphs become replacement characters rather than guessed words. The source PDFs are never rewritten. The two font identities and mappings are recorded in `data/devanagari_glyph_map.json`. Outline verification does not certify the transcription. There are 247 pages with unresolved glyphs; they remain readable but are excluded from generated explanations.

To rebuild the map, obtain `hinted/NotoSansDevanagari-Regular.ttf` and `hinted/NotoSansDevanagari-Bold.ttf` from that exact [upstream commit](https://github.com/notofonts/noto-fonts/tree/ad153f5a14c838afb16c83f0a02784c7605f1e21/hinted), save them as `NotoSansDevanagari-Regular-old.ttf` and `NotoSansDevanagari-Bold-old.ttf`, install `requirements-dev.txt`, and run `python scripts/build_devanagari_map.py --font-directory YOUR_FONT_DIRECTORY`. The recovery uses no generative text correction.

### Historical scans

The archive's embedded OCR is kept in its original reading order and marked `archive_ocr` / `ocr_unreviewed`, with unknown confidence. OCR can corrupt diacritics, names, word spacing and numbers. A scan may contain blank, cropped or damaged pages; page coverage means every page of the supplied PDF, not independent certification of a complete critical edition. The original scan is always available for comparison.

Selected section links were checked against the stored text. The two headings missed by archive OCR (Rigveda II, Book X at PDF 394; Atharvaveda II, Book XVIII at PDF 223) were checked visually. Yajurveda's outline links the beginning of its translation; use PDF-page navigation for other chapters. No verse anchors are invented for the new volumes.

Run `python scripts/import_pdfs.py --reuse-existing` to retain unchanged indexes, avoiding repeat OCR of the original Gītā scan. Add `--rebuild BOOK_ID ...` to re-extract selected editions. Full OCR rebuilding still requires the Tesseract resources described above. Reload the database index and restart the server after changing the corpus.
