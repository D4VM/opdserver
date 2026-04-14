"""
Shared pytest fixtures for the OPDS server test suite.

Sets up a fully isolated app instance with:
  - temporary SQLite database
  - temporary books/ and covers/ directories
  - config module patched to use those paths
"""
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ── patch config BEFORE importing anything that reads it ──────────────────────
_tmpdir = tempfile.mkdtemp()
_tmp = Path(_tmpdir)

import config as _config_mod
_config_mod.BASE_DIR    = _tmp
_config_mod.BOOKS_DIR   = _tmp / "books"
_config_mod.COVERS_DIR  = _tmp / "covers"
_config_mod.DB_PATH     = _tmp / "test.db"
_config_mod.BOOKS_DIR.mkdir()
_config_mod.COVERS_DIR.mkdir()

# Initialise the DB schema synchronously so all tests see existing tables
import asyncio as _asyncio
from database import init_db as _init_db
_asyncio.run(_init_db())

# Patch routers/api.py module-level config reference as well (it imports config)
import routers.api as _api_mod
_api_mod.config = _config_mod

# ── import the app AFTER config patch ─────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from main import app  # noqa: E402


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture(scope="function")
async def client():
    """Fresh async HTTP client for each test."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
