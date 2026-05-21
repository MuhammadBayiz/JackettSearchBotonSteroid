import logging
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
    tmdb_api_key: str
    qbittorrent_host: str
    qbittorrent_username: str
    qbittorrent_password: str
    qbittorrent_category: str
    webhook_host: str
    webhook_port: int
    index_base_url: str
    media_local_path: str
    subtitle_languages: list[str]
    default_max_results: int
    redact_after_seconds: int
    log_file_path: str
    console_log_level: int
    file_log_level: int
    authorized_chat_ids: list[int]
    owner_id: int

    @classmethod
    def from_env(cls, env_file: str = "config.env") -> "BotConfig":
        load_dotenv(env_file)
        _validate_required_env(
            [
                "TELEGRAM_TOKEN",
                "API_ID",
                "API_HASH",
                "JACKETT_API_KEY",
                "JACKETT_URL",
                "TMDB_API_KEY",
                "QBITTORRENT_HOST",
                "QBITTORRENT_USERNAME",
                "QBITTORRENT_PASSWORD",
                "QBITTORRENT_CATEGORY",
                "OWNER_ID",
            ]
        )

        return cls(
            token=_require_env("TELEGRAM_TOKEN"),
            api_id=_parse_int_env("API_ID", required=True),
            api_hash=_require_env("API_HASH"),
            jackett_api_key=_require_env("JACKETT_API_KEY"),
            jackett_url=_require_env("JACKETT_URL"),
            tmdb_api_key=_require_env("TMDB_API_KEY"),
            qbittorrent_host=_require_env("QBITTORRENT_HOST"),
            qbittorrent_username=_require_env("QBITTORRENT_USERNAME"),
            qbittorrent_password=_require_env("QBITTORRENT_PASSWORD"),
            qbittorrent_category=_require_env("QBITTORRENT_CATEGORY"),
            webhook_host=_parse_str_env("WEBHOOK_HOST", default="127.0.0.1"),
            webhook_port=_parse_int_env("WEBHOOK_PORT", default=8888),
            index_base_url=_parse_str_env("INDEX_BASE_URL", default=""),
            media_local_path=_parse_str_env("MEDIA_LOCAL_PATH", default=""),
            subtitle_languages=_parse_str_list_env("SUBTITLE_LANGUAGES", default="eng"),
            default_max_results=_parse_positive_int_env("MAX_RESULTS", default=10),
            redact_after_seconds=_parse_positive_int_env(
                "REDACT_AFTER_SECONDS", default=300
            ),
            log_file_path=_parse_str_env(
                "LOG_FILE_PATH", default="logs/jackett_bot.log"
            ),
            console_log_level=_parse_log_level_env("CONSOLE_LOG_LEVEL", default="INFO"),
            file_log_level=_parse_log_level_env("FILE_LOG_LEVEL", default="DEBUG"),
            authorized_chat_ids=_parse_authorized_chat_ids(
                os.getenv("AUTHORIZED_CHAT_IDS", "")
            ),
            owner_id=_parse_int_env("OWNER_ID", required=True),
        )


def _validate_required_env(keys: list[str]):
    missing_keys = [
        key for key in keys if os.getenv(key) is None or not os.getenv(key, "").strip()
    ]
    if missing_keys:
        missing_list = ", ".join(missing_keys)
        raise ValueError(
            "Missing required config values: "
            f"{missing_list}. Fill them in config.env before starting the bot."
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
        raise ValueError(
            f"Environment variable {key} must be an integer, got: {raw!r}"
        ) from exc


def _parse_positive_int_env(key: str, default: int) -> int:
    value = _parse_int_env(key, default=default)
    if value < 1:
        raise ValueError(f"Environment variable {key} must be >= 1, got: {value}")
    return value


def _parse_str_env(key: str, default: str) -> str:
    value = os.getenv(key)
    if value is None or not value.strip():
        return default
    return value.strip()


def _parse_log_level_env(key: str, default: str) -> int:
    raw_level = os.getenv(key, default).strip().upper()
    level = getattr(logging, raw_level, None)
    if not isinstance(level, int):
        raise ValueError(
            f"Invalid log level for {key}: {raw_level!r}. "
            "Use DEBUG, INFO, WARNING, ERROR, or CRITICAL."
        )
    return level


def _parse_str_list_env(key: str, default: str) -> list[str]:
    raw_val = os.getenv(key)
    if raw_val is None or not raw_val.strip():
        raw_val = default
    return [x.strip().lower() for x in raw_val.split(",") if x.strip()]


def _parse_authorized_chat_ids(raw_chat_ids: str) -> list[int]:
    chat_ids: list[int] = []
    for chat_id in raw_chat_ids.split(","):
        trimmed = chat_id.strip()
        if not trimmed:
            continue
        try:
            chat_ids.append(int(trimmed))
        except ValueError as exc:
            raise ValueError(
                f"Invalid chat id in AUTHORIZED_CHAT_IDS: {trimmed!r}"
            ) from exc
    return chat_ids
