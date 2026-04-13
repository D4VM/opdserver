from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Book:
    id: str
    title: str
    filename: str
    file_path: str
    format: str
    added_at: str
    updated_at: str
    author: Optional[str] = None
    description: Optional[str] = None
    publisher: Optional[str] = None
    language: str = "en"
    published: Optional[str] = None
    file_size: Optional[int] = None
    cover_path: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None


@dataclass
class Tag:
    id: int
    name: str


@dataclass
class BookWithTags:
    book: Book
    tags: list[Tag] = field(default_factory=list)
