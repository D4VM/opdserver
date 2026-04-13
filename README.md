# OPD Server

An OPDS 1.2 catalog server for serving ebooks to KOReader on jailbroken Kindles. Includes a web management UI for uploading books, editing metadata, and organizing with tags, authors, and series.

## Features

- **OPDS 1.2 feeds** — compatible with KOReader, Kindle, and any OPDS-capable reader
- **Web UI** — upload, browse, search, and edit book metadata from a browser
- **Metadata search** — fetch metadata automatically from Google Books and Open Library
- **Cover extraction** — covers are extracted from EPUB files on upload
- **Tag / Author / Series organization** — browse and filter your library
- **EPUB write-back** — optionally save metadata changes back into the EPUB file
- **Extensible metadata plugins** — drop a `.py` file in `metadata/` to add a new source

## Quick Start

### With Docker (recommended)

```bash
# 1. Clone the repo
git clone https://github.com/D4VM/opdserver.git
cd opdserver

# 2. Set your LAN IP in docker-compose.yml (BASE_URL line), then:
docker compose up --build
```

Open `http://localhost:8000` in your browser. Your library data is stored in `./data/` and survives container restarts.

After code changes, rebuild with:
```bash
docker compose up --build
```

### Without Docker

```bash
pip install -r requirements.txt
python3 main.py
```

For KOReader, add an OPDS catalog pointing to `http://<server-ip>:8000/opds`.

## Configuration

All settings are optional environment variables:

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Public URL used in OPDS feed links — set to your LAN IP |
| `SERVER_TITLE` | `My Library` | Title shown in OPDS feeds |
| `PORT` | `8000` | Port to listen on |
| `HOST` | `0.0.0.0` | Host to bind |

Example:

```bash
BASE_URL=http://192.168.1.100:8000 SERVER_TITLE="Home Library" python3 main.py
```

## Architecture

```
main.py          FastAPI app entry point, startup hooks, static file mounts
config.py        All paths and settings (BASE_DIR, BOOKS_DIR, COVERS_DIR, BASE_URL, …)
database.py      init_db(), get_db(), all SQL query functions (raw aiosqlite, no ORM)
models.py        Python dataclasses: Book, Tag, BookWithTags
routers/
  opds.py        OPDS 1.2 Atom XML feeds — all /opds/* endpoints
  api.py         JSON REST API: upload pipeline, book/tag CRUD, metadata search/apply
  web.py         Jinja2 HTML routes for the management UI
metadata/
  __init__.py    Auto-discovery loader — scans *.py, registers MetadataPlugin subclasses
  base.py        MetadataPlugin ABC + MetadataResult dataclass
  google_books.py  Google Books API plugin
  open_library.py  Open Library API plugin
templates/       Jinja2 HTML templates (Bootstrap 5, no build step)
static/          CSS + vanilla JS
books/           Uploaded ebook files, stored as {uuid}.{ext}
covers/          Extracted cover images as {uuid}.jpg
library.db       SQLite database (auto-created on startup)
```

## OPDS Feed Endpoints

| URL | Type | Description |
|---|---|---|
| `/opds` | Navigation | Root catalog |
| `/opds/all?page=N` | Acquisition | All books, paginated |
| `/opds/recent?page=N` | Acquisition | Books by date added |
| `/opds/tags` | Navigation | All tags |
| `/opds/tags/{name}?page=N` | Acquisition | Books by tag |
| `/opds/search?q=&page=N` | Acquisition | Full-text search |
| `/books/{uuid}.{ext}` | File | Download a book |
| `/covers/{uuid}.jpg` | Image | Book cover |

## Web UI Endpoints

| URL | Description |
|---|---|
| `/books` | Library — browse, search, filter |
| `/books/{id}/edit` | Edit book metadata, tags, cover |
| `/upload` | Upload new books |
| `/tags` | Manage tags |
| `/authors` | Browse by author |
| `/series` | Browse by series |

REST API docs are available at `/api/docs` (FastAPI auto-generated Swagger UI).

## Writing a Metadata Plugin

Drop a `.py` file in the `metadata/` directory. Define a class that inherits `MetadataPlugin` — it's auto-registered on first search.

```python
from metadata.base import MetadataPlugin, MetadataResult

class MyPlugin(MetadataPlugin):
    name = "My Source"

    async def search(self, title: str, author: str = "") -> list[MetadataResult]:
        # fetch from your API
        return [MetadataResult(
            source=self.name,
            title="...",
            author="...",
            description="...",
            cover_url="https://...",
        )]
```

## Localization

All UI labels live in `strings.json`. To translate the interface, edit the values (not the keys):

```json
{
  "nav_library":   "Библиотека",
  "nav_upload":    "Загрузить",
  "nav_tags":      "Теги",
  "btn_save":      "Сохранить",
  "drop_hint":     "Перетащите файлы сюда",
  ...
}
```

To keep your translations separate from the source code, create a custom file and point to it:

```bash
# env var
LOCALE_FILE=/data/my_strings.json python3 main.py

# or in docker-compose.yml
environment:
  - LOCALE_FILE=/app/my_strings.json
volumes:
  - ./my_strings.json:/app/my_strings.json
```

If a key is missing from your file, the interface falls back to the key name itself — so partial translations work fine.

## Supported Formats

EPUB, PDF, MOBI, AZW, AZW3, CBZ, FB2, TXT

Metadata and cover extraction is fully supported for EPUB. Other formats fall back to filename-based title parsing.
