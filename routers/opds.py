"""
OPDS 1.2 catalog — fully spec-compliant for KOReader/Kindle.

Spec refs:
  https://specs.opds.io/opds-1.2.html
  https://specs.opds.io/authentication-for-opds-1.0.html
"""
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from lxml import etree

import config
import database
from database import get_db

router = APIRouter(prefix="/opds")

# ── Namespaces ────────────────────────────────────────────────────────────────
NS = {
    None:       "http://www.w3.org/2005/Atom",
    "opds":     "http://opds-spec.org/2010/catalog",
    "dc":       "http://purl.org/dc/terms/",
    "os":       "http://a9.com/-/spec/opensearch/1.1/",
    "calibre":  "http://calibre.kovidgoyal.net/2009/metadata",
}

ATOM_NS      = "http://www.w3.org/2005/Atom"
DC_NS        = "http://purl.org/dc/terms/"
OS_NS        = "http://a9.com/-/spec/opensearch/1.1/"
CALIBRE_NS   = "http://calibre.kovidgoyal.net/2009/metadata"

# Correct OPDS 1.x link relation URIs
REL_ACQ       = "http://opds-spec.org/acquisition"
REL_IMAGE     = "http://opds-spec.org/image"
REL_THUMBNAIL = "http://opds-spec.org/image/thumbnail"

# Content-Type strings for OPDS feeds
NAV_CT = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_CT = "application/atom+xml;profile=opds-catalog;kind=acquisition"

