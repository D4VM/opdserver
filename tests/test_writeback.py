"""
Metadata write-back tests: round-trip for EPUB, PDF, FB2, CBZ.
Tests idempotency (writing twice gives same result, no accumulation).
"""
import zipfile
import warnings

import pytest

warnings.filterwarnings("ignore")

FIELDS = {
    "title": "Roundtrip Title",
    "author": "Test Author",
    "description": "A test description.",
    "publisher": "Test Publisher",
    "language": "en",
    "published": "2024-01-01",
    "series": "Test Series",
    "series_index": 3.0,
}


def _epub_series_name(metadata):
    """Extract calibre:series name from ebooklib metadata."""
    for ns_key in metadata:
        for tag_key in metadata[ns_key]:
            tag = str(tag_key).lower()
            if "series" in tag and "index" not in tag:
                for text, attrs in metadata[ns_key][tag_key]:
                    val = text or attrs.get("content")
                    if val:
                        return val
    return None


def _make_epub(path):
    import ebooklib.epub as ep
    book = ep.EpubBook()
    book.set_title("Original Title")
    book.set_language("en")
    ch = ep.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    ch.content = b"<html><body><p>Hello</p></body></html>"
    book.add_item(ch)
    book.toc = (ep.Link("ch1.xhtml", "Ch1", "ch1"),)
    book.add_item(ep.EpubNcx())
    book.add_item(ep.EpubNav())
    book.spine = ["nav", ch]
    ep.write_epub(str(path), book)


def _make_pdf(path):
    import fitz
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "PDF", fontsize=12)
    doc.save(str(path))
    doc.close()


def _make_fb2(path):
    path.write_bytes(b"""<?xml version="1.0" encoding="utf-8"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info>
<genre>fiction</genre>
<author><first-name>Old</first-name><last-name>Author</last-name></author>
<book-title>Old Title</book-title>
<lang>en</lang>
</title-info></description>
<body><section><p>Text</p></section></body>
</FictionBook>""")


def _make_cbz(path):
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("page1.jpg", b"\xff\xd8\xff\xd9")
    path.write_bytes(buf.getvalue())


# ── EPUB ──────────────────────────────────────────────────────────────────────

def test_epub_writeback_title(tmp_path):
    import ebooklib.epub as ep
    from ebooklib.epub import NAMESPACES
    from routers.api import _write_metadata_to_epub

    epub = tmp_path / "test.epub"
    _make_epub(epub)
    _write_metadata_to_epub(epub, FIELDS)

    book = ep.read_epub(str(epub))
    DC_NS = NAMESPACES["DC"]
    titles = [v for v, _ in book.metadata.get(DC_NS, {}).get("title", [])]
    assert titles == ["Roundtrip Title"]


def test_epub_writeback_series(tmp_path):
    import ebooklib.epub as ep
    from routers.api import _write_metadata_to_epub

    epub = tmp_path / "test.epub"
    _make_epub(epub)
    _write_metadata_to_epub(epub, FIELDS)

    book = ep.read_epub(str(epub))
    name = _epub_series_name(book.metadata)
    assert name == "Test Series"


def test_epub_writeback_idempotent(tmp_path):
    """Writing metadata twice must not accumulate duplicate entries."""
    import ebooklib.epub as ep
    from ebooklib.epub import NAMESPACES
    from routers.api import _write_metadata_to_epub

    epub = tmp_path / "test.epub"
    _make_epub(epub)
    _write_metadata_to_epub(epub, FIELDS)
    _write_metadata_to_epub(epub, FIELDS)

    book = ep.read_epub(str(epub))
    DC_NS = NAMESPACES["DC"]
    titles = [v for v, _ in book.metadata.get(DC_NS, {}).get("title", [])]
    assert len(titles) == 1, f"Duplicate titles after 2nd write: {titles}"


def test_epub_writeback_author(tmp_path):
    import ebooklib.epub as ep
    from ebooklib.epub import NAMESPACES
    from routers.api import _write_metadata_to_epub

    epub = tmp_path / "test.epub"
    _make_epub(epub)
    _write_metadata_to_epub(epub, FIELDS)

    book = ep.read_epub(str(epub))
    DC_NS = NAMESPACES["DC"]
    creators = [v for v, _ in book.metadata.get(DC_NS, {}).get("creator", [])]
    assert "Test Author" in creators


