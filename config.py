import configparser
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

BOOKS_DIR = BASE_DIR / "books"
COVERS_DIR = BASE_DIR / "covers"
DB_PATH = BASE_DIR / "library.db"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Load server.ini (fall back to defaults if not present)
_ini = configparser.ConfigParser()
_ini.read(BASE_DIR / "server.ini")

def _get(section: str, key: str, default: str) -> str:
    # Environment variables override ini (e.g. BASE_URL overrides [server] base_url)
    env_key = f"{section.upper()}_{key.upper()}"
    return os.environ.get(env_key) or _ini.get(section, key, fallback=default)

HOST          = _get("server", "host",     "0.0.0.0")
PORT          = int(_get("server", "port", "8000"))
BASE_URL      = _get("server", "base_url", "http://localhost:8000").rstrip("/")
SERVER_TITLE  = _get("server", "title",    "OPD Server")

PAGE_SIZE       = int(_get("library", "page_size",       "50"))
MAX_COVER_WIDTH = int(_get("library", "max_cover_width", "600"))
