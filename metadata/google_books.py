import urllib.parse
import httpx
from .base import MetadataPlugin, MetadataResult


class GoogleBooksPlugin(MetadataPlugin):
    name = "Google Books"
    _BASE = "https://www.googleapis.com/books/v1/volumes"

    async def search(self, title: str, author: str = "") -> list[MetadataResult]:
        query = title
        if author:
            query += f" inauthor:{author}"
        params = {"q": query, "maxResults": 5, "printType": "books"}

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self._BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("items", []):
            info = item.get("volumeInfo", {})

            authors = info.get("authors", [])
            author_str = ", ".join(authors) if authors else None

            categories = info.get("categories", [])

            # Cover image — prefer the largest available
            image_links = info.get("imageLinks", {})
            cover_url = (
                image_links.get("large")
                or image_links.get("medium")
                or image_links.get("thumbnail")
            )
            # Force HTTPS
            if cover_url:
                cover_url = cover_url.replace("http://", "https://")

            isbn = None
            for id_entry in info.get("industryIdentifiers", []):
                if id_entry.get("type") in ("ISBN_13", "ISBN_10"):
                    isbn = id_entry["identifier"]
                    break

            published = info.get("publishedDate", "")
            # Normalize to YYYY-MM-DD if only year given
            if published and len(published) == 4:
                published = f"{published}-01-01"

            results.append(
                MetadataResult(
                    source=self.name,
                    title=info.get("title", title),
                    author=author_str,
                    description=info.get("description"),
                    publisher=info.get("publisher"),
                    published=published or None,
                    language=info.get("language"),
                    cover_url=cover_url,
                    isbn=isbn,
                    tags=categories,
                )
            )
        return results
