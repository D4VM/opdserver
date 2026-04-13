"""
Metadata plugin system
======================
Plugins are auto-discovered: any .py file in this directory that defines a
class inheriting from MetadataPlugin is automatically loaded and registered.

To write a new plugin, create a file in this directory, e.g.
``metadata/my_source.py``, and define a class:

    from metadata.base import MetadataPlugin, MetadataResult

    class MySourcePlugin(MetadataPlugin):
        name = "My Source"

        async def search(self, title: str, author: str = "") -> list[MetadataResult]:
            # Call your API here and return results
            return [
                MetadataResult(
                    source=self.name,
                    title="...",
                    author="...",
                    description="...",
                    cover_url="https://...",
                )
            ]

That's all — no registration needed.
"""

import importlib
import inspect
import logging
from pathlib import Path

from .base import MetadataPlugin, MetadataResult  # noqa: F401 — re-exported

logger = logging.getLogger(__name__)

_PLUGINS: list[MetadataPlugin] = []
_LOADED = False


def _load_plugins() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True

    plugin_dir = Path(__file__).parent
    skip = {"__init__.py", "base.py"}

    for path in sorted(plugin_dir.glob("*.py")):
        if path.name in skip:
            continue
        module_name = f"metadata.{path.stem}"
        try:
            mod = importlib.import_module(module_name)
        except Exception as e:
            logger.warning("Could not load metadata plugin %s: %s", path.name, e)
            continue

        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, MetadataPlugin)
                and obj is not MetadataPlugin
                and obj not in {type(p) for p in _PLUGINS}
            ):
                try:
                    _PLUGINS.append(obj())
                    logger.info("Loaded metadata plugin: %s", obj.name)
                except Exception as e:
                    logger.warning("Could not instantiate plugin %s: %s", obj.__name__, e)


async def search_metadata(title: str, author: str = "") -> list[MetadataResult]:
    """Search all registered plugins and return combined results."""
    _load_plugins()
    results: list[MetadataResult] = []
    for plugin in _PLUGINS:
        try:
            plugin_results = await plugin.search(title, author)
            results.extend(plugin_results)
        except Exception as e:
            logger.warning("Plugin %s failed: %s", plugin.name, e)
    return results


def get_plugins() -> list[MetadataPlugin]:
    _load_plugins()
    return list(_PLUGINS)
