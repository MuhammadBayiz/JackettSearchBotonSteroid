from __future__ import annotations

import html
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote

import httpx

_TORZNAB_NS = "http://torznab.com/schemas/2015/feed"


@dataclass(frozen=True)
class SearchResult:
    title: str
    age: str
    size: str
    size_bytes: int
    link: str | None = None
    magnet: str | None = None

    def download_url(self) -> str | None:
        return self.magnet or self.link

    def as_html(self) -> str:
        return (
            f"<b>Title:</b> <code>{html.escape(self.title)}</code>\n"
            f"<b>Age:</b> {self.age}\n"
            f"<b>Size:</b> {self.size}\n"
        )

    def as_text(self) -> str:
        return f"Title: {self.title}\nAge: {self.age}\nSize: {self.size}\n"


class JackettService:
    def __init__(
        self,
        jackett_url: str,
        jackett_api_key: str,
        client: httpx.AsyncClient | None = None,
    ):
        self.jackett_url = jackett_url.rstrip("/")
        self.jackett_api_key = jackett_api_key
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    def build_search_url(
        self,
        query: str,
        category: str | None = None,
        indexer_ids: list[str] | None = None,
    ) -> str:
        if indexer_ids:
            indexer_path = ",".join(indexer_ids)
        else:
            indexer_path = "all"

        base = f"{self.jackett_url}/api/v2.0/indexers/{indexer_path}/results/torznab/api"

        if query.startswith("tt") and query[2:].isdigit():
            url = f"{base}?apikey={self.jackett_api_key}&imdbid={query}"
        else:
            url = f"{base}?apikey={self.jackett_api_key}&t=search&q={quote(query)}"

        if category:
            url += f"&cat={category}"

        return url

    async def get_tags_from_api(self, timeout: int = 30) -> dict[str, list[str]]:
        """Return {tag: [indexer_id, ...]} for all configured indexers that have tags."""
        url = f"{self.jackett_url}/api/v2.0/indexers?configured=true&apikey={self.jackett_api_key}"
        try:
            response = await self._client.get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return {}

        tag_map: dict[str, list[str]] = {}
        for indexer in data:
            indexer_id = indexer.get("id", "")
            tags = indexer.get("tags") or []
            for tag in tags:
                tag_map.setdefault(tag, []).append(indexer_id)

        return tag_map

    async def search(
        self,
        query: str,
        golden_popcorn: bool = False,
        category: str | None = None,
        indexer_ids: list[str] | None = None,
        timeout: int = 60,
    ) -> list[SearchResult]:
        url = self.build_search_url(query, category=category, indexer_ids=indexer_ids)
        response = await self._client.get(url, timeout=timeout)
        response.raise_for_status()

        if not response.text.strip():
            return []

        return parse_search_results(response.content, golden_popcorn=golden_popcorn)

    async def close(self):
        if self._owns_client:
            await self._client.aclose()


def convert_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0 B"

    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    index = int(math.floor(math.log(size_bytes, 1024)))
    power = math.pow(1024, index)
    size = round(size_bytes / power, 2)
    return f"{size} {size_name[index]}"


def format_pub_date(pub_date: str) -> str:
    try:
        date_obj = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        return "unknown"

    time_elapsed = datetime.now(date_obj.tzinfo) - date_obj

    if time_elapsed.days > 0:
        return f"{time_elapsed.days} d"

    hours, remainder = divmod(time_elapsed.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours} h"
    if minutes > 0:
        return f"{minutes} m"
    return f"{seconds} s"


def parse_search_results(
    response_content: bytes, golden_popcorn: bool = False
) -> list[SearchResult]:
    root = ET.fromstring(response_content)
    results: list[SearchResult] = []

    for item in root.findall(".//item"):
        title = _get_item_text(item, "title")
        size_raw = _get_item_text(item, "size")
        pub_date = _get_item_text(item, "pubDate")

        if not title or not size_raw or not pub_date:
            continue
        if golden_popcorn and "Golden Popcorn" not in title:
            continue

        size_bytes = _safe_int(size_raw)
        if size_bytes is None:
            continue

        link = _get_item_text(item, "link")
        magnet = _get_torznab_attr(item, "magneturl")

        results.append(
            SearchResult(
                title=title,
                age=format_pub_date(pub_date),
                size=convert_size(size_bytes),
                size_bytes=size_bytes,
                link=link,
                magnet=magnet,
            )
        )

    return results


def _get_item_text(item: ET.Element, tag: str) -> str | None:
    element = item.find(tag)
    return element.text if element is not None else None


def _get_torznab_attr(item: ET.Element, attr_name: str) -> str | None:
    for attr_el in item.findall(f"{{{_TORZNAB_NS}}}attr"):
        if attr_el.get("name") == attr_name:
            return attr_el.get("value")
    return None


def _safe_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
