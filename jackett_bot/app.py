import logging

from pyrogram import Client, filters

from .config import BotConfig
from .handlers.commands import CommandHandlers
from .services.auth import AuthorizationService
from .services.jackett import JackettService
from .services.telegraph import TelegraphService


class JackettSearchBot:
    def __init__(self, config: BotConfig | None = None):
        self.config = config or BotConfig.from_env("config.env")
        self.logger = self._build_logger()

        self.auth_service = AuthorizationService(
            db_path=self.config.auth_db_path,
            bootstrap_ids=self.config.authorized_chat_ids,
            logger=self.logger,
        )
        self.jackett_service = JackettService(
            jackett_url=self.config.jackett_url,
            jackett_api_key=self.config.jackett_api_key,
        )
        self.telegraph_service = TelegraphService(logger=self.logger)

        self.handlers = CommandHandlers(
            config=self.config,
            auth_service=self.auth_service,
            jackett_service=self.jackett_service,
            telegraph_service=self.telegraph_service,
            logger=self.logger,
        )

        self.app = Client(
            "jackett_bot",
            api_id=self.config.api_id,
            api_hash=self.config.api_hash,
            bot_token=self.config.token,
        )
        self._register_handlers()

    def _register_handlers(self):
        @self.app.on_message(filters.command("start"))
        async def start_handler(client, message):
            await self.handlers.start(message)

        @self.app.on_message(filters.command(["release", "relase", "r"]))
        async def release_handler(client, message):
            await self.handlers.release(message)

        @self.app.on_message(filters.command("check"))
        async def check_handler(client, message):
            await self.handlers.check(message)

        @self.app.on_message(filters.command("auth"))
        async def auth_handler(client, message):
            await self.handlers.auth(message)

        @self.app.on_message(filters.command(["unauth", "deauth"]))
        async def unauth_handler(client, message):
            await self.handlers.unauth(message)

        @self.app.on_message(filters.command(["unauthall", "deauthall"]))
        async def unauthall_handler(client, message):
            await self.handlers.unauthall(message)

        @self.app.on_message(filters.command(["authlist", "alist"]))
        async def authlist_handler(client, message):
            await self.handlers.authlist(message)

        @self.app.on_message(filters.command(["whoami", "id"]))
        async def whoami_handler(client, message):
            await self.handlers.whoami(message)

        @self.app.on_callback_query(filters.regex(r"^release_page:"))
        async def release_page_handler(client, callback_query):
            await self.handlers.release_page(callback_query)

    def run(self):
        self.logger.info("Bot is running...")
        self.app.run()

    @staticmethod
    def _build_logger() -> logging.Logger:
        logging.basicConfig(
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            level=logging.INFO,
            handlers=[logging.StreamHandler()],
        )
        logger = logging.getLogger("JackettSearchBot")
        logger.info("JackettSearchBot initialized.")
        return logger
