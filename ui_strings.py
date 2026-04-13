"""
UI string / locale system for OPD Server.

Locale files live in locales/<code>.json  (e.g. locales/en.json, locales/ru.json).
The active language is persisted in settings.json and can be changed at runtime
via set_language() — no server restart needed.

Priority: settings.json > LOCALE_LANG env var > "en" fallback.
"""
import json
import os
from pathlib import Path

LOCALES_DIR   = Path(__file__).parent / "locales"
SETTINGS_FILE = Path(__file__).parent / "settings.json"
_DEFAULT_LANG = "en"


# ── Strings dict ────────────────────────────────────────────────────────────

class Strings(dict):
    """Dict subclass: missing keys return the key name itself (safe fallback)."""

    def __missing__(self, key: str) -> str:
        return key

    def __getattr__(self, key: str) -> str:
        try:
            return self[key]
        except KeyError:
            return key


# ── Settings persistence ─────────────────────────────────────────────────────

def _load_settings() -> dict:
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_settings(data: dict) -> None:
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Locale helpers ───────────────────────────────────────────────────────────

def list_locales() -> list[dict]:
    """Return [{code, name}, ...] sorted by display name for all locales/ files."""
    result = []
    for path in sorted(LOCALES_DIR.glob("*.json")):
        code = path.stem
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("locale_name", code.upper())
        except Exception:
            name = code.upper()
        result.append({"code": code, "name": name})
    return sorted(result, key=lambda x: x["name"])


def _load_locale(lang: str) -> Strings:
    path = LOCALES_DIR / f"{lang}.json"
    if not path.exists():
        path = LOCALES_DIR / f"{_DEFAULT_LANG}.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return Strings(data)   # keep all keys including locale_name


def get_current_lang() -> str:
    return _load_settings().get(
        "language", os.environ.get("LOCALE_LANG", _DEFAULT_LANG)
    )


# ── Live-swappable singleton ─────────────────────────────────────────────────
# _active is the same dict object registered as a Jinja2 global.
# Mutating it in place means templates pick up the new language instantly,
# with no restart and no need to re-register the global.

_active: Strings = Strings()


def _reload() -> None:
    new = _load_locale(get_current_lang())
    _active.clear()
    _active.update(new)


def get_active() -> Strings:
    return _active


def set_language(lang: str) -> None:
    """Persist the language choice and hot-reload the active strings."""
    settings = _load_settings()
    settings["language"] = lang
    _save_settings(settings)
    _reload()


# Initialise on import
_reload()
