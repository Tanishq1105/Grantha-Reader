import hashlib
from scripts.setup_books import restore


def book(data=b'original PDF bytes'):
    return {'title': 'Test edition', 'filename': 'Original.pdf',
            'stored_filename': 'book.pdf', 'pdf_sha256': hashlib.sha256(data).hexdigest()}


def test_restore_exact_local_edition_and_preserve_changed_destination(tmp_path):
    source=tmp_path/'old'/'data'/'pdfs';source.mkdir(parents=True)
    original=b'original PDF bytes';(source/'book.pdf').write_bytes(original)
    destination=tmp_path/'new'/'data'/'pdfs'
    assert restore([book()],destination,[tmp_path/'old'])==[]
    assert (destination/'book.pdf').read_bytes()==original
    (destination/'book.pdf').write_bytes(b'a different edition')
    assert restore([book()],destination,[tmp_path/'old'])==['Original.pdf']
    assert (destination/'book.pdf').read_bytes()==b'a different edition'


def test_restore_rejects_same_filename_with_different_bytes(tmp_path):
    source=tmp_path/'downloads';source.mkdir()
    (source/'Original.pdf').write_bytes(b'a different edition')
    destination=tmp_path/'books'
    assert restore([book()],destination,[source])==['Original.pdf']
    assert not list(destination.iterdir())
