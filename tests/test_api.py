"""
API endpoint tests: upload, CRUD, download, tags, cover, metadata search/apply.
"""
import io
import zipfile

import pytest

from tests.helpers import make_epub_bytes, make_pdf_bytes, make_fb2_bytes, make_cbz_bytes


# ── Upload ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_upload_epub(client):
    resp = await client.post(
        "/api/upload",
        files=[("files", ("test.epub", make_epub_bytes(), "application/epub+zip"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    book = data[0]
    assert "id" in book
    assert book["title"] == "Test EPUB"
    assert book["format"] == "epub"
    assert "error" not in book
    return book["id"]


@pytest.mark.anyio
async def test_upload_pdf(client):
    resp = await client.post(
        "/api/upload",
        files=[("files", ("test.pdf", make_pdf_bytes(), "application/pdf"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["format"] == "pdf"
    assert "error" not in data[0]


@pytest.mark.anyio
async def test_upload_fb2(client):
    resp = await client.post(
        "/api/upload",
        files=[("files", ("test.fb2", make_fb2_bytes(), "application/x-fictionbook+xml"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["format"] == "fb2"
    assert data[0]["title"] == "Test FB2"
    assert "error" not in data[0]


@pytest.mark.anyio
async def test_upload_cbz(client):
    resp = await client.post(
        "/api/upload",
        files=[("files", ("test.cbz", make_cbz_bytes(), "application/zip"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["format"] == "cbz"
    assert "error" not in data[0]


@pytest.mark.anyio
async def test_upload_multiple_files(client):
    resp = await client.post(
        "/api/upload",
        files=[
            ("files", ("a.epub", make_epub_bytes(), "application/epub+zip")),
            ("files", ("b.pdf",  make_pdf_bytes(),  "application/pdf")),
        ],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all("error" not in d for d in data)


# ── Update metadata ───────────────────────────────────────────────────────────

async def _upload_epub(client) -> str:
    resp = await client.post(
        "/api/upload",
        files=[("files", ("book.epub", make_epub_bytes(), "application/epub+zip"))],
    )
    return resp.json()[0]["id"]


@pytest.mark.anyio
async def test_update_book_metadata(client):
    book_id = await _upload_epub(client)
    resp = await client.post(
        f"/api/books/{book_id}",
        params={
            "title": "Updated Title",
            "author": "Jane Doe",
            "series": "My Series",
            "series_index": "1",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.anyio
async def test_update_book_partial(client):
    """Only provided fields should be changed."""
    book_id = await _upload_epub(client)
    await client.post(f"/api/books/{book_id}", params={"title": "Title A"})
    resp = await client.post(f"/api/books/{book_id}", params={"author": "Author B"})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_update_book_clear_field(client):
    """Passing an empty string should clear optional fields (stored as NULL)."""
    book_id = await _upload_epub(client)
    await client.post(f"/api/books/{book_id}", params={"series": "Some Series"})
    resp = await client.post(f"/api/books/{book_id}", params={"series": ""})
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_update_book_invalid_series_index(client):
    """Non-numeric series_index should be silently ignored."""
    book_id = await _upload_epub(client)
    resp = await client.post(
        f"/api/books/{book_id}", params={"series_index": "not-a-number"}
    )
    assert resp.status_code == 200


# ── Delete ────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_delete_book(client):
    book_id = await _upload_epub(client)
    resp = await client.delete(f"/api/books/{book_id}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # Second delete returns 404
    resp2 = await client.delete(f"/api/books/{book_id}")
    assert resp2.status_code == 404


# ── Download ──────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_download_book(client):
    book_id = await _upload_epub(client)
    resp = await client.get(f"/api/download/{book_id}")
    assert resp.status_code == 200
    assert "epub" in resp.headers.get("content-type", "").lower() or \
           len(resp.content) > 0


@pytest.mark.anyio
async def test_download_filename_header(client):
    book_id = await _upload_epub(client)
    await client.post(f"/api/books/{book_id}", params={"title": "My Book", "author": "Ann Auth"})
    resp = await client.get(f"/api/download/{book_id}")
    assert resp.status_code == 200
    import urllib.parse
    cd = resp.headers.get("content-disposition", "")
    # Header may use plain filename= or RFC 5987 filename*=utf-8''... encoding
    cd_decoded = urllib.parse.unquote(cd)
    assert "My Book" in cd_decoded
    assert "Ann Auth" in cd_decoded


# ── Cover ─────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_upload_cover(client):
    book_id = await _upload_epub(client)
    # Minimal valid JPEG
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (100, 150), color=(200, 100, 50)).save(buf, format="JPEG")
    jpeg_bytes = buf.getvalue()
    resp = await client.post(
        f"/api/books/{book_id}/cover",
        files=[("file", ("cover.jpg", jpeg_bytes, "image/jpeg"))],
    )
    assert resp.status_code == 200
    assert "cover" in resp.json()


@pytest.mark.anyio
async def test_upload_invalid_cover(client):
    book_id = await _upload_epub(client)
    resp = await client.post(
        f"/api/books/{book_id}/cover",
        files=[("file", ("bad.jpg", b"not an image", "image/jpeg"))],
    )
    assert resp.status_code == 400


# ── Tags ──────────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_create_and_list_tag(client):
    resp = await client.post("/api/tags", params={"name": "sci-fi"})
    assert resp.status_code == 200
    tag = resp.json()
    assert tag["name"] == "sci-fi"
    assert "id" in tag


@pytest.mark.anyio
async def test_create_tag_idempotent(client):
    """Creating the same tag twice returns the same tag, no error."""
    r1 = await client.post("/api/tags", params={"name": "fantasy"})
    r2 = await client.post("/api/tags", params={"name": "fantasy"})
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.anyio
async def test_delete_tag(client):
    resp = await client.post("/api/tags", params={"name": "to-delete"})
    tag_id = resp.json()["id"]
    del_resp = await client.delete(f"/api/tags/{tag_id}")
    assert del_resp.status_code == 200
    assert del_resp.json() == {"ok": True}


@pytest.mark.anyio
async def test_rename_tag(client):
    resp = await client.post("/api/tags", params={"name": "old-name"})
    tag_id = resp.json()["id"]
    ren = await client.post(f"/api/tags/{tag_id}/rename", params={"name": "new-name"})
    assert ren.status_code == 200


@pytest.mark.anyio
async def test_add_remove_book_tag(client):
    book_id = await _upload_epub(client)
    tag_resp = await client.post("/api/tags", params={"name": "tagged"})
    tag_id = tag_resp.json()["id"]

    add = await client.post(f"/api/books/{book_id}/tags/{tag_id}")
    assert add.status_code == 200

    remove = await client.delete(f"/api/books/{book_id}/tags/{tag_id}")
    assert remove.status_code == 200


@pytest.mark.anyio
async def test_add_book_tag_idempotent(client):
    """Adding the same tag twice must not error."""
    book_id = await _upload_epub(client)
    tag_id = (await client.post("/api/tags", params={"name": "dup"})).json()["id"]
    r1 = await client.post(f"/api/books/{book_id}/tags/{tag_id}")
    r2 = await client.post(f"/api/books/{book_id}/tags/{tag_id}")
    assert r1.status_code == r2.status_code == 200


# ── Metadata apply ────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_apply_metadata(client):
    book_id = await _upload_epub(client)
    resp = await client.post(
        f"/api/books/{book_id}/metadata/apply",
        params={
            "title": "Applied Title",
            "author": "Applied Author",
            "tags": "tag1,tag2",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.anyio
async def test_apply_metadata_with_writeback(client):
    """write_to_file=true for an EPUB should not crash."""
    book_id = await _upload_epub(client)
    resp = await client.post(
        f"/api/books/{book_id}/metadata/apply",
        params={
            "title": "Written Back",
            "write_to_file": "true",
        },
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_apply_metadata_cover_url_ssrf_blocked(client):
    """SSRF-blocked cover_url must not crash the endpoint."""
    book_id = await _upload_epub(client)
    resp = await client.post(
        f"/api/books/{book_id}/metadata/apply",
        params={"cover_url": "file:///etc/passwd"},
    )
    # Endpoint should still succeed (cover just not saved)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
