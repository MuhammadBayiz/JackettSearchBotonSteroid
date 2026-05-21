import asyncio
import json
import logging
import os
import sqlite3
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import quote

import aiohttp
import aiohttp.web
from aiohttp.web_request import Request
from aiohttp.web_response import Response
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

from .config import BotConfig
from .services.auth import AuthorizationService
from .services.jackett import JackettService
from .services.qbittorrent import qBittorrentService
from .services.settings import SettingsService
from .services.tmdb import TMDbService

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

        self.settings_service = SettingsService()
        self.auth_service = AuthorizationService(
            bootstrap_ids=self.config.authorized_chat_ids,
        )
        self.jackett_service = JackettService(
            jackett_url=self.config.jackett_url,
            jackett_api_key=self.config.jackett_api_key,
            jackett_password=self.config.jackett_password,
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
            settings_service=self.settings_service,
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

        @self.app.on_message(self._filters.command("settings"))
        async def settings_handler(client, message):
            await self.handlers.settings(message)

        @self.app.on_message(self._filters.command("listtorrents"))
        async def listtorrents_handler(client, message):
            await self.handlers.listtorrents(client, message)

        @self.app.on_callback_query(self._filters.regex(r"^settings_toggle:"))
        async def settings_toggle_handler(client, callback_query):
            await self.handlers.settings_toggle(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^release_cat:"))
        async def release_cat_handler(client, callback_query):
            await self.handlers.release_cat(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^release_tag:"))
        async def release_tag_handler(client, callback_query):
            await self.handlers.release_tag(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^release_dl:"))
        async def release_dl_handler(client, callback_query):
            await self.handlers.release_dl(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^release_page:"))
        async def release_page_handler(client, callback_query):
            await self.handlers.release_page(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^release_close:"))
        async def release_close_handler(client, callback_query):
            await self.handlers.release_close(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^list_page:"))
        async def list_page_handler(client, callback_query):
            await self.handlers.list_page(callback_query)

        @self.app.on_callback_query(self._filters.regex(r"^list_refresh:"))
        async def list_refresh_handler(client, callback_query):
            await self.handlers.list_refresh(client, callback_query)

        @self.app.on_inline_query()
        async def inline_query_handler(client, inline_query):
            await self.handlers.inline_query(inline_query)

    async def _extract_and_send_subtitles(self, chat_id: int, content_path: str):
        if not self.config.subtitle_languages:
            return

        target_langs = set(self.config.subtitle_languages)
        video_files = []

        if os.path.isfile(content_path):
            if content_path.lower().endswith((".mkv", ".mp4")):
                video_files.append(content_path)
        elif os.path.isdir(content_path):
            for root, _, files in os.walk(content_path):
                for f in files:
                    if f.lower().endswith((".mkv", ".mp4")):
                        video_files.append(os.path.join(root, f))

        subtitles_extracted = 0

        for video_path in video_files:
            try:
                cmd = [
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_streams", "-select_streams", "s", video_path,
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()

                if proc.returncode != 0:
                    self.logger.warning("ffprobe failed on %s", video_path)
                    continue

                streams_data = json.loads(stdout.decode())
                for stream in streams_data.get("streams", []):
                    tags = stream.get("tags", {})
                    lang = tags.get("language", "und").lower()
                    title = tags.get("title", "")

                    if len(lang) == 2:
                        lang_map = {
                            "en": "eng", "es": "spa", "fr": "fre", "de": "ger",
                            "it": "ita", "ar": "ara", "ru": "rus", "zh": "chi",
                            "ja": "jpn",
                        }
                        lang = lang_map.get(lang, lang)

                    if lang in target_langs or "all" in target_langs:
                        stream_index = stream.get("index")
                        codec_name = stream.get("codec_name", "")
                        base_name = os.path.splitext(os.path.basename(video_path))[0]
                        out_filename = f"{base_name}.{lang}.srt"
                        caption_text = lang.upper()
                        if title:
                            caption_text += f" - {title}"

                        with tempfile.TemporaryDirectory() as tmpdir:
                            out_path = os.path.join(tmpdir, out_filename)
                            ffmpeg_cmd = [
                                "ffmpeg", "-y", "-v", "quiet", "-i", video_path,
                                "-map", f"0:{stream_index}",
                            ]
                            if codec_name == "subrip":
                                ffmpeg_cmd.extend(["-c:s", "copy"])
                            else:
                                ffmpeg_cmd.extend(["-c:s", "srt"])
                            ffmpeg_cmd.append(out_path)

                            extract_proc = await asyncio.create_subprocess_exec(
                                *ffmpeg_cmd,
                                stdout=asyncio.subprocess.PIPE,
                                stderr=asyncio.subprocess.PIPE,
                            )
                            await extract_proc.communicate()

                            if extract_proc.returncode == 0 and os.path.exists(out_path):
                                await self.app.send_document(
                                    chat_id=chat_id,
                                    document=out_path,
                                    caption=caption_text,
                                )
                                subtitles_extracted += 1
                            else:
                                self.logger.warning(
                                    "Failed to extract subtitle %s from %s",
                                    stream_index, video_path,
                                )
            except Exception as exc:
                self.logger.exception(
                    "Error extracting subtitles from %s: %s", video_path, exc
                )

        if subtitles_extracted == 0:
            await self.app.send_message(chat_id=chat_id, text="No subtitles found.")

    async def handle_torrent_done(self, request: Request) -> Response:
        try:
            content_type = request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    payload = await request.json()
                except Exception:
                    raw_text = await request.text()
                    self.logger.warning(
                        "Failed to parse JSON cleanly, attempting manual parse. Raw: %s",
                        raw_text,
                    )
                    import ast
                    try:
                        payload = ast.literal_eval(raw_text)
                    except Exception:
                        payload = {}
            else:
                payload = await request.post()

            torrent_name = payload.get("name", "Unknown torrent")
            content_path = payload.get("content_path", "")
            tags_str = payload.get("tags", "")
            tags = [t.strip() for t in tags_str.split(",") if t.strip()]

            chat_id = None
            for tag in tags:
                if tag.startswith("jack:"):
                    try:
                        chat_id = int(tag[5:])
                        break
                    except ValueError:
                        pass

            if chat_id is not None:
                text_msg = f"<b>{torrent_name}</b> torrent downloaded."

                if content_path and self.config.index_base_url and self.config.media_local_path:
                    rel_path = content_path
                    if content_path.startswith(self.config.media_local_path):
                        rel_path = content_path[len(self.config.media_local_path):]
                    rel_path = rel_path.lstrip("/")
                    url_parts = [quote(p) for p in rel_path.split("/")]
                    index_url = f"{self.config.index_base_url.rstrip('/')}/{'/'.join(url_parts)}"
                    text_msg += f"\n\n<b>Download URL:</b>\n{index_url}"

                await self.app.send_message(
                    chat_id=chat_id,
                    text=text_msg,
                    parse_mode=ParseMode.HTML,
                )

                if content_path:
                    asyncio.create_task(
                        self._extract_and_send_subtitles(chat_id, content_path)
                    )
            else:
                self.logger.warning(
                    "Torrent done webhook received but no valid chat ID tag found. Tags: %s",
                    tags,
                )

            return aiohttp.web.json_response({"status": "ok"})
        except Exception as exc:
            self.logger.exception("Failed to process torrent done webhook: %s", exc)
            return aiohttp.web.json_response(
                {"status": "error", "message": str(exc)}, status=500
            )

    async def start_webhook_server(self):
        web_app = aiohttp.web.Application()
        web_app.router.add_post("/webhook/torrent-done", self.handle_torrent_done)
        runner = aiohttp.web.AppRunner(web_app)
        await runner.setup()
        site = aiohttp.web.TCPSite(
            runner, self.config.webhook_host, self.config.webhook_port
        )
        await site.start()
        self.logger.info(
            "Webhook server started on %s:%s",
            self.config.webhook_host,
            self.config.webhook_port,
        )

    def run(self):
        self.logger.info("Starting bot runtime.")

        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.start_webhook_server())

        try:
            self.app.run()
        except KeyboardInterrupt:
            self.logger.info(
                "Stop signal received (KeyboardInterrupt). Exiting gracefully."
            )
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc).lower():
                self.logger.error(
                    "Session database is locked. Another instance may be running."
                )
                raise SystemExit(2) from exc
            self.logger.exception("SQLite operational error while starting bot.")
            raise
        except FloodWait as exc:
            self.logger.error(
                "Telegram rate limited bot startup. Wait %s seconds before retrying.",
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
                show_time=True, show_level=True, show_path=False,
                markup=False, rich_tracebacks=True,
            )
            console_format = "%(message)s"
        else:
            console_handler = logging.StreamHandler()
            console_format = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"

        console_handler.setLevel(self.config.console_log_level)
        console_handler.setFormatter(logging.Formatter(console_format))

        file_handler = RotatingFileHandler(
            filename=log_path, maxBytes=10 * 1024 * 1024,
            backupCount=5, encoding="utf-8",
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
