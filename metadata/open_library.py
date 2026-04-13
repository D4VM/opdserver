import httpx
from .base import MetadataPlugin, MetadataResult


class OpenLibraryPlugin(MetadataPlugin):
    name = "Open Library"
    _SEARCH = "https://openlibrary.org/search.json"
    _COVER = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"

    async def search(self, title: str, author: str = "") -> list[MetadataResult]:
        params: dict = {"title": title, "limit": 5, "fields": "key,title,author_name,publisher,first_publish_year,language,subject,cover_i,isbn"}
        if author:
            params["author"] = author

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self._SEARCH, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for doc in data.get("docs", []):
            authors = doc.get("author_name", [])
            author_str = ", ".join(authors) if authors else None

            cover_id = doc.get("cover_i")
            cover_url = self._COVER.format(cover_id=cover_id) if cover_id else None

            year = doc.get("first_publish_year")
            published = f"{year}-01-01" if year else None

            langs = doc.get("language", [])
            language = langs[0] if langs else None

            subjects = doc.get("subject", [])[:5]  # limit tags

            isbns = doc.get("isbn", [])
            isbn = next((i for i in isbns if len(i) == 13), isbns[0] if isbns else None)

            publishers = doc.get("publisher", [])

            results.append(
                MetadataResult(
                    source=self.name,
                    title=doc.get("title", title),
                    author=author_str,
                    description=None,  # Open Library search doesn't return descriptions
                    publisher=publishers[0] if publishers else None,
                    published=published,
                    language=language,
                    cover_url=cover_url,
                    isbn=isbn,
                    tags=subjects,
                )
            )
        return results
