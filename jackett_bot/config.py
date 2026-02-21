import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class BotConfig:
    token: str
    api_id: int
    api_hash: str
    jackett_api_key: str
    jackett_url: str
    default_max_results: int
    authorized_chat_ids: list[int]
    owner_id: int
    auth_db_path: str

    @classmethod
    def from_env(cls, env_file: str = "config.env") -> "BotConfig":
        load_dotenv(env_file)

        return cls(
            token=_require_env("TELEGRAM_TOKEN"),
            api_id=_parse_int_env("API_ID", required=True),
            api_hash=_require_env("API_HASH"),
            jackett_api_key=_require_env("JACKETT_API_KEY"),
            jackett_url=_require_env("JACKETT_URL"),
            default_max_results=_parse_int_env("MAX_RESULTS", default=10),
            authorized_chat_ids=_parse_authorized_chat_ids(os.getenv("AUTHORIZED_CHAT_IDS", "")),
            owner_id=_parse_int_env("OWNER_ID", default=0),
            auth_db_path=_parse_str_env("AUTH_DB_PATH", default="auth.db"),
        )


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if value is None or not value.strip():
        raise ValueError(f"Missing required environment variable: {key}")
    return value.strip()


def _parse_int_env(key: str, default: int | None = None, required: bool = False) -> int:
    raw = os.getenv(key)

    if raw is None or not raw.strip():
        if required:
            raise ValueError(f"Missing required integer environment variable: {key}")
        if default is not None:
            return default
        raise ValueError(f"Missing integer environment variable with no default: {key}")

    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"Environment variable {key} must be an integer, got: {raw!r}") from exc


def _parse_str_env(key: str, default: str) -> str:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _parse_authorized_chat_ids(raw_chat_ids: str) -> list[int]:
    chat_ids: list[int] = []
    for chat_id in raw_chat_ids.split(","):
        trimmed = chat_id.strip()
        if not trimmed:
            continue
        try:
            chat_ids.append(int(trimmed))
        except ValueError as exc:
            raise ValueError(f"Invalid chat id in AUTHORIZED_CHAT_IDS: {trimmed!r}") from exc
    return chat_ids
