import logging
from typing import Iterable

from telegraph import Telegraph


class TelegraphService:
    _instance = None
    _telegraph_token = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        account_name: str = "JackettSearchBot",
        logger: logging.Logger | None = None,
        access_token: str | None = None,
    ):
        self.logger = logger or logging.getLogger("JackettSearchBot")
        self.account_name = account_name

        if access_token and access_token.strip():
            self.__class__._telegraph_token = access_token.strip()

    def create_new_telegraph_token(self, name: str) -> str:
        telegraph = Telegraph()
        telegraph.create_account(short_name=name)
        return telegraph.get_access_token()

    def _ensure_token(self) -> bool:
        if self.__class__._telegraph_token:
            return True

        try:
            self.__class__._telegraph_token = self.create_new_telegraph_token(self.account_name)
            return True
        except Exception as exc:
            self.logger.exception("Unable to create Telegraph account/token: %s", exc)
            return False

    def get_telegraph_token(self) -> str | None:
        if self.__class__._telegraph_token:
            return self.__class__._telegraph_token

        if self._ensure_token():
            return self.__class__._telegraph_token

        return None

    def create_page(self, title: str, html_content: str, author_name: str) -> dict:
        token = self.get_telegraph_token()
        if not token:
            raise RuntimeError("Telegraph token unavailable")

        telegraph = Telegraph(token)
        return telegraph.create_page(
            title=title,
            html_content=html_content,
            author_name=author_name,
        )

    def send_results_to_telegraph(self, results: Iterable[str]) -> str | None:
        formatted_results = "<br>".join(result.replace("\n", "<br>") for result in results)

        try:
            response = self.create_page(
                title="Search Results",
                html_content=formatted_results,
                author_name="JackettSearchBot",
            )
            return response.get("url")
        except Exception as exc:
            self.logger.exception("Error pasting to Telegraph: %s", exc)
            return None
