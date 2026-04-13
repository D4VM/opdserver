"""
Fantlab.ru metadata plugin.
Searches https://fantlab.ru — the largest Russian SF/fantasy bibliography database.
"""

import re

import httpx
from bs4 import BeautifulSoup

from .base import MetadataPlugin, MetadataResult


class FantlabPlugin(MetadataPlugin):
    name = "Fantlab"

    SEARCH_URL = "https://fantlab.ru/searchmain?searchstr="

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

            for item in soup.select(".search-block.editions .b"):
                a_tag = item.select_one("a")
                if not a_tag:
                    continue

                href = a_tag.get("href", "")
                if not re.search(r"edition\d+", href):
                    continue

                edition_url = f"https://fantlab.ru{href}"

                try:
                    edition_resp = await client.get(edition_url, timeout=10)
                    edition_resp.raise_for_status()
                except Exception:
                    continue

                esoup = BeautifulSoup(edition_resp.content, "html.parser")
                block = esoup.select_one(".titles-block-center")
                if not block:
                    continue

                title_tag = block.select_one("#name")
                book_title = title_tag.get_text(strip=True) if title_tag else None
                if not book_title:
                    continue

                author_tag = block.select_one("#autors a")
                book_author = author_tag.get_text(strip=True) if author_tag else None

                lang_meta = block.select_one("meta[itemprop='inLanguage']")
                language = lang_meta.get("content", "").strip() if lang_meta else None

                publisher_tag = block.select_one("#publisher a")
                publisher = publisher_tag.get_text(strip=True) if publisher_tag else None

                series_tag = block.select_one("#series a")
                series = series_tag.get_text(strip=True) if series_tag else None

                img_tag = esoup.select_one("img[itemprop='image']")
                if img_tag and img_tag.get("src", "").startswith("/"):
                    cover_url = f"https://fantlab.ru{img_tag['src']}"
                else:
                    cover_url = None

                book_id = href.replace("/edition", "")

                results.append(
                    MetadataResult(
                        source=self.name,
                        title=book_title,
                        author=book_author,
                        publisher=publisher,
                        language=language or None,
                        cover_url=cover_url,
                        series=series,
                        isbn=book_id,
                    )
                )

        return results
