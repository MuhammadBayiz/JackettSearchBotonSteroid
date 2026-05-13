import asyncio
import logging
import sqlite3
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import BotConfig
from .services.auth import AuthorizationService
from .services.jackett import JackettService
from .services.qbittorrent import qBittorrentService
from .services.tmdb import TMDbService
from pyrogram.errors import FloodWait

try:
    from rich.logging import RichHandler
except ImportError:
    RichHandler = None


class JackettSearchBot:
    def __init__(self, config: BotConfig | None = None):
        self.config = config or BotConfig.from_env("config.env")
        self.logger = self._build_logger()

        from .handlers.commands import CommandHandlers
        from pyrogram import Client, filters

        self._filters = filters

        self.auth_service = AuthorizationService(
            bootstrap_ids=self.config.authorized_chat_ids,
        )
        self.jackett_service = JackettService(
            jackett_url=self.config.jackett_url,
            jackett_api_key=self.config.jackett_api_key,
        )
        self.tmdb_service = TMDbService(
            tmdb_api_key=self.config.tmdb_api_key,
        )
        self.qbt_service = qBittorrentService(
            host=self.config.qbittorrent_host,
            username=self.config.qbittorrent_username,
            password=self.config.qbittorrent_password,
            category=self.config.qbittorrent_category,
        )

        self.handlers = CommandHandlers(
            config=self.config,
            auth_service=self.auth_service,
            jackett_service=self.jackett_service,
            tmdb_service=self.tmdb_service,
            qbt_service=self.qbt_service,
            logger=self.logger,
        )

        self.app = Client(
            "jackett_bot",
            api_id=self.config.api_id,
            api_hash=self.config.api_hash,
            bot_token=self.config.token,
        )
        self._register_handlers()

    @classmethod
    def initialize(cls, env_file: str = "config.env") -> "JackettSearchBot":
        config = BotConfig.from_env(env_file)
        bot = cls(config=config)
        bot.logger.info("Initialization complete. Configuration is valid.")
        return bot

    def _register_handlers(self):
        @self.app.on_message(self._filters.command("release"))
        async def release_handler(client, message):
            await self.handlers.release(message)

        @self.app.on_message(self._filters.command("auth"))
        async def auth_handler(client, message):
            await self.handlers.auth(message)

        @self.app.on_message(self._filters.command("unauth"))
        async def unauth_handler(client, message):
            await self.handlers.unauth(message)

        @self.app.on_message(self._filters.command("unauthall"))
        async def unauthall_handler(client, message):
            await self.handlers.unauthall(message)

        @self.app.on_message(self._filters.command("listtorrents"))
        async def listtorrents_handler(client, message):
            await self.handlers.listtorrents(client, message)

        @self.app.on_callback_query(self._filters.regex(r"^release_page:"))
        async def release_page_handler(client, callback_query):
            await self.handlers.release_page(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^release_close:"))
        async def release_close_handler(client, callback_query):
            await self.handlers.release_close(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^qbt_add:"))
        async def qbt_add_handler(client, callback_query):
            await self.handlers.qbt_add(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^list_page:"))
        async def list_page_handler(client, callback_query):
            await self.handlers.list_page(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^list_refresh:"))
        async def list_refresh_handler(client, callback_query):
            await self.handlers.list_refresh(client, callback_query)

        @self.app.on_inline_query()
        async def inline_query_handler(client, inline_query):
            await self.handlers.inline_query(inline_query)

    def run(self):
        self.logger.info("Starting bot runtime.")
        try:
            self.app.run()
        except KeyboardInterrupt:
            self.logger.info(
                "Stop signal received (KeyboardInterrupt). Exiting gracefully."
            )
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc).lower():
                self.logger.error(
                    "Session database is locked. This usually means another bot instance is still running "
                    "or a stale session lock exists."
                )
                self.logger.error(
                    "Action: stop other instances, remove any stale session lock if needed, and retry. "
                    "This build uses a persisted session to reduce repeated bot re-authorization on restart."
                )
                raise SystemExit(2) from exc
            self.logger.exception("SQLite operational error while starting bot.")
            raise
        except FloodWait as exc:
            self.logger.error(
                "Telegram rate limited bot authorization/startup. Wait %s seconds before retrying.",
                exc.value,
            )
            raise SystemExit(3) from exc
        except Exception:
            self.logger.exception("Fatal runtime error. Bot stopped unexpectedly.")
            raise
        finally:
            self._shutdown_services()
            self.logger.info("Bot shutdown complete.")

    def _shutdown_services(self):
        async def _close_services():
            await self.jackett_service.close()
            await self.tmdb_service.close()

        try:
            asyncio.run(_close_services())
        except Exception:
            self.logger.exception(
                "Error while closing service clients during shutdown."
            )

    def _build_logger(self) -> logging.Logger:
        log_path = Path(self.config.log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if RichHandler is not None:
            console_handler = RichHandler(
                show_time=True,
                show_level=True,
                show_path=False,
                markup=False,
                rich_tracebacks=True,
            )
            console_format = "%(message)s"
        else:
            console_handler = logging.StreamHandler()
            console_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

        console_handler.setLevel(self.config.console_log_level)
        console_handler.setFormatter(logging.Formatter(console_format))

        file_handler = RotatingFileHandler(
            filename=log_path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(self.config.file_log_level)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | "
                "%(filename)s:%(lineno)d | %(funcName)s | %(message)s"
            )
        )

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        root_logger.handlers.clear()
        root_logger.addHandler(file_handler)

        logger = logging.getLogger("JackettSearchBot")
        logger.handlers.clear()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)
        logger.propagate = True

        self._configure_third_party_loggers()
        logger.info("JackettSearchBot initialized.")
        logger.info(
            "Logging configured | console=%s | file=%s | path=%s",
            logging.getLevelName(self.config.console_log_level),
            logging.getLevelName(self.config.file_log_level),
            str(log_path.resolve()),
        )
        return logger

    def _configure_third_party_loggers(self):
        for logger_name in ("pyrogram", "httpx", "httpcore", "asyncio"):
            logging.getLogger(logger_name).setLevel(logging.WARNING)
