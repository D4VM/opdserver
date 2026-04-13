"""
Fantasy-Worlds.org metadata plugin.
Searches https://fantasy-worlds.org for book metadata (Russian fantasy/SF).
"""

import httpx
from bs4 import BeautifulSoup

from .base import MetadataPlugin, MetadataResult


class FantasyWorldsPlugin(MetadataPlugin):
    name = "Fantasy Worlds"

    SEARCH_URL = "https://fantasy-worlds.org/search/?q="

    @staticmethod
    def _fix_query(query: str) -> str:
        return "+".join(query.strip().split())

    async def search(self, title: str, author: str = "") -> list[MetadataResult]:
        query = f"{title} {author}".strip() if author else title
        url = self.SEARCH_URL + self._fix_query(query)

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception:
                return []

        soup = BeautifulSoup(resp.content, "html.parser")
        results = []

        for item in soup.select(".news_body"):
            try:
                title_tag = item.select_one('span[itemprop="name"]')
                if not title_tag:
                    continue
                book_title = title_tag.get_text(strip=True)

                author_tag = item.select_one('a[itemprop="author"]')
                book_author = author_tag.get_text(strip=True) if author_tag else None

                # Series — may be multiple, join with " / "
                series_links = item.select('a[href^="/series/"]')
                series = ": ".join(a.get_text(strip=True) for a in series_links) or None

                # Series index
                series_index: float | None = None
                number_text = item.find(string="Номер книги в серии:")
                if number_text:
                    try:
                        series_index = float(number_text.next.strip())
                    except (ValueError, AttributeError):
                        pass

                isbn_tag = item.select_one('span[itemprop="isbn"]')
                isbn = isbn_tag.get_text(strip=True) if isbn_tag else None

                desc_tag = item.select_one('span[itemprop="description"]')
                description = desc_tag.get_text(strip=True) if desc_tag else None

                img_tag = item.select_one('img[itemprop="image"]')
                cover_url = (
                    "https://fantasy-worlds.org" + img_tag["src"]
                    if img_tag and img_tag.get("src")
                    else None
                )

                results.append(
                    MetadataResult(
                        source=self.name,
                        title=book_title,
                        author=book_author,
                        description=description,
                        cover_url=cover_url,
                        isbn=isbn,
                        series=series,
                        series_index=series_index,
                    )
                )
            except Exception:
                continue

        return results
