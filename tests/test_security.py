"""
Security-focused tests: SSRF, path traversal, upload limits, SQL injection surface,
ZIP slip, and XML XXE hardening.
"""
import io
import zipfile

import pytest
import pytest_asyncio


# ── SSRF guard ────────────────────────────────────────────────────────────────

class TestSsrfGuard:
    """_is_safe_url() must reject dangerous URL patterns."""

    def setup_method(self):
        from routers.api import _is_safe_url
        self.is_safe = _is_safe_url

    def test_http_url_is_safe(self):
        # A regular https URL should be allowed
        assert self.is_safe("https://covers.openlibrary.org/b/isbn/9781234567890-M.jpg") is True

    def test_file_scheme_blocked(self):
        assert self.is_safe("file:///etc/passwd") is False

    def test_data_scheme_blocked(self):
        assert self.is_safe("data:text/plain;base64,aGVsbG8=") is False

    def test_ftp_scheme_blocked(self):
        assert self.is_safe("ftp://example.com/file.jpg") is False

    def test_localhost_blocked(self):
        assert self.is_safe("http://localhost/secret") is False
        assert self.is_safe("http://127.0.0.1/secret") is False

    def test_loopback_ipv6_blocked(self):
        assert self.is_safe("http://[::1]/secret") is False

    def test_private_ip_blocked(self):
        assert self.is_safe("http://192.168.1.1/") is False
        assert self.is_safe("http://10.0.0.1/") is False
        assert self.is_safe("http://172.16.0.1/") is False

    def test_link_local_blocked(self):
        # AWS IMDS
        assert self.is_safe("http://169.254.169.254/latest/meta-data/") is False

    def test_empty_url_blocked(self):
        assert self.is_safe("") is False

    def test_no_host_blocked(self):
        assert self.is_safe("http:///path") is False


# ── Upload size limit ─────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_upload_file_too_large(client):
    """Files over MAX_UPLOAD_BYTES should be rejected with an error entry."""
    from routers.api import MAX_UPLOAD_BYTES
    oversized = b"A" * (MAX_UPLOAD_BYTES + 1)
    resp = await client.post(
        "/api/upload",
        files=[("files", ("big.epub", oversized, "application/epub+zip"))],
    )
    assert resp.status_code == 200
    result = resp.json()
    assert len(result) == 1
    assert "error" in result[0]
    assert "too large" in result[0]["error"].lower()


# ── Format detection: unsupported extension rejected ─────────────────────────

@pytest.mark.anyio
async def test_upload_unsupported_format(client):
    resp = await client.post(
        "/api/upload",
        files=[("files", ("malware.exe", b"MZx\x00", "application/octet-stream"))],
    )
    assert resp.status_code == 200
    result = resp.json()
    assert "error" in result[0]


# ── Book ID validation: non-UUID IDs return 404, not server errors ────────────

@pytest.mark.anyio
async def test_download_unknown_id_returns_404(client):
    resp = await client.get("/api/download/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_update_book_unknown_id_returns_404(client):
    resp = await client.post("/api/books/does-not-exist?title=X")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_delete_book_unknown_id_returns_404(client):
    resp = await client.delete("/api/books/does-not-exist")
    assert resp.status_code == 404


# ── SQL injection surface: update_book column whitelist ───────────────────────

@pytest.mark.anyio
async def test_update_book_rejects_unknown_column(client):
    """database.update_book must reject dict keys that aren't book columns."""
    import database, aiosqlite
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        with pytest.raises(ValueError, match="Unknown book column"):
            await database.update_book(db, "fake-id", {"evil_col; DROP TABLE books;--": "x"})


# ── ORDER BY whitelist ────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_get_books_rejects_sql_injection_order_by():
    """get_books() must raise ValueError for non-whitelisted order_by."""
    import aiosqlite, database
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        with pytest.raises(ValueError, match="Invalid order_by"):
            await database.get_books(db, order_by="added_at; DROP TABLE books--")


@pytest.mark.anyio
async def test_get_books_valid_order_by():
    """Legitimate order_by values must not raise."""
    import aiosqlite, database
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        books, _ = await database.get_books(db, order_by="title")
        assert isinstance(books, list)
        books, _ = await database.get_books(db, order_by="added_at DESC")
        assert isinstance(books, list)
        books, _ = await database.get_books(
            db, order_by="series NULLS LAST, series_index NULLS LAST, title"
        )
        assert isinstance(books, list)


# ── ZIP slip: CBZ rewrite must not propagate traversal paths ─────────────────

def test_cbz_zip_slip_entries_are_skipped(tmp_path):
    """A CBZ with path-traversal entries must not have them in the output."""
    import zipfile
    from pathlib import Path

    cbz = tmp_path / "test.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("page1.jpg", b"\xff\xd8\xff\xd9")
        # Evil entry
        zf.writestr("../../evil.sh", b"#!/bin/bash\nrm -rf /")

    from routers.api import _write_metadata_to_cbz
    _write_metadata_to_cbz(cbz, {"title": "Safe Title"})

    with zipfile.ZipFile(cbz) as zf:
        names = zf.namelist()
    assert not any(".." in n or n.startswith("/") for n in names), (
        f"Traversal paths survived ZIP rewrite: {names}"
    )


def test_cbz_zip_slip_absolute_paths_skipped(tmp_path):
    cbz = tmp_path / "test.cbz"
    with zipfile.ZipFile(cbz, "w") as zf:
        zf.writestr("page1.jpg", b"\xff\xd8\xff\xd9")
        zf.writestr("/etc/cron.d/evil", b"* * * * * root /bin/sh /tmp/evil.sh")

    from routers.api import _write_metadata_to_cbz
    _write_metadata_to_cbz(cbz, {"title": "T"})

    with zipfile.ZipFile(cbz) as zf:
        names = zf.namelist()
    assert not any(n.startswith("/") for n in names)


# ── XML XXE: lxml parsers must use hardened options ───────────────────────────

def test_fb2_extraction_rejects_xxe(tmp_path):
    """XXE payload in an FB2 file must not exfiltrate /etc/passwd content."""
    evil_fb2 = tmp_path / "evil.fb2"
    evil_fb2.write_bytes(b"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info>
<genre>fiction</genre>
<author><first-name>&xxe;</first-name><last-name>X</last-name></author>
<book-title>Evil</book-title>
<lang>en</lang>
</title-info></description>
<body><section><p>x</p></section></body>
</FictionBook>""")
    from routers.api import _extract_fb2
    meta = _extract_fb2(evil_fb2)
    # Either extraction fails (returns {}) or author must not contain passwd content
    author = meta.get("author", "") or ""
    assert "root:" not in author, "XXE read /etc/passwd via FB2 extraction"


def test_fb2_writeback_rejects_xxe(tmp_path):
    """XXE payload in FB2 write-back must not cause file reads."""
    evil_fb2 = tmp_path / "evil.fb2"
    evil_fb2.write_bytes(b"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">
<description><title-info>
<genre>fiction</genre>
<book-title>&xxe;</book-title>
<lang>en</lang>
</title-info></description>
<body><section><p>x</p></section></body>
</FictionBook>""")
    from routers.api import _write_metadata_to_fb2
    # Must not crash and must not read system files
    _write_metadata_to_fb2(evil_fb2, {"title": "Safe"})
    content = evil_fb2.read_text(encoding="utf-8")
    assert "root:" not in content