MIME_MAP = {
    "epub":  "application/epub+zip",
    "pdf":   "application/pdf",
    "mobi":  "application/x-mobipocket-ebook",
    "azw":   "application/vnd.amazon.mobi8-ebook",
    "azw3":  "application/vnd.amazon.mobi8-ebook",
    "cbz":   "application/x-cbz",
    "fb2":   "application/x-fictionbook+xml",
    "txt":   "text/plain",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _quote(s: str) -> str:
    """URL-encode a path segment (encodes spaces, slashes, Cyrillic, etc.)."""
    return urllib.parse.quote(s, safe="")


def _feed(feed_id: str, title: str, updated: str = "") -> etree._Element:
    feed = etree.Element("feed", nsmap=NS)
    etree.SubElement(feed, "id").text = feed_id
    etree.SubElement(feed, "title").text = title
    etree.SubElement(feed, "updated").text = updated or _now()
    author = etree.SubElement(feed, "author")
    etree.SubElement(author, "name").text = config.SERVER_TITLE
    # OpenSearch description — used by KOReader for the search box
    link = etree.SubElement(feed, "link")
    link.set("rel", "search")
    link.set("type", "application/opensearchdescription+xml")
    link.set("href", f"{config.BASE_URL}/opds/opensearch.xml")
    return feed


def _link(parent, rel: str, type_: str, href: str) -> etree._Element:
    link = etree.SubElement(parent, "link")
    link.set("rel", rel)
    link.set("type", type_)
    link.set("href", href)
    return link


def _xml_response(feed: etree._Element, ct: str) -> Response:
    body = etree.tostring(
        feed, xml_declaration=True, encoding="UTF-8", pretty_print=True
    )
    return Response(content=body, media_type=ct)


def _pagination_links(
    feed: etree._Element, base_url: str, page: int, total: int, page_size: int
) -> None:
    """Add RFC 5005 prev/next links. base_url must already include any ?q= params."""
    sep = "&" if "?" in base_url else "?"
    if page > 0:
        _link(feed, "previous", ACQ_CT, f"{base_url}{sep}page={page - 1}")
    if (page + 1) * page_size < total:
        _link(feed, "next", ACQ_CT, f"{base_url}{sep}page={page + 1}")


def _opensearch_counts(
    feed: etree._Element, total: int, page: int, page_size: int
) -> None:
    etree.SubElement(feed, f"{{{OS_NS}}}totalResults").text = str(total)
    etree.SubElement(feed, f"{{{OS_NS}}}itemsPerPage").text = str(page_size)
    etree.SubElement(feed, f"{{{OS_NS}}}startIndex").text = str(page * page_size)


def _book_entry(feed: etree._Element, book, in_series: bool = False) -> None:
    """Render one book as an OPDS acquisition entry."""
    entry = etree.SubElement(feed, "entry")

    # ── Required Atom fields ──────────────────────────────────────────────────
    etree.SubElement(entry, "id").text = f"urn:uuid:{book.id}"
    etree.SubElement(entry, "updated").text = book.updated_at

    # KOReader uses <title> as the saved filename.
    # Format: "Series [N] Title" or just "Title" when no series.
    # <author> is omitted so it doesn't get appended to the filename.
    if book.series:
        if book.series_index is not None:
            n = int(book.series_index) if book.series_index == int(book.series_index) else book.series_index
            display_title = f"{book.series} [{n}] {book.title}"
        else:
            display_title = f"{book.series} {book.title}"
    else:
        display_title = book.title
    etree.SubElement(entry, "title").text = display_title

    if book.author:
        author = etree.SubElement(entry, "author")
        etree.SubElement(author, "name").text = book.author

    # ── Description / summary ─────────────────────────────────────────────────
    if book.description:
        summary = etree.SubElement(entry, "summary")
        summary.set("type", "text")
        # Truncate very long descriptions so KOReader doesn't choke
        summary.text = book.description[:2000]

    # ── Dublin Core metadata ──────────────────────────────────────────────────
    if book.language:
        etree.SubElement(entry, f"{{{DC_NS}}}language").text = book.language
    if book.publisher:
        etree.SubElement(entry, f"{{{DC_NS}}}publisher").text = book.publisher
    if book.published:
        etree.SubElement(entry, f"{{{DC_NS}}}issued").text = book.published[:10]

    # ── Series (Calibre convention — read by KOReader) ────────────────────────
    if book.series:
        series_el = etree.SubElement(entry, f"{{{CALIBRE_NS}}}series")
        series_el.text = book.series
        if book.series_index is not None:
            idx = (
                int(book.series_index)
                if book.series_index == int(book.series_index)
                else book.series_index
            )
            etree.SubElement(
                entry, f"{{{CALIBRE_NS}}}series_index"
            ).text = str(idx)

    # ── Cover image links ─────────────────────────────────────────────────────
    if book.cover_path:
        cover_url = f"{config.BASE_URL}/covers/{book.id}.jpg"
        _link(entry, REL_THUMBNAIL, "image/jpeg", cover_url)
        _link(entry, REL_IMAGE,     "image/jpeg", cover_url)

    # ── Acquisition link ──────────────────────────────────────────────────────
    mime = MIME_MAP.get(book.format.lower(), "application/octet-stream")
    _link(entry, REL_ACQ, mime, f"{config.BASE_URL}/api/download/{book.id}")


def _nav_entry(
    feed: etree._Element,
    entry_id: str,
    title: str,
    href: str,
    ct: str,
    content: str = "",
    updated: str = "",
    cover_url: Optional[str] = None,
) -> None:
    """Render one entry in a navigation feed."""
    e = etree.SubElement(feed, "entry")
    etree.SubElement(e, "id").text = entry_id
    etree.SubElement(e, "title").text = title
    etree.SubElement(e, "updated").text = updated or _now()
    if content:
        c = etree.SubElement(e, "content")
        c.set("type", "text")
        c.text = content
    if cover_url:
        _link(e, REL_THUMBNAIL, "image/jpeg", cover_url)
    _link(e, "subsection", ct, href)


# ── Root ──────────────────────────────────────────────────────────────────────

@router.get("", response_class=Response)
@router.get("/", response_class=Response)
async def opds_root(db: aiosqlite.Connection = Depends(get_db)):
    rows = await db.execute_fetchall(
        "SELECT COUNT(*), MAX(updated_at) FROM books"
    )
    total, last_updated = rows[0][0], rows[0][1] or _now()

    feed = _feed("urn:opds:root", config.SERVER_TITLE, last_updated)
    _link(feed, "self",  NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")

    _nav_entry(feed, "urn:opds:all",     "All Books",
               f"{config.BASE_URL}/opds/all",     ACQ_CT,
               f"{total} book{'s' if total != 1 else ''} in library")
    _nav_entry(feed, "urn:opds:recent",  "Recently Added",
               f"{config.BASE_URL}/opds/recent",  ACQ_CT,
               "Latest additions")
    _nav_entry(feed, "urn:opds:authors", "Browse by Author",
               f"{config.BASE_URL}/opds/authors", NAV_CT)
    _nav_entry(feed, "urn:opds:series",  "Browse by Series",
               f"{config.BASE_URL}/opds/series",  NAV_CT)
    _nav_entry(feed, "urn:opds:tags",    "Browse by Tag",
               f"{config.BASE_URL}/opds/tags",    NAV_CT)

    return _xml_response(feed, NAV_CT)


# ── Acquisition feeds ─────────────────────────────────────────────────────────

@router.get("/all", response_class=Response)
async def opds_all(
    page: int = Query(0, ge=0), db: aiosqlite.Connection = Depends(get_db)
):
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE, order_by="title"
    )
    feed = _feed("urn:opds:all", "All Books")
    _link(feed, "self",  ACQ_CT, f"{config.BASE_URL}/opds/all")
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds")
    _opensearch_counts(feed, total, page, config.PAGE_SIZE)
    _pagination_links(feed, f"{config.BASE_URL}/opds/all", page, total, config.PAGE_SIZE)
    for book in books:
        _book_entry(feed, book)
    return _xml_response(feed, ACQ_CT)


@router.get("/recent", response_class=Response)
async def opds_recent(
    page: int = Query(0, ge=0), db: aiosqlite.Connection = Depends(get_db)
):
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE, order_by="added_at DESC"
    )
    feed = _feed("urn:opds:recent", "Recently Added")
    _link(feed, "self",  ACQ_CT, f"{config.BASE_URL}/opds/recent")
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds")
    _opensearch_counts(feed, total, page, config.PAGE_SIZE)
    _pagination_links(feed, f"{config.BASE_URL}/opds/recent", page, total, config.PAGE_SIZE)
    for book in books:
        _book_entry(feed, book)
    return _xml_response(feed, ACQ_CT)


