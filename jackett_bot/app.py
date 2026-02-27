import asyncio
import logging
import sqlite3
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import BotConfig
from .services.auth import AuthorizationService
from .services.jackett import JackettService
from .services.ptp import PTPService


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
        self.ptp_service = PTPService()

        self.handlers = CommandHandlers(
            config=self.config,
            auth_service=self.auth_service,
            jackett_service=self.jackett_service,
            ptp_service=self.ptp_service,
            logger=self.logger,
        )

        self.app = Client(
            "jackett_bot",
            api_id=self.config.api_id,
            api_hash=self.config.api_hash,
            bot_token=self.config.token,
            in_memory=True,
        )
        self._register_handlers()

    @classmethod
    def initialize(cls, env_file: str = "config.env") -> "JackettSearchBot":
        config = BotConfig.from_env(env_file)
        bot = cls(config=config)
        bot.logger.info("Initialization complete. Configuration is valid.")
        return bot

    def _register_handlers(self):
        @self.app.on_message(self._filters.command("start"))
        async def start_handler(client, message):
            await self.handlers.start(message)

        @self.app.on_message(self._filters.command("help"))
        async def help_handler(client, message):
            await self.handlers.help(message)

        @self.app.on_message(self._filters.command(["release", "relase", "r"]))
        async def release_handler(client, message):
            await self.handlers.release(message)

        @self.app.on_message(self._filters.command("check"))
        async def check_handler(client, message):
            await self.handlers.check(message)

        @self.app.on_message(self._filters.command("auth"))
        async def auth_handler(client, message):
            await self.handlers.auth(message)

        @self.app.on_message(self._filters.command(["unauth", "deauth"]))
        async def unauth_handler(client, message):
            await self.handlers.unauth(message)

        @self.app.on_message(self._filters.command(["unauthall", "deauthall"]))
        async def unauthall_handler(client, message):
            await self.handlers.unauthall(message)

        @self.app.on_callback_query(self._filters.regex(r"^release_page:"))
        async def release_page_handler(client, callback_query):
            await self.handlers.release_page(callback_query)

    def run(self):
        self.logger.info("Starting bot runtime.")
        try:
            self.app.run()
        except KeyboardInterrupt:
            self.logger.info("Stop signal received (KeyboardInterrupt). Exiting gracefully.")
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc).lower():
                self.logger.error(
                    "Session database is locked. This usually means another bot instance is still running "
                    "or a stale session lock exists."
                )
                self.logger.error(
                    "Action: stop other instances and retry. This build uses in-memory session mode to avoid "
                    "persistent session locks."
                )
                raise SystemExit(2) from exc
            self.logger.exception("SQLite operational error while starting bot.")
            raise
        except Exception:
            self.logger.exception("Fatal runtime error. Bot stopped unexpectedly.")
            raise
        finally:
            self._shutdown_services()
            self.logger.info("Bot shutdown complete.")

    def _shutdown_services(self):
        async def _close_services():
            await self.jackett_service.close()
            await self.ptp_service.close()

        try:
            asyncio.run(_close_services())
        except Exception:
            self.logger.exception("Error while closing service clients during shutdown.")

    def _build_logger(self) -> logging.Logger:
        log_path = Path(self.config.log_file_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(self.config.console_log_level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )

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
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

        logger = logging.getLogger("JackettSearchBot")
        logger.info("JackettSearchBot initialized.")
        logger.info(
            "Logging configured | console=%s | file=%s | path=%s",
            logging.getLevelName(self.config.console_log_level),
            logging.getLevelName(self.config.file_log_level),
            str(log_path.resolve()),
        )
        return logger