def test_epub_writeback_with_cover(tmp_path):
    """Writing cover bytes should update or add a cover image item."""
    from PIL import Image
    import io
    from routers.api import _write_metadata_to_epub
    import ebooklib

    epub = tmp_path / "test.epub"
    _make_epub(epub)

    buf = io.BytesIO()
    Image.new("RGB", (100, 150), (255, 0, 0)).save(buf, format="JPEG")
    cover_bytes = buf.getvalue()

    _write_metadata_to_epub(epub, {"title": "With Cover"}, cover_bytes=cover_bytes)

    import ebooklib.epub as ep
    book = ep.read_epub(str(epub))
    images = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
    assert len(images) > 0


# ── PDF ───────────────────────────────────────────────────────────────────────

def test_pdf_writeback_metadata(tmp_path):
    import fitz
    from routers.api import _write_metadata_to_pdf

    pdf = tmp_path / "test.pdf"
    _make_pdf(pdf)
    _write_metadata_to_pdf(pdf, FIELDS)

    doc = fitz.open(str(pdf))
    meta = doc.metadata
    doc.close()
    assert meta.get("title") == "Roundtrip Title"
    assert meta.get("author") == "Test Author"


def test_pdf_writeback_idempotent(tmp_path):
    import fitz
    from routers.api import _write_metadata_to_pdf

    pdf = tmp_path / "test.pdf"
    _make_pdf(pdf)
    _write_metadata_to_pdf(pdf, FIELDS)
    _write_metadata_to_pdf(pdf, FIELDS)

    doc = fitz.open(str(pdf))
    assert doc.metadata.get("title") == "Roundtrip Title"
    doc.close()


def test_pdf_writeback_temp_file_cleaned_on_error(tmp_path):
    """If PDF write-back fails, no .tmp.pdf should be left behind."""
    from routers.api import _write_metadata_to_pdf

    pdf = tmp_path / "corrupt.pdf"
    pdf.write_bytes(b"this is not a pdf")
    _write_metadata_to_pdf(pdf, FIELDS)
    assert not (tmp_path / "corrupt.tmp.pdf").exists()


# ── FB2 ───────────────────────────────────────────────────────────────────────

def test_fb2_writeback_title(tmp_path):
    from lxml import etree
    from routers.api import _write_metadata_to_fb2

    fb2 = tmp_path / "test.fb2"
    _make_fb2(fb2)
    _write_metadata_to_fb2(fb2, FIELDS)

    tree = etree.parse(str(fb2))
    ns = "http://www.gribuser.ru/xml/fictionbook/2.0"
    title = tree.find(f".//{{{ns}}}book-title")
    assert title is not None and title.text == "Roundtrip Title"


def test_fb2_writeback_series(tmp_path):
    from lxml import etree
    from routers.api import _write_metadata_to_fb2

    fb2 = tmp_path / "test.fb2"
    _make_fb2(fb2)
    _write_metadata_to_fb2(fb2, FIELDS)

    tree = etree.parse(str(fb2))
    ns = "http://www.gribuser.ru/xml/fictionbook/2.0"
    seq = tree.find(f".//{{{ns}}}sequence")
    assert seq is not None
    assert seq.get("name") == "Test Series"
    assert seq.get("number") == "3"


def test_fb2_writeback_author_split(tmp_path):
    """Author 'First Last' should split into first-name / last-name elements."""
    from lxml import etree
    from routers.api import _write_metadata_to_fb2

    fb2 = tmp_path / "test.fb2"
    _make_fb2(fb2)
    _write_metadata_to_fb2(fb2, {"author": "John Doe"})

    tree = etree.parse(str(fb2))
    ns = "http://www.gribuser.ru/xml/fictionbook/2.0"
    fn = tree.find(f".//{{{ns}}}first-name")
    ln = tree.find(f".//{{{ns}}}last-name")
    assert fn is not None and fn.text == "John"
    assert ln is not None and ln.text == "Doe"