# ── Authors ───────────────────────────────────────────────────────────────────

@router.get("/authors", response_class=Response)
async def opds_authors(db: aiosqlite.Connection = Depends(get_db)):
    authors = await database.get_authors(db)
    feed = _feed("urn:opds:authors", "Browse by Author")
    _link(feed, "self",  NAV_CT, f"{config.BASE_URL}/opds/authors")
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds")
    for a in authors:
        name = a["author"]
        href = f"{config.BASE_URL}/opds/authors/{_quote(name)}"
        cover_url = None
        if a.get("cover_path"):
            bid = a["cover_path"].split("/")[-1].split(".")[0]
            cover_url = f"{config.BASE_URL}/covers/{bid}.jpg"
        _nav_entry(
            feed, f"urn:opds:author:{_quote(name)}", name, href, ACQ_CT,
            content=f"{a['book_count']} book{'s' if a['book_count'] != 1 else ''}",
            cover_url=cover_url,
        )
    return _xml_response(feed, NAV_CT)


@router.get("/authors/{author_name}", response_class=Response)
async def opds_author_books(
    author_name: str,
    page: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    # FastAPI already URL-decodes path params — no manual unquote needed
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE,
        author=author_name,
        order_by="series NULLS LAST, series_index NULLS LAST, title",
    )
    base = f"{config.BASE_URL}/opds/authors/{_quote(author_name)}"
    feed = _feed(f"urn:opds:author:{_quote(author_name)}", author_name)
    _link(feed, "self",  ACQ_CT, base)
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds/authors")
    _opensearch_counts(feed, total, page, config.PAGE_SIZE)
    _pagination_links(feed, base, page, total, config.PAGE_SIZE)
    for book in books:
        _book_entry(feed, book)
    return _xml_response(feed, ACQ_CT)


# ── Series ────────────────────────────────────────────────────────────────────

@router.get("/series", response_class=Response)
async def opds_series(db: aiosqlite.Connection = Depends(get_db)):
    series_list = await database.get_series_list(db)
    feed = _feed("urn:opds:series", "Browse by Series")
    _link(feed, "self",  NAV_CT, f"{config.BASE_URL}/opds/series")
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds")
    for s in series_list:
        name = s["series"]
        href = f"{config.BASE_URL}/opds/series/{_quote(name)}"
        cover_url = None
        if s.get("cover_path"):
            bid = s["cover_path"].split("/")[-1].split(".")[0]
            cover_url = f"{config.BASE_URL}/covers/{bid}.jpg"
        _nav_entry(
            feed, f"urn:opds:series:{_quote(name)}", name, href, ACQ_CT,
            content=f"{s['book_count']} book{'s' if s['book_count'] != 1 else ''}",
            cover_url=cover_url,
        )
    return _xml_response(feed, NAV_CT)


