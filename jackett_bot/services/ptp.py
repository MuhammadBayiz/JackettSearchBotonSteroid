import httpx


class PTPService:
    def __init__(self, base_url: str = "https://passthepopcorn.me", client: httpx.AsyncClient | None = None):
        self.base_url = base_url
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None

    async def is_available(self, timeout: int = 5) -> bool:
        try:
            response = await self._client.get(self.base_url, timeout=timeout)
            response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def close(self):
        if self._owns_client:
            await self._client.aclose()
