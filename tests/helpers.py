"""
Minimal test-file factory helpers shared across test modules.
Kept separate from conftest.py to avoid double-import side effects.
"""


def make_epub_bytes() -> bytes:
    """Return bytes of a minimal but valid EPUB file."""
    import ebooklib.epub as ep
    import io
    book = ep.EpubBook()
    book.set_title("Test EPUB")
    book.set_language("en")
    ch = ep.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    ch.content = b"<html><body><p>Hello</p></body></html>"
    book.add_item(ch)
    book.toc = (ep.Link("ch1.xhtml", "Ch1", "ch1"),)
    book.add_item(ep.EpubNcx())
    book.add_item(ep.EpubNav())
    book.spine = ["nav", ch]
    buf = io.BytesIO()
    ep.write_epub(buf, book)
    return buf.getvalue()


def make_pdf_bytes() -> bytes:
    """Return bytes of a minimal PDF."""
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Test PDF", fontsize=12)
    buf = doc.write()
    doc.close()
    return buf


def make_fb2_bytes() -> bytes:
    return b"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info>
<genre>fiction</genre>
<author><first-name>Test</first-name><last-name>Author</last-name></author>
<book-title>Test FB2</book-title>
<lang>en</lang>
</title-info></description>
<body><section><p>Hello</p></section></body>
</FictionBook>"""


def make_cbz_bytes() -> bytes:
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("page1.jpg", b"\xff\xd8\xff\xd9")
    return buf.getvalue()
