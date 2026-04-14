"""
Database layer tests: CRUD, search/filter, pagination, tag maps, aggregates.
"""
import uuid
from datetime import datetime, timezone

import aiosqlite
import pytest

import database
from config import DB_PATH
from models import Book


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _book(overrides=None) -> Book:
    bid = str(uuid.uuid4())
    b = Book(
        id=bid,
        title="Test Book",
        filename=f"{bid}.epub",
        file_path=f"books/{bid}.epub",
        format="epub",
        added_at=_now(),
        updated_at=_now(),
    )
    if overrides:
        for k, v in overrides.items():
            setattr(b, k, v)
    return b


async def _db():
    conn = aiosqlite.connect(DB_PATH)
    db = await conn.__aenter__()
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    return db, conn


@pytest.mark.anyio
async def test_insert_and_get_book():
    db, conn = await _db()
    try:
        b = _book({"title": "Unique Title CRUD"})
        await database.insert_book(db, b)
        fetched = await database.get_book(db, b.id)
        assert fetched is not None
        assert fetched.title == "Unique Title CRUD"
        assert fetched.format == "epub"
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_book_not_found():
    db, conn = await _db()
    try:
        result = await database.get_book(db, "no-such-id")
        assert result is None
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_update_book():
    db, conn = await _db()
    try:
        b = _book({"title": "Before Update"})
        await database.insert_book(db, b)
        await database.update_book(db, b.id, {"title": "After Update", "author": "New Author"})
        fetched = await database.get_book(db, b.id)
        assert fetched.title == "After Update"
        assert fetched.author == "New Author"
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_delete_book():
    db, conn = await _db()
    try:
        b = _book()
        await database.insert_book(db, b)
        await database.delete_book(db, b.id)
        assert await database.get_book(db, b.id) is None
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_books_search():
    db, conn = await _db()
    try:
        b = _book({"title": "Unique Searchable XYZ", "author": "SearchAuthor"})
        await database.insert_book(db, b)
        results, total = await database.get_books(db, search="Searchable XYZ")
        assert any(r.id == b.id for r in results)
        assert total >= 1
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_books_no_match():
    db, conn = await _db()
    try:
        results, total = await database.get_books(db, search="zzzNOTHINGzzzNOTHING")
        assert results == []
        assert total == 0
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_books_by_author():
    db, conn = await _db()
    try:
        author = "UniqueAuthorABC"
        b = _book({"author": author})
        await database.insert_book(db, b)
        results, _ = await database.get_books(db, author=author)
        assert any(r.id == b.id for r in results)
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_books_by_series():
    db, conn = await _db()
    try:
        series = "UniqueSeries999"
        b = _book({"series": series, "series_index": 1.0})
        await database.insert_book(db, b)
        results, _ = await database.get_books(db, series=series)
        assert any(r.id == b.id for r in results)
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_books_pagination():
    db, conn = await _db()
    try:
        # Insert 3 books with a unique tag for isolation
        ids = []
        for i in range(3):
            b = _book({"title": f"PaginationBook{i} PGTEST"})
            await database.insert_book(db, b)
            ids.append(b.id)
        # Page 0, size 2
        p0, total = await database.get_books(db, search="PGTEST", page=0, page_size=2)
        assert len(p0) == 2
        assert total == 3
        # Page 1, size 2
        p1, _ = await database.get_books(db, search="PGTEST", page=1, page_size=2)
        assert len(p1) == 1
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_books_by_tag():
    db, conn = await _db()
    try:
        b = _book()
        await database.insert_book(db, b)
        tag = await database.create_tag(db, "unique-filter-tag-xyz")
        await database.add_book_tag(db, b.id, tag.id)

        results, total = await database.get_books(db, tag="unique-filter-tag-xyz")
        assert any(r.id == b.id for r in results)
        assert total >= 1
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_create_tag_idempotent():
    db, conn = await _db()
    try:
        t1 = await database.create_tag(db, "idempotent-tag")
        t2 = await database.create_tag(db, "idempotent-tag")
        assert t1.id == t2.id
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_rename_tag():
    db, conn = await _db()
    try:
        tag = await database.create_tag(db, "before-rename")
        await database.rename_tag(db, tag.id, "after-rename")
        tags = await database.get_tags(db)
        names = [t.name for t in tags]
        assert "after-rename" in names
        assert "before-rename" not in names
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_delete_tag_cascades():
    """Deleting a tag must remove its book_tags rows too."""
    db, conn = await _db()
    try:
        b = _book()
        await database.insert_book(db, b)
        tag = await database.create_tag(db, "cascade-tag")
        await database.add_book_tag(db, b.id, tag.id)
        await database.delete_tag(db, tag.id)
        book_tags = await database.get_book_tags(db, b.id)
        assert not any(t.id == tag.id for t in book_tags)
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_book_tags_map():
    db, conn = await _db()
    try:
        b1, b2 = _book(), _book()
        await database.insert_book(db, b1)
        await database.insert_book(db, b2)
        t1 = await database.create_tag(db, "map-tag-a")
        t2 = await database.create_tag(db, "map-tag-b")
        await database.add_book_tag(db, b1.id, t1.id)
        await database.add_book_tag(db, b1.id, t2.id)
        await database.add_book_tag(db, b2.id, t1.id)

        tag_map = await database.get_book_tags_map(db, [b1.id, b2.id])
        assert set(tag_map[b1.id]) == {"map-tag-a", "map-tag-b"}
        assert tag_map[b2.id] == ["map-tag-a"]
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_book_tags_map_empty_input():
    db, conn = await _db()
    try:
        result = await database.get_book_tags_map(db, [])
        assert result == {}
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_authors():
    db, conn = await _db()
    try:
        author = "AuthorListTest"
        await database.insert_book(db, _book({"author": author}))
        authors = await database.get_authors(db)
        assert any(a["author"] == author for a in authors)
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_get_series_list():
    db, conn = await _db()
    try:
        series = "SeriesListTest"
        await database.insert_book(db, _book({"series": series, "series_index": 1.0}))
        sl = await database.get_series_list(db)
        assert any(s["series"] == series for s in sl)
    finally:
        await conn.__aexit__(None, None, None)


@pytest.mark.anyio
async def test_update_book_unknown_column_raises():
    db, conn = await _db()
    try:
        with pytest.raises(ValueError, match="Unknown book column"):
            await database.update_book(db, "x", {"injected_col": "val"})
    finally:
        await conn.__aexit__(None, None, None)
