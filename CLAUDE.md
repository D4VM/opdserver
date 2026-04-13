# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An OPDS 1.2 catalog server for serving ebooks to KOReader on jailbroken Kindles. Includes a web management UI for uploading books, editing metadata, and organizing with tags.

## Running the server

```bash
# Install dependencies
pip install -r requirements.txt

# Start (auto-reload in development)
python3 main.py

# Or directly with uvicorn
python3 -m uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Environment variables (all optional)
BASE_URL=http://192.168.1.100:8000   # used in OPDS feed links — set to your LAN IP
SERVER_TITLE="My Library"
PORT=8000
HOST=0.0.0.0
```

Server starts at `http://localhost:8000`. KOReader OPDS catalog URL: `http://<server-ip>:8000/opds`

## Architecture

```
main.py          FastAPI app, startup hooks, StaticFiles mounts
config.py        All paths and settings (BASE_DIR, BOOKS_DIR, COVERS_DIR, PAGE_SIZE, BASE_URL)
database.py      init_db(), get_db() (aiosqlite context), all raw SQL query functions
models.py        Python dataclasses: Book, Tag, BookWithTags
routers/
  opds.py        OPDS 1.2 Atom XML feeds — all /opds/* endpoints
  api.py         JSON API: upload pipeline, book/tag CRUD, metadata search/apply
  web.py         Jinja2 HTML routes for the management UI
metadata/
  __init__.py    Auto-discovery loader — scans *.py files, registers MetadataPlugin subclasses
  base.py        MetadataPlugin ABC + MetadataResult dataclass
  google_books.py  Google Books API plugin
  open_library.py  Open Library API plugin
templates/       Jinja2 HTML (Bootstrap 5, no build step)
static/          CSS + vanilla JS
books/           Uploaded ebook files, stored as {uuid}.{ext}
covers/          Extracted cover images as {uuid}.jpg
library.db       SQLite database (auto-created on startup)
```

## Key design decisions

- **Raw aiosqlite** (no ORM) — 3-table schema is simple enough; all queries are in `database.py`
- **lxml.etree** for OPDS XML — handles namespace prefixes and character escaping correctly
- **Flat file storage** — books stored as `{uuid}.{ext}`, avoids path/character issues
- **`BASE_URL` in config** — all OPDS feed links use this; must be set to LAN IP for Kindle access

## OPDS feed structure

| Endpoint | Type | Description |
|---|---|---|
| `/opds` | Navigation | Root catalog |
| `/opds/all?page=N` | Acquisition | All books, paginated |
| `/opds/recent?page=N` | Acquisition | Books by added date |
| `/opds/tags` | Navigation | All tags |
| `/opds/tags/{name}?page=N` | Acquisition | Books by tag |
| `/opds/search?q=&page=N` | Acquisition | Full-text search |
| `/books/{uuid}.{ext}` | File | Download |
| `/covers/{uuid}.jpg` | Image | Cover |

## Writing a metadata plugin

Drop a `.py` file in `metadata/`. Define a class inheriting `MetadataPlugin`. It auto-registers on first search.

```python
from metadata.base import MetadataPlugin, MetadataResult

class MyPlugin(MetadataPlugin):
    name = "My Source"

    async def search(self, title: str, author: str = "") -> list[MetadataResult]:
        # fetch from your API
        return [MetadataResult(source=self.name, title="...", author="...")]
```

## API endpoints

- `POST /api/upload` — multipart `files[]`, returns JSON list with id/title/author/cover
- `POST /api/books/{id}?title=&author=&...&write_to_file=true` — update metadata
- `DELETE /api/books/{id}` — delete book and files
- `POST /api/books/{id}/cover` — replace cover image (multipart `file`)
- `GET /api/books/{id}/metadata/search?q=&author=` — search all plugins
- `POST /api/books/{id}/metadata/apply?title=&...&cover_url=&tags=&write_to_file=true` — apply result
- `POST /api/tags?name=` — create tag
- `DELETE /api/tags/{id}` — delete tag
- `POST /api/tags/{id}/rename?name=` — rename tag
- `POST/DELETE /api/books/{id}/tags/{tag_id}` — assign/remove tag

FastAPI auto-docs available at `/api/docs`.
