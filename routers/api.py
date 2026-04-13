import hashlib
import io
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite
import httpx
import magic
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from PIL import Image

import database
import config
from database import get_db
from models import Book
from metadata import search_metadata

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

SUPPORTED_MIME = {
    "application/epub+zip": "epub",
    "application/pdf": "pdf",
    "application/x-mobipocket-ebook": "mobi",
    "application/x-fictionbook+xml": "fb2",
    "application/xml": None,   # needs extension fallback (fb2 often detected as xml)
    "text/xml": None,          # same
    "application/zip": None,   # fb2.zip — extension fallback
    "application/octet-stream": None,
}
SUPPORTED_EXT = {"epub", "pdf", "mobi", "azw", "azw3", "cbz", "fb2", "txt"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Metadata extraction ───────────────────────────────────────────────────────

def _extract_epub(path: Path) -> dict:
    try:
        import ebooklib
        from ebooklib import epub as epublib

        book = epublib.read_epub(str(path), options={"ignore_ncx": True})
        meta: dict = {}

        def _get(name):
            items = book.get_metadata("DC", name)
            return items[0][0] if items else None

        meta["title"] = _get("title")
        meta["author"] = _get("creator")
        meta["description"] = _get("description")
        meta["publisher"] = _get("publisher")
        meta["language"] = _get("language")
        meta["published"] = _get("date")

        # Cover image
        cover_bytes = None
        for item in book.get_items_of_type(ebooklib.ITEM_COVER):
            cover_bytes = item.get_content()
            break
        if not cover_bytes:
            for item in book.get_items_of_type(ebooklib.ITEM_IMAGE):
                if "cover" in (item.get_name() or "").lower():
                    cover_bytes = item.get_content()
                    break
        meta["cover_bytes"] = cover_bytes
        return meta
    except Exception as e:
        logger.warning("EPUB extraction failed: %s", e)
        return {}


def _extract_pdf(path: Path) -> dict:
    try:
        import fitz  # pymupdf

        doc = fitz.open(str(path))
        info = doc.metadata or {}
        meta: dict = {
            "title": info.get("title") or None,
            "author": info.get("author") or None,
            "description": info.get("subject") or None,
            "publisher": info.get("creator") or None,
        }
        # Render first page as cover
        if doc.page_count > 0:
            page = doc[0]
            mat = fitz.Matrix(1.5, 1.5)
            pix = page.get_pixmap(matrix=mat)
            meta["cover_bytes"] = pix.tobytes("jpeg")
        doc.close()
        return meta
    except Exception as e:
        logger.warning("PDF extraction failed: %s", e)
        return {}


def _extract_mobi(path: Path) -> dict:
    try:
        import mobi

        tempdir, filepath = mobi.extract(str(path))
        # mobi.extract returns a path to the extracted EPUB or HTML
        meta: dict = {}
        # Try reading as epub if extracted
        epub_path = Path(filepath)
        if epub_path.suffix.lower() == ".epub":
            meta = _extract_epub(epub_path)
        return meta
    except Exception as e:
        logger.warning("MOBI extraction failed: %s", e)
        return {}


def _extract_fb2(path: Path) -> dict:
    import base64
    import zipfile
    from lxml import etree

    try:
        content = path.read_bytes()

        # Support .fb2.zip — unzip and read the first .fb2 inside
        if content[:2] == b"PK":
            with zipfile.ZipFile(path) as zf:
                fb2_names = [n for n in zf.namelist() if n.lower().endswith(".fb2")]
                if not fb2_names:
                    return {}
                content = zf.read(fb2_names[0])

        root = etree.fromstring(content)

        # FB2 files may or may not declare a namespace
        ns = root.nsmap.get(None, "")
        def _tag(name: str) -> str:
            return f"{{{ns}}}{name}" if ns else name

        def _find(parent, *path):
            node = parent
            for part in path:
                node = node.find(_tag(part))
                if node is None:
                    return None
            return node

        def _text(parent, *path) -> Optional[str]:
            node = _find(parent, *path)
            return node.text.strip() if node is not None and node.text else None

        desc = _find(root, "description")
        if desc is None:
            return {}

        title_info = _find(desc, "title-info")
        publish_info = _find(desc, "publish-info")

        meta: dict = {}

        if title_info is not None:
            meta["title"] = _text(title_info, "book-title")

            # Author: assemble from first-name / middle-name / last-name
            author_node = _find(title_info, "author")
            if author_node is not None:
                parts = [
                    _text(author_node, "first-name"),
                    _text(author_node, "middle-name"),
                    _text(author_node, "last-name"),
                ]
                name = " ".join(p for p in parts if p)
                meta["author"] = name or None

            # Description (annotation → plain text)
            ann = _find(title_info, "annotation")
            if ann is not None:
                meta["description"] = " ".join(ann.itertext()).strip() or None

            meta["language"] = _text(title_info, "lang")

            # Series
            seq = _find(title_info, "sequence")
            if seq is not None:
                meta["series"] = seq.get("name")
                num = seq.get("number")
                if num:
                    try:
                        meta["series_index"] = float(num)
                    except ValueError:
                        pass

            # Cover: FB2 stores cover as a <binary> element referenced from <coverpage>
            coverpage = _find(title_info, "coverpage")
            if coverpage is not None:
                img_node = coverpage.find(_tag("image"))
                if img_node is not None:
                    # href is like "#cover.jpg" — the '#' references a <binary id="cover.jpg">
                    href = img_node.get("{http://www.w3.org/1999/xlink}href") or \
                           img_node.get("href", "")
                    binary_id = href.lstrip("#")
                    if binary_id:
                        for binary in root.iter(_tag("binary")):
                            if binary.get("id") == binary_id and binary.text:
                                try:
                                    meta["cover_bytes"] = base64.b64decode(
                                        binary.text.strip()
                                    )
                                except Exception:
                                    pass
                                break

        if publish_info is not None:
            meta["publisher"] = _text(publish_info, "publisher")
            year = _text(publish_info, "year")
            if year:
                meta["published"] = f"{year}-01-01"

        return meta

    except Exception as e:
        logger.warning("FB2 extraction failed: %s", e)
        return {}


def _save_cover(cover_bytes: bytes, book_id: str) -> Optional[str]:
    try:
        img = Image.open(io.BytesIO(cover_bytes)).convert("RGB")
        w, h = img.size
        if w > config.MAX_COVER_WIDTH:
            ratio = config.MAX_COVER_WIDTH / w
            img = img.resize((config.MAX_COVER_WIDTH, int(h * ratio)), Image.LANCZOS)
        out_path = config.COVERS_DIR / f"{book_id}.jpg"
        img.save(str(out_path), "JPEG", quality=85)
        return f"covers/{book_id}.jpg"
    except Exception as e:
        logger.warning("Cover save failed: %s", e)
        return None


async def _fetch_cover_from_url(url: str, book_id: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return _save_cover(resp.content, book_id)
    except Exception as e:
        logger.warning("Cover fetch from URL failed: %s", e)
        return None


def _detect_format(data: bytes, filename: str) -> Optional[str]:
    mime = magic.from_buffer(data, mime=True)
    fmt = SUPPORTED_MIME.get(mime)
    if fmt:
        return fmt
    ext = Path(filename).suffix.lstrip(".").lower()
    return ext if ext in SUPPORTED_EXT else None


def _write_metadata_to_epub(path: Path, fields: dict) -> None:
    """Write updated metadata back to the EPUB file."""
    try:
        import ebooklib
        from ebooklib import epub as epublib

        book = epublib.read_epub(str(path), options={"ignore_ncx": True})
        dc_map = {
            "title": "title",
            "author": "creator",
            "description": "description",
            "publisher": "publisher",
            "language": "language",
            "published": "date",
        }
        for field, dc_name in dc_map.items():
            if field in fields and fields[field] is not None:
                book.metadata["DC"] = {
                    k: v for k, v in book.metadata.get("DC", {}).items()
                    if k != dc_name
                }
                book.add_metadata("DC", dc_name, fields[field])
        epublib.write_epub(str(path), book)
    except Exception as e:
        logger.warning("EPUB metadata write-back failed: %s", e)


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload")
async def upload_books(
    files: list[UploadFile] = File(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    results = []
    for upload in files:
        data = await upload.read()
        fmt = _detect_format(data[:2048], upload.filename or "")
        if not fmt:
            results.append({"filename": upload.filename, "error": "Unsupported format"})
            continue

        book_id = str(uuid.uuid4())
        file_path = config.BOOKS_DIR / f"{book_id}.{fmt}"
        file_path.write_bytes(data)

        # Extract metadata
        extractors = {
            "epub": _extract_epub,
            "pdf": _extract_pdf,
            "mobi": _extract_mobi,
            "fb2": _extract_fb2,
        }
        meta = extractors.get(fmt, lambda p: {})(file_path)

        cover_path = None
        cover_bytes = meta.pop("cover_bytes", None)
        if cover_bytes:
            cover_path = _save_cover(cover_bytes, book_id)

        # Hash for duplicate detection (store in description comment, not DB field)
        # (future: add hash column — skipped for now)

        title = meta.get("title") or Path(upload.filename or "unknown").stem
        book = Book(
            id=book_id,
            title=title,
            author=meta.get("author"),
            description=meta.get("description"),
            publisher=meta.get("publisher"),
            language=meta.get("language") or "en",
            published=meta.get("published"),
            filename=upload.filename or f"{book_id}.{fmt}",
            file_path=f"books/{book_id}.{fmt}",
            file_size=len(data),
            format=fmt,
            cover_path=cover_path,
            series=meta.get("series"),
            series_index=meta.get("series_index"),
            added_at=_now(),
            updated_at=_now(),
        )
        await database.insert_book(db, book)
        results.append({
            "id": book.id,
            "title": book.title,
            "author": book.author,
            "format": book.format,
            "cover": f"/covers/{book_id}.jpg" if cover_path else None,
        })

    return JSONResponse(results)


# ── Book CRUD ─────────────────────────────────────────────────────────────────

@router.post("/books/{book_id}")
async def update_book(
    book_id: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    description: Optional[str] = None,
    publisher: Optional[str] = None,
    language: Optional[str] = None,
    published: Optional[str] = None,
    series: Optional[str] = None,
    series_index: Optional[str] = None,  # received as string, cast to float
    write_to_file: bool = Query(False),
    db: aiosqlite.Connection = Depends(get_db),
):
    book = await database.get_book(db, book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    fields: dict = {"updated_at": _now()}
    for k, v in [("title", title), ("author", author), ("description", description),
                 ("publisher", publisher), ("language", language), ("published", published),
                 ("series", series)]:
        if v is not None:
            fields[k] = v or None  # store empty string as NULL

    if series_index is not None:
        try:
            fields["series_index"] = float(series_index) if series_index else None
        except ValueError:
            pass

    await database.update_book(db, book_id, fields)

    if write_to_file and book.format == "epub":
        epub_path = config.BASE_DIR / book.file_path
        _write_metadata_to_epub(epub_path, {k: v for k, v in fields.items() if k != "updated_at"})

    return {"ok": True}


@router.delete("/books/{book_id}")
async def delete_book(book_id: str, db: aiosqlite.Connection = Depends(get_db)):
    book = await database.get_book(db, book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    book_file = config.BASE_DIR / book.file_path
    if book_file.exists():
        book_file.unlink()

    if book.cover_path:
        cover_file = config.BASE_DIR / book.cover_path
        if cover_file.exists():
            cover_file.unlink()

    await database.delete_book(db, book_id)
    return {"ok": True}


@router.post("/books/{book_id}/cover")
async def update_cover(
    book_id: str,
    file: UploadFile = File(...),
    db: aiosqlite.Connection = Depends(get_db),
):
    book = await database.get_book(db, book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    data = await file.read()
    cover_path = _save_cover(data, book_id)
    if not cover_path:
        raise HTTPException(400, "Invalid image file")

    await database.update_book(db, book_id, {"cover_path": cover_path, "updated_at": _now()})
    return {"cover": f"/covers/{book_id}.jpg"}


# ── Download with friendly filename ──────────────────────────────────────────

def _safe_name(text: str) -> str:
    """Remove characters illegal in filenames. Keeps non-ASCII (Cyrillic etc.)."""
    return re.sub(r'[\\/:*?"<>|]', "", text).strip()


def _download_filename(book) -> str:
    """
    Series [N] Title - Author.ext
    Title - Author.ext          (no series)
    Title.ext                   (no author either)
    """
    title  = _safe_name(book.title)  or "Unknown"
    author = _safe_name(book.author) if book.author else None

    if book.series:
        series = _safe_name(book.series)
        if book.series_index is not None:
            idx = (
                int(book.series_index)
                if book.series_index == int(book.series_index)
                else book.series_index
            )
            prefix = f"{series} [{idx}]"
        else:
            prefix = series
        name = f"{prefix} {title}"
    else:
        name = title

    if author:
        name = f"{name} - {author}"

    return f"{name}.{book.format}"


@router.get("/download/{book_id}")
async def download_book(book_id: str, db: aiosqlite.Connection = Depends(get_db)):
    book = await database.get_book(db, book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    file_path = config.BASE_DIR / book.file_path
    if not file_path.exists():
        raise HTTPException(404, "File not found")
    filename = _download_filename(book)
    mime_map = {
        "epub": "application/epub+zip",
        "pdf": "application/pdf",
        "mobi": "application/x-mobipocket-ebook",
        "fb2": "application/x-fictionbook+xml",
        "cbz": "application/x-cbz",
        "txt": "text/plain",
    }
    media_type = mime_map.get(book.format.lower(), "application/octet-stream")
    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )


# ── Tag CRUD ──────────────────────────────────────────────────────────────────

@router.post("/tags")
async def create_tag(name: str, db: aiosqlite.Connection = Depends(get_db)):
    tag = await database.create_tag(db, name.strip())
    return {"id": tag.id, "name": tag.name}


@router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await database.delete_tag(db, tag_id)
    return {"ok": True}


@router.post("/tags/{tag_id}/rename")
async def rename_tag(tag_id: int, name: str, db: aiosqlite.Connection = Depends(get_db)):
    await database.rename_tag(db, tag_id, name.strip())
    return {"ok": True}


@router.post("/books/{book_id}/tags/{tag_id}")
async def add_book_tag(book_id: str, tag_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await database.add_book_tag(db, book_id, tag_id)
    return {"ok": True}


@router.delete("/books/{book_id}/tags/{tag_id}")
async def remove_book_tag(book_id: str, tag_id: int, db: aiosqlite.Connection = Depends(get_db)):
    await database.remove_book_tag(db, book_id, tag_id)
    return {"ok": True}


# ── Metadata search ───────────────────────────────────────────────────────────

@router.get("/books/{book_id}/metadata/search")
async def search_book_metadata(
    book_id: str,
    q: Optional[str] = Query(None),
    author: str = Query(""),
    db: aiosqlite.Connection = Depends(get_db),
):
    book = await database.get_book(db, book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    query = q or book.title
    results = await search_metadata(query, author or (book.author or ""))
    return [
        {
            "source": r.source,
            "title": r.title,
            "author": r.author,
            "description": r.description,
            "publisher": r.publisher,
            "published": r.published,
            "language": r.language,
            "cover_url": r.cover_url,
            "isbn": r.isbn,
            "tags": r.tags,
            "series": r.series,
            "series_index": r.series_index,
        }
        for r in results
    ]


@router.post("/books/{book_id}/metadata/apply")
async def apply_metadata(
    book_id: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    description: Optional[str] = None,
    publisher: Optional[str] = None,
    published: Optional[str] = None,
    language: Optional[str] = None,
    cover_url: Optional[str] = None,
    tags: Optional[str] = None,  # comma-separated
    series: Optional[str] = None,
    series_index: Optional[str] = None,
    write_to_file: bool = Query(False),
    db: aiosqlite.Connection = Depends(get_db),
):
    book = await database.get_book(db, book_id)
    if not book:
        raise HTTPException(404, "Book not found")

    fields: dict = {"updated_at": _now()}
    for k, v in [("title", title), ("author", author), ("description", description),
                 ("publisher", publisher), ("published", published), ("language", language),
                 ("series", series)]:
        if v is not None:
            fields[k] = v

    if series_index is not None:
        try:
            fields["series_index"] = float(series_index) if series_index else None
        except ValueError:
            pass

    # Fetch and save cover from URL
    if cover_url:
        saved = await _fetch_cover_from_url(cover_url, book_id)
        if saved:
            fields["cover_path"] = saved

    await database.update_book(db, book_id, fields)

    # Apply tags
    if tags:
        for tag_name in [t.strip() for t in tags.split(",") if t.strip()]:
            tag = await database.create_tag(db, tag_name)
            await database.add_book_tag(db, book_id, tag.id)

    if write_to_file and book.format == "epub":
        epub_path = config.BASE_DIR / book.file_path
        _write_metadata_to_epub(epub_path, {k: v for k, v in fields.items() if k != "updated_at"})

    return {"ok": True}
