"""
UI string loader for OPD Server.

Default strings live in strings.json (English). To localize:
  - Edit strings.json directly, OR
  - Create a custom JSON file and point to it via:
      env var:   LOCALE_FILE=/path/to/your/strings.json
      server.ini: [server] locale_file = /path/to/your/strings.json
"""
import json
import os
from pathlib import Path

_DEFAULT = Path(__file__).parent / "strings.json"


class Strings(dict):
    """Dict subclass: missing keys return the key name itself (safe fallback)."""

    def __missing__(self, key: str) -> str:
        return key

    def __getattr__(self, key: str) -> str:
        try:
            return self[key]
        except KeyError:
            return key


def load_strings() -> Strings:
    locale_file = os.environ.get("LOCALE_FILE") or os.environ.get("SERVER_LOCALE_FILE")
    path = Path(locale_file) if locale_file else _DEFAULT
    if not path.is_absolute():
        path = Path(__file__).parent / path

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        with open(_DEFAULT, encoding="utf-8") as f:
            data = json.load(f)

    # Strip comment/metadata keys (start with _)
    return Strings({k: v for k, v in data.items() if not k.startswith("_")})
