from __future__ import annotations

import html
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
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


@dataclass(frozen=True)
class JackettCategory:
    name: str
    id: str


def _is_imdb_id(query: str) -> bool:
    return query.startswith("tt") and query[2:].isdigit()


def _is_tmdb_id(query: str) -> bool:
    return query.startswith("tmdb:") and query[5:].isdigit()


def is_id_query(query: str) -> bool:
    """True when query is an IMDB or TMDB ID — skips category selection."""
    return _is_imdb_id(query) or _is_tmdb_id(query)


class JackettService:
    def __init__(
        self,
        jackett_url: str,
        jackett_api_key: str,
        jackett_password: str = "",
        client: httpx.AsyncClient | None = None,
    ):
        self.jackett_url = jackett_url.rstrip("/")
        self.jackett_api_key = jackett_api_key
        self.jackett_password = jackett_password
        self._client = client or httpx.AsyncClient(follow_redirects=True)
        self._owns_client = client is None
        self._categories_cache: list[JackettCategory] | None = None

    def build_search_url(
        self,
        query: str,
        category: str | None = None,
        indexer_ids: list[str] | None = None,
    ) -> str:
        # ID-based searches use Jackett's lookup API which not all indexers support.
        # Using specific indexers causes a 500 if any of them don't support it.
        if _is_imdb_id(query) or _is_tmdb_id(query):
            indexer_path = "all"
        else:
            indexer_path = ",".join(indexer_ids) if indexer_ids else "all"
        base = f"{self.jackett_url}/api/v2.0/indexers/{indexer_path}/results/torznab/api"

        if _is_imdb_id(query):
            url = f"{base}?apikey={self.jackett_api_key}&imdbid={query}"
        elif _is_tmdb_id(query):
            tmdb_id = query[5:]
            url = f"{base}?apikey={self.jackett_api_key}&tmdbid={tmdb_id}"
        else:
            url = f"{base}?apikey={self.jackett_api_key}&t=search&q={quote(query)}"

        if category:
            url += f"&cat={category}"

        return url

    async def get_categories(self, timeout: int = 30) -> list[JackettCategory]:
        """Fetch top-level categories from Jackett caps. Cached after first call."""
        if self._categories_cache is not None:
            return self._categories_cache

        url = (
            f"{self.jackett_url}/api/v2.0/indexers/all/results/torznab/api"
            f"?apikey={self.jackett_api_key}&t=caps"
        )
        try:
            response = await self._client.get(url, timeout=timeout)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            cats = [
                JackettCategory(name=el.get("name", ""), id=el.get("id", ""))
                for el in root.findall(".//categories/category")
                if el.get("name") and el.get("id")
            ]
        except Exception:
            cats = []

        self._categories_cache = cats
        return cats

    async def _get_authenticated_client(self, timeout: int = 30) -> httpx.AsyncClient:
        """Return a client with a valid Jackett session cookie.

        Jackett's management API requires a browser-style session:
        1. GET /UI/Login  →  nginx reverse proxy sets TestCookie
        2. POST /UI/Dashboard with password  →  Jackett sets its own session cookie
        """
        auth_client = httpx.AsyncClient(follow_redirects=True)
        await auth_client.get(f"{self.jackett_url}/UI/Login", timeout=timeout)
        await auth_client.post(
            f"{self.jackett_url}/UI/Dashboard",
            data={"password": self.jackett_password},
            timeout=timeout,
        )
        return auth_client

    async def get_tags_from_api(self, timeout: int = 30) -> dict[str, list[str]]:
        """Return {tag: [indexer_id, ...]} for all configured indexers that have tags."""
        auth_client = None
        try:
            auth_client = await self._get_authenticated_client(timeout=timeout)
            response = await auth_client.get(
                f"{self.jackett_url}/api/v2.0/indexers",
                params={"configured": "true", "apikey": self.jackett_api_key},
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:
            return {}
        finally:
            if auth_client is not None:
                await auth_client.aclose()

        tag_map: dict[str, list[str]] = {}
        for indexer in data:
            indexer_id = indexer.get("id", "")
            for tag in indexer.get("tags") or []:
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

        # Prefer magnet url, fallback to standard link
        magnet_element = item.find(
            "torznab:attr[@name='magneturl']",
            namespaces={"torznab": "http://torznab.com/schemas/2015/feed"},
        )
        magneturl = (
            magnet_element.attrib.get("value") if magnet_element is not None else None
        )

        link = _get_item_text(item, "link")
        download_url = magneturl or link

        if not title or not size_raw or not pub_date or not download_url:
            continue
        if golden_popcorn and "Golden Popcorn" not in title:
            continue

        size_bytes = _safe_int(size_raw)
        if size_bytes is None:
            continue

        results.append(
            SearchResult(
                title=title,
                age=format_pub_date(pub_date),
                size=convert_size(size_bytes),
                size_bytes=size_bytes,
                link=_get_item_text(item, "link"),
                magnet=_get_torznab_attr(item, "magneturl"),
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
