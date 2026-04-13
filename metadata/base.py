from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MetadataResult:
    source: str                    # plugin name, e.g. "Google Books"
    title: str
    author: Optional[str] = None
    description: Optional[str] = None
    publisher: Optional[str] = None
    published: Optional[str] = None
    language: Optional[str] = None
    cover_url: Optional[str] = None
    isbn: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    series: Optional[str] = None
    series_index: Optional[float] = None


class MetadataPlugin(ABC):
    name: str

    @abstractmethod
    async def search(self, title: str, author: str = "") -> list[MetadataResult]:
        """Search for book metadata. Returns up to ~5 results."""
        ...
