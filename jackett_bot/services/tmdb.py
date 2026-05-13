import asyncio
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class TMDbSearchResult:
    id: int
    title: str
    media_type: str
    release_date: str
    popularity: float
    imdb_id: str | None = None
    poster_path: str | None = None
    overview: str | None = None
    original_language: str | None = None

    @property
    def display_title(self) -> str:
        date_str = f" ({self.release_date[:4]})" if self.release_date else ""
        return f"{self.title}{date_str}"

    @property
    def thumb_url(self) -> str | None:
        if not self.poster_path:
            return None
        return f"https://image.tmdb.org/t/p/w200{self.poster_path}"


class TMDbService:
    def __init__(self, tmdb_api_key: str, client: httpx.AsyncClient | None = None):
        self.api_key = tmdb_api_key
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self.base_url = "https://api.themoviedb.org/3"

    async def search(self, query: str, limit: int = 10) -> list[TMDbSearchResult]:
        if not query.strip():
            return []

        url = f"{self.base_url}/search/multi"
        params = {
            "api_key": self.api_key,
            "query": query,
            "include_adult": "false",
        }

        response = await self._client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        results = []
        for item in data.get("results", []):
            media_type = item.get("media_type")
            if media_type not in ("movie", "tv"):
                continue

            title = item.get("title") or item.get("name")
            release_date = item.get("release_date") or item.get("first_air_date") or ""

            if not title:
                continue

            results.append(
                TMDbSearchResult(
                    id=item["id"],
                    title=title,
                    media_type=media_type,
                    release_date=release_date,
                    popularity=item.get("popularity", 0.0),
                    poster_path=item.get("poster_path"),
                    overview=item.get("overview") or None,
                    original_language=item.get("original_language") or None,
                )
            )

        # Sort by popularity
        results.sort(key=lambda r: r.popularity, reverse=True)
        results = results[:limit]

        # Fetch imdb_id concurrently
        tasks = [self._fetch_imdb_id(result) for result in results]
        results_with_imdb_id = await asyncio.gather(*tasks)

        # Filter out results without imdb_id as they can't be searched using it in jackett easily
        return [r for r in results_with_imdb_id if r.imdb_id]

    async def _fetch_imdb_id(self, result: TMDbSearchResult) -> TMDbSearchResult:
        url = f"{self.base_url}/{result.media_type}/{result.id}/external_ids"
        params = {"api_key": self.api_key}

        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            imdb_id = data.get("imdb_id")

            return TMDbSearchResult(
                id=result.id,
                title=result.title,
                media_type=result.media_type,
                release_date=result.release_date,
                popularity=result.popularity,
                imdb_id=imdb_id,
                poster_path=result.poster_path,
                overview=result.overview,
                original_language=result.original_language,
            )
        except Exception:
            return result

    async def close(self):
        if self._owns_client:
            await self._client.aclose()