@router.get("/series/{series_name}", response_class=Response)
async def opds_series_books(
    series_name: str,
    page: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE,
        series=series_name,
        order_by="series_index NULLS LAST, title",
    )
    base = f"{config.BASE_URL}/opds/series/{_quote(series_name)}"
    feed = _feed(f"urn:opds:series:{_quote(series_name)}", series_name)
    _link(feed, "self",  ACQ_CT, base)
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds/series")
    _opensearch_counts(feed, total, page, config.PAGE_SIZE)
    _pagination_links(feed, base, page, total, config.PAGE_SIZE)
    for book in books:
        _book_entry(feed, book)
    return _xml_response(feed, ACQ_CT)


# ── Tags ──────────────────────────────────────────────────────────────────────

@router.get("/tags", response_class=Response)
async def opds_tags(db: aiosqlite.Connection = Depends(get_db)):
    tags = await database.get_tags(db)
    feed = _feed("urn:opds:tags", "Browse by Tag")
    _link(feed, "self",  NAV_CT, f"{config.BASE_URL}/opds/tags")
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds")
    for tag in tags:
        _nav_entry(
            feed, f"urn:opds:tag:{tag.id}", tag.name,
            f"{config.BASE_URL}/opds/tags/{_quote(tag.name)}", ACQ_CT,
        )
    return _xml_response(feed, NAV_CT)


@router.get("/tags/{tag_name}", response_class=Response)
async def opds_tag_books(
    tag_name: str,
    page: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE, tag=tag_name
    )
    base = f"{config.BASE_URL}/opds/tags/{_quote(tag_name)}"
    feed = _feed(f"urn:opds:tag:{_quote(tag_name)}", f"Tag: {tag_name}")
    _link(feed, "self",  ACQ_CT, base)
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds/tags")
    _opensearch_counts(feed, total, page, config.PAGE_SIZE)
    _pagination_links(feed, base, page, total, config.PAGE_SIZE)
    for book in books:
        _book_entry(feed, book)
    return _xml_response(feed, ACQ_CT)


# ── Search ────────────────────────────────────────────────────────────────────

@router.get("/search", response_class=Response)
async def opds_search(
    q: str = Query(""),
    page: int = Query(0, ge=0),
    db: aiosqlite.Connection = Depends(get_db),
):
    books, total = await database.get_books(
        db, page=page, page_size=config.PAGE_SIZE, search=q
    )
    q_enc = urllib.parse.quote(q, safe="")
    base = f"{config.BASE_URL}/opds/search?q={q_enc}"
    feed = _feed("urn:opds:search", f"Search: {q}")
    _link(feed, "self",  ACQ_CT, base)
    _link(feed, "start", NAV_CT, f"{config.BASE_URL}/opds")
    _link(feed, "up",    NAV_CT, f"{config.BASE_URL}/opds")
    _opensearch_counts(feed, total, page, config.PAGE_SIZE)
    _pagination_links(feed, base, page, total, config.PAGE_SIZE)
    for book in books:
        _book_entry(feed, book)
    return _xml_response(feed, ACQ_CT)


# ── OpenSearch description ────────────────────────────────────────────────────

@router.get("/opensearch.xml", response_class=Response)
async def opensearch_description():
    # KOReader reads this to build its search URL template
    title = config.SERVER_TITLE.replace("&", "&amp;").replace("<", "&lt;")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">\n'
        f'  <ShortName>{title}</ShortName>\n'
        f'  <Description>Search {title}</Description>\n'
        '  <InputEncoding>UTF-8</InputEncoding>\n'
        '  <OutputEncoding>UTF-8</OutputEncoding>\n'
        f'  <Url type="{ACQ_CT}"\n'
        f'       template="{config.BASE_URL}/opds/search?q={{searchTerms}}&amp;page=0"/>\n'
        '</OpenSearchDescription>'
    )
    return Response(content=xml.encode("utf-8"),
                    media_type="application/opensearchdescription+xml")