def test_fb2_writeback_clear_series(tmp_path):
    """Passing series='' should remove the <sequence> element."""
    from lxml import etree
    from routers.api import _write_metadata_to_fb2

    fb2 = tmp_path / "test.fb2"
    _make_fb2(fb2)
    # First add a series
    _write_metadata_to_fb2(fb2, {"series": "To Remove"})
    # Now clear it
    _write_metadata_to_fb2(fb2, {"series": ""})

    tree = etree.parse(str(fb2))
    ns = "http://www.gribuser.ru/xml/fictionbook/2.0"
    seq = tree.find(f".//{{{ns}}}sequence")
    assert seq is None


# ── CBZ ───────────────────────────────────────────────────────────────────────

def test_cbz_writeback_creates_comicinfo(tmp_path):
    from xml.etree.ElementTree import fromstring
    from routers.api import _write_metadata_to_cbz

    cbz = tmp_path / "test.cbz"
    _make_cbz(cbz)
    _write_metadata_to_cbz(cbz, FIELDS)

    with zipfile.ZipFile(cbz) as zf:
        assert "ComicInfo.xml" in zf.namelist()
        root = fromstring(zf.read("ComicInfo.xml"))

    assert root.findtext("Title") == "Roundtrip Title"
    assert root.findtext("Writer") == "Test Author"
    assert root.findtext("Series") == "Test Series"
    assert root.findtext("Number") == "3"
    assert root.findtext("Year") == "2024"


def test_cbz_writeback_updates_existing_comicinfo(tmp_path):
    import io
    from xml.etree.ElementTree import fromstring
    from routers.api import _write_metadata_to_cbz

    # CBZ with existing ComicInfo.xml
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("page1.jpg", b"\xff\xd8\xff\xd9")
        zf.writestr("ComicInfo.xml", b"<ComicInfo><Title>Old</Title></ComicInfo>")
    cbz = tmp_path / "test.cbz"
    cbz.write_bytes(buf.getvalue())

    _write_metadata_to_cbz(cbz, {"title": "New Title"})

    with zipfile.ZipFile(cbz) as zf:
        root = fromstring(zf.read("ComicInfo.xml"))
    assert root.findtext("Title") == "New Title"
    # Original pages preserved
    assert "page1.jpg" in zf.namelist()


def test_cbz_writeback_temp_file_cleaned_on_error(tmp_path):
    """Corrupt CBZ must not leave a .tmp.cbz behind."""
    from routers.api import _write_metadata_to_cbz

    cbz = tmp_path / "bad.cbz"
    cbz.write_bytes(b"not a zip file")
    _write_metadata_to_cbz(cbz, {"title": "X"})
    assert not (tmp_path / "bad.tmp.cbz").exists()


def test_cbz_writeback_float_series_index(tmp_path):
    """series_index=2.5 should be written as '2.5', not '2'."""
    from xml.etree.ElementTree import fromstring
    from routers.api import _write_metadata_to_cbz

    cbz = tmp_path / "test.cbz"
    _make_cbz(cbz)
    _write_metadata_to_cbz(cbz, {"series": "S", "series_index": 2.5})

    with zipfile.ZipFile(cbz) as zf:
        root = fromstring(zf.read("ComicInfo.xml"))
    assert root.findtext("Number") == "2.5"


# ── Dispatcher (_write_metadata_to_file) ─────────────────────────────────────

def test_dispatcher_skips_unknown_format(tmp_path):
    """_write_metadata_to_file must silently skip unsupported formats."""
    from routers.api import _write_metadata_to_file

    mobi = tmp_path / "test.mobi"
    mobi.write_bytes(b"\x50\x4b")
    # Should not raise
    _write_metadata_to_file(mobi, "mobi", {"title": "X"})


def test_dispatcher_passes_cover_bytes(tmp_path):
    """Cover bytes must be forwarded to the EPUB writer."""
    from PIL import Image
    import io as _io
    from routers.api import _write_metadata_to_file

    epub = tmp_path / "cover_test.epub"
    _make_epub(epub)

    buf = _io.BytesIO()
    Image.new("RGB", (50, 75), (0, 255, 0)).save(buf, format="JPEG")
    _write_metadata_to_file(epub, "epub", {"title": "Covered"}, cover_bytes=buf.getvalue())

    import ebooklib, ebooklib.epub as ep
    book = ep.read_epub(str(epub))
    images = list(book.get_items_of_type(ebooklib.ITEM_IMAGE))
    assert len(images) > 0
