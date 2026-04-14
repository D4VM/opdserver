"""
OPDS feed tests: structure, namespaces, pagination, search, navigation entries.
"""
import pytest
from lxml import etree

from tests.helpers import make_epub_bytes

ATOM_NS = "http://www.w3.org/2005/Atom"
DC_NS = "http://purl.org/dc/terms/"
OS_NS = "http://a9.com/-/spec/opensearch/1.1/"
CALIBRE_NS = "http://calibre.kovidgoyal.net/2009/metadata"


def _parse(resp) -> etree._Element:
    assert resp.status_code == 200
    return etree.fromstring(resp.content)


async def _upload_book(client, title="OPDS Book", author="OPDS Author") -> str:
    import ebooklib.epub as ep, io
    book = ep.EpubBook()
    book.set_title(title)
    book.set_language("en")
    ch = ep.EpubHtml(title="Ch", file_name="ch.xhtml", lang="en")
    ch.content = b"<html><body><p>x</p></body></html>"
    book.add_item(ch)
    book.toc = (ep.Link("ch.xhtml", "Ch", "ch"),)
    book.add_item(ep.EpubNcx())
    book.add_item(ep.EpubNav())
    book.spine = ["nav", ch]
    buf = io.BytesIO()
    ep.write_epub(buf, book)
    resp = await client.post(
        "/api/upload",
        files=[("files", (f"{title}.epub", buf.getvalue(), "application/epub+zip"))],
    )
    return resp.json()[0]["id"]


# ── Root feed ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_root_returns_200(client):
    resp = await client.get("/opds")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_opds_root_content_type(client):
    resp = await client.get("/opds")
    ct = resp.headers.get("content-type", "")
    assert "atom+xml" in ct


@pytest.mark.anyio
async def test_opds_root_valid_xml(client):
    resp = await client.get("/opds")
    feed = _parse(resp)
    assert feed.tag == f"{{{ATOM_NS}}}feed"


@pytest.mark.anyio
async def test_opds_root_has_navigation_entries(client):
    resp = await client.get("/opds")
    feed = _parse(resp)
    entries = feed.findall(f"{{{ATOM_NS}}}entry")
    # Should have: All Books, Recent, Authors, Series, Tags
    assert len(entries) >= 5


@pytest.mark.anyio
async def test_opds_root_trailing_slash(client):
    """Both /opds and /opds/ should work."""
    r1 = await client.get("/opds")
    r2 = await client.get("/opds/")
    assert r1.status_code == r2.status_code == 200


# ── All books ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_all_returns_200(client):
    resp = await client.get("/opds/all")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_opds_all_contains_uploaded_book(client):
    book_id = await _upload_book(client, "UniqueOPDSTitle999")
    resp = await client.get("/opds/all")
    assert resp.status_code == 200
    assert b"UniqueOPDSTitle999" in resp.content


@pytest.mark.anyio
async def test_opds_all_entry_has_acquisition_link(client):
    await _upload_book(client, "AcqLinkTest")
    resp = await client.get("/opds/all")
    feed = _parse(resp)
    for entry in feed.findall(f"{{{ATOM_NS}}}entry"):
        links = entry.findall(f"{{{ATOM_NS}}}link")
        acq = [l for l in links if "acquisition" in l.get("rel", "")]
        if acq:
            assert acq[0].get("href", "").startswith("http")
            break


# ── Recent ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_recent_returns_200(client):
    resp = await client.get("/opds/recent")
    assert resp.status_code == 200


# ── Pagination ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_all_invalid_page_clamped(client):
    """Negative page parameter must not crash."""
    resp = await client.get("/opds/all?page=0")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_opds_all_page_param(client):
    resp = await client.get("/opds/all?page=999")
    assert resp.status_code == 200


# ── Authors ───────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_authors_returns_200(client):
    resp = await client.get("/opds/authors")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_opds_author_books(client):
    await _upload_book(client, "AuthorBooksTitle", author="UniqueAuthorOPDS")
    resp = await client.get("/opds/authors/UniqueAuthorOPDS")
    assert resp.status_code == 200
    assert b"UniqueAuthorOPDS" in resp.content


# ── Series ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_series_returns_200(client):
    resp = await client.get("/opds/series")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_opds_series_books(client):
    book_id = await _upload_book(client, "SeriesBookOPDS")
    await client.post(f"/api/books/{book_id}", params={"series": "UniqueSeriesOPDS", "series_index": "1"})
    resp = await client.get("/opds/series/UniqueSeriesOPDS")
    assert resp.status_code == 200


# ── Tags ──────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_tags_returns_200(client):
    resp = await client.get("/opds/tags")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_opds_tag_books(client):
    book_id = await _upload_book(client, "TaggedBook")
    tag = (await client.post("/api/tags", params={"name": "opds-test-tag"})).json()
    await client.post(f"/api/books/{book_id}/tags/{tag['id']}")
    resp = await client.get("/opds/tags/opds-test-tag")
    assert resp.status_code == 200


# ── Search ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_search_returns_200(client):
    resp = await client.get("/opds/search?q=test")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_opds_search_finds_book(client):
    await _upload_book(client, "UniqueSearchableOPDS888")
    resp = await client.get("/opds/search?q=UniqueSearchableOPDS888")
    assert resp.status_code == 200
    assert b"UniqueSearchableOPDS888" in resp.content


@pytest.mark.anyio
async def test_opds_search_empty_query(client):
    resp = await client.get("/opds/search?q=")
    assert resp.status_code == 200


# ── OpenSearch ────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opensearch_xml(client):
    resp = await client.get("/opds/opensearch.xml")
    assert resp.status_code == 200
    assert b"OpenSearchDescription" in resp.content
    assert b"searchTerms" in resp.content


# ── Calibre series extension ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_opds_entry_has_calibre_series(client):
    book_id = await _upload_book(client, "SeriesEntryTest")
    await client.post(
        f"/api/books/{book_id}",
        params={"series": "CalibreSeries", "series_index": "2"},
    )
    resp = await client.get("/opds/all")
    assert resp.status_code == 200
    assert b"CalibreSeries" in resp.content


# ── Well-formedness ───────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_all_opds_endpoints_return_valid_xml(client):
    endpoints = ["/opds", "/opds/all", "/opds/recent", "/opds/authors",
                 "/opds/series", "/opds/tags", "/opds/search?q=x"]
    for url in endpoints:
        resp = await client.get(url)
        assert resp.status_code == 200, f"Failed: {url}"
        try:
            etree.fromstring(resp.content)
        except etree.XMLSyntaxError as e:
            pytest.fail(f"Invalid XML from {url}: {e}")
