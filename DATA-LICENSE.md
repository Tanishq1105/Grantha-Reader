# Application code and supplied books

The original application code and documentation use the MIT license in `LICENSE`. This does not relicense the user-supplied books, their translations, commentary, artwork or extracted text.

The package returns the supplied PDFs as part of the user's requested reader. Their bytes and publisher notices are unchanged. No permission for public redistribution or commercial use is inferred from the uploads. The searchable text is an extraction from those same books, not a separately licensed website corpus.

| Original file | Attribution recorded from the supplied edition |
| --- | --- |
| Bhagavad Gita.pdf | Śrīmad Bhagavad Gītā, edited by Ashok Kaushik |
| bhagavad-gita-as-it-is.pdf | A. C. Bhaktivedanta Swami Prabhupāda / BBT |
| Valmiki_Ramayana_Gita_Press.pdf | Gita Press, Sanskrit text and English translation |

The source edition and PDF page accompany every retrieval result. `docs/SOURCES.md` documents OCR, font decoding and index corrections. Corrections to navigation metadata do not change the original book pages.

Dependencies retain their own licenses. In particular, PyMuPDF has AGPL/commercial licensing terms; the MIT license on this project's original code does not override them. See the installed dependency's license and https://pymupdf.readthedocs.io/en/latest/about.html. Tesseract and its language models have their own notices and are only needed to regenerate OCR. React notices and the Noto Serif Devanagari SIL Open Font License are retained in `frontend/public/` and the built distribution.

This is a private supplied-book project package, not a declaration that the books or all dependencies are covered by MIT or Creative Commons.

The eight added historical scans are attributed in `docs/SOURCES.md` and `data/pdf_books.json`. Their original title pages and archive records identify the editions and translators. The app claims no new rights in those scans or translations. The Devanagari recovery map derives from Noto font mappings under the SIL Open Font License; upstream font binaries are not bundled for map rebuilding.
