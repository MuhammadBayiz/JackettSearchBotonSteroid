import asyncio
import html
import logging
import time
import uuid
from dataclasses import dataclass

import httpx
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    Message,
)

from ..config import BotConfig
from ..services.auth import AuthorizationService
from ..services.jackett import JackettService, SearchResult
from ..services.tmdb import TMDbService


@dataclass
class ReleasePaginationSession:
    session_id: str
    requester_user_id: int
    chat_id: int
    query: str
    golden_popcorn: bool
    results: list[SearchResult]
    created_at: float


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class AuthTarget:
    entity_id: int
    entity_type: str
    source: str


class CommandHandlers:
    def __init__(
        self,
        config: BotConfig,
        auth_service: AuthorizationService,
        jackett_service: JackettService,
        tmdb_service: TMDbService,
        logger: logging.Logger,
    ):
        self.config = config
        self.auth_service = auth_service
        self.jackett_service = jackett_service
        self.tmdb_service = tmdb_service
        self.logger = logger
        self._pagination_sessions: dict[str, ReleasePaginationSession] = {}
        self._pagination_ttl_seconds = 3600
        self._redaction_delay_seconds = self.config.redact_after_seconds
        self._redaction_tasks: set[asyncio.Task] = set()

    async def release(self, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        chat_id = message.chat.id
        access = self._get_access_decision(user_id, chat_id)

        if not access.allowed:
            await self._reply_text(message, f"NOT AUTHORIZED ({access.reason})")
            return

        command_parts = message.text.split()[1:] if message.text else []
        if not command_parts:
            await self._reply_text(message, "PROVIDE QUERY OR IMDB ID/URL")
            return

        golden_popcorn = "--gp" in command_parts
        query_parts = [part for part in command_parts if part != "--gp"]
        query = " ".join(query_parts)

        if not query:
            await self._reply_text(message, "PROVIDE QUERY OR IMDB ID/URL")
            return

        self.logger.info(
            "Search requested | query=%s | golden_popcorn=%s | user_id=%s | chat_id=%s",
            query,
            golden_popcorn,
            user_id,
            chat_id,
        )

        sent_message = await self._try_send_searching_message(message)

        try:
            all_results = await self.jackett_service.search(
                query, golden_popcorn=golden_popcorn
            )
            all_results = self._sort_results_by_resolution_priority(all_results)

            if not all_results:
                no_results_suffix = " (with GP)" if golden_popcorn else ""
                await self._reply_text(
                    message, f"NO RESULTS{no_results_suffix}".upper()
                )
                return

            session = self._create_pagination_session(
                requester_user_id=user_id,
                chat_id=chat_id,
                query=query,
                golden_popcorn=golden_popcorn,
                results=all_results,
            )

            message_text, reply_markup = self._build_page_response(session, page=1)
            try:
                result_message = await message.reply_text(
                    message_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
            except FloodWait as exc:
                self.logger.warning(
                    "FloodWait while sending release results | wait_seconds=%s | chat_id=%s",
                    exc.value,
                    chat_id,
                )
                await self._reply_text(message, "TELEGRAM RATE LIMIT. TRY AGAIN LATER.")
                return

            self._schedule_message_redaction(session.session_id, result_message)
        except httpx.HTTPStatusError as http_err:
            self.logger.error("HTTP error occurred: %s", http_err)
            await self._reply_text(message, "HTTP ERROR OCCURRED")
        except httpx.HTTPError as http_err:
            self.logger.error("Network error occurred: %s", http_err)
            await self._reply_text(message, "NETWORK ERROR OCCURRED")
        except Exception as exc:
            self.logger.exception("Unexpected error occurred: %s", exc)
            await self._reply_text(message, "UNEXPECTED ERROR OCCURRED")
        finally:
            if sent_message is not None:
                await self._delete_message(sent_message)

    async def release_page(self, callback_query: CallbackQuery):
        parsed = self._parse_pagination_callback_data(callback_query.data)
        if not parsed:
            await self._answer_callback(
                callback_query, "INVALID PAGINATION REQUEST", show_alert=False
            )
            return

        session_id, requested_page = parsed
        session = self._get_pagination_session(session_id)
        if not session:
            await self._answer_callback(
                callback_query, "SESSION EXPIRED. RUN /RELEASE AGAIN.", show_alert=True
            )
            return

        requester_id = callback_query.from_user.id if callback_query.from_user else 0
        message_chat_id = (
            callback_query.message.chat.id if callback_query.message else 0
        )

        if (
            requester_id != session.requester_user_id
            and requester_id != self.config.owner_id
        ):
            await self._answer_callback(
                callback_query, "PAGINATION BELONGS TO ANOTHER USER", show_alert=True
            )
            return

        if message_chat_id != session.chat_id:
            await self._answer_callback(
                callback_query, "INVALID CHAT FOR THIS PAGINATION", show_alert=True
            )
            return

        if not callback_query.message:
            await self._answer_callback(
                callback_query, "MESSAGE NO LONGER AVAILABLE", show_alert=True
            )
            return

        try:
            message_text, reply_markup = self._build_page_response(
                session, requested_page
            )
            await callback_query.message.edit_text(
                message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            await self._answer_callback(callback_query)
        except FloodWait as exc:
            self.logger.warning(
                "FloodWait while changing release page | wait_seconds=%s | session_id=%s",
                exc.value,
                session_id,
            )
            await self._answer_callback(
                callback_query, "RATE LIMITED. TRY AGAIN LATER.", show_alert=False
            )
        except Exception as exc:
            self.logger.exception("Failed to update pagination message: %s", exc)
            await self._answer_callback(
                callback_query, "UNABLE TO CHANGE PAGE RIGHT NOW", show_alert=False
            )

    async def release_close(self, callback_query: CallbackQuery):
        session_id = self._parse_close_callback_data(callback_query.data)
        if not session_id:
            await self._answer_callback(
                callback_query, "INVALID CLOSE REQUEST", show_alert=False
            )
            return

        session = self._get_pagination_session(session_id)
        if not session:
            await self._answer_callback(
                callback_query, "SESSION EXPIRED", show_alert=False
            )
            return

        requester_id = callback_query.from_user.id if callback_query.from_user else 0
        message_chat_id = (
            callback_query.message.chat.id if callback_query.message else 0
        )

        if (
            requester_id != session.requester_user_id
            and requester_id != self.config.owner_id
        ):
            await self._answer_callback(
                callback_query, "ONLY REQUESTER OR OWNER CAN CLOSE", show_alert=True
            )
            return

        if message_chat_id != session.chat_id:
            await self._answer_callback(
                callback_query, "INVALID CHAT FOR THIS REQUEST", show_alert=True
            )
            return

        if not callback_query.message:
            await self._answer_callback(
                callback_query, "MESSAGE NO LONGER AVAILABLE", show_alert=True
            )
            return

        self._pagination_sessions.pop(session_id, None)

        try:
            await callback_query.message.edit_text(
                "<code>RESULTS REDACTED</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
            await self._answer_callback(
                callback_query, "RESULTS CLOSED", show_alert=False
            )
        except FloodWait as exc:
            self.logger.warning(
                "FloodWait while closing release message | wait_seconds=%s | session_id=%s",
                exc.value,
                session_id,
            )
            await self._answer_callback(
                callback_query, "RATE LIMITED. TRY AGAIN LATER.", show_alert=False
            )
        except Exception as exc:
            self.logger.exception("Failed to close release message: %s", exc)
            await self._answer_callback(
                callback_query, "UNABLE TO CLOSE RIGHT NOW", show_alert=False
            )

    async def auth(self, message: Message):
        requester_id = message.from_user.id if message.from_user else 0

        if not self._is_owner(requester_id):
            await self._reply_text(message, "ONLY OWNER CAN USE /AUTH")
            return

        target, error_message = self._extract_auth_target(message)
        if error_message:
            await self._reply_text(message, error_message.upper())
            return

        if self.auth_service.is_configured_id_authorized(target.entity_id):
            await self._reply_text(
                message,
                f"{target.entity_type.upper()} {target.entity_id} ALREADY AUTHORIZED VIA CONFIG",
            )
            return

        if self.auth_service.is_temporary_id_authorized(target.entity_id):
            await self._reply_text(
                message,
                f"{target.entity_type.upper()} {target.entity_id} ALREADY TEMP AUTHORIZED",
            )
            return

        self.auth_service.add_authorized(target.entity_id)
        await self._reply_text(
            message,
            f"AUTHORIZED {target.entity_type.upper()} {target.entity_id} ({target.source.upper()})",
        )

    async def unauth(self, message: Message):
        requester_id = message.from_user.id if message.from_user else 0

        if not self._is_owner(requester_id):
            await self._reply_text(message, "ONLY OWNER CAN USE /UNAUTH")
            return

        target, error_message = self._extract_auth_target(message)
        if error_message:
            await self._reply_text(message, error_message.upper())
            return

        if target.entity_id == self.config.owner_id and self.config.owner_id != 0:
            await self._reply_text(message, "OWNER CANNOT BE REMOVED")
            return

        if self.auth_service.is_configured_id_authorized(target.entity_id):
            await self._reply_text(
                message,
                f"{target.entity_type.upper()} {target.entity_id} IS AUTHORIZED VIA CONFIG",
            )
            return

        removed = self.auth_service.remove_authorized(target.entity_id)
        if removed:
            await self._reply_text(
                message,
                f"REMOVED TEMP AUTH FOR {target.entity_type.upper()} {target.entity_id}",
            )
        else:
            await self._reply_text(
                message,
                f"{target.entity_type.upper()} {target.entity_id} NOT TEMP AUTHORIZED",
            )

    async def unauthall(self, message: Message):
        requester_id = message.from_user.id if message.from_user else 0

        if not self._is_owner(requester_id):
            await self._reply_text(message, "ONLY OWNER CAN USE /UNAUTHALL")
            return

        removed_count = self.auth_service.clear_authorized()
        await self._reply_text(message, f"CLEARED {removed_count} TEMP AUTHORIZATIONS")

    async def inline_query(self, inline_query: InlineQuery):
        # We allow inline queries for everyone since the bot will only respond to
        # the resulting `/release <imdb_id>` command in authorized chats anyway.
        # Also, Pyrogram `InlineQuery` does not provide the target `chat.id` in all cases,
        # so checking group authorization at this stage is not feasible.

        query = inline_query.query.strip()
        if not query:
            await inline_query.answer([], cache_time=0)
            return

        try:
            results = await self.tmdb_service.search(query, limit=10)

            inline_results = []
            for result in results:
                if not result.imdb_id:
                    continue

                inline_results.append(
                    InlineQueryResultArticle(
                        title=result.display_title,
                        input_message_content=InputTextMessageContent(
                            f"/release {result.imdb_id}"
                        ),
                        description=f"Type: {result.media_type.capitalize()}",
                    )
                )

            await inline_query.answer(inline_results, cache_time=300)
        except Exception as exc:
            self.logger.exception("Failed to handle inline query: %s", exc)
            await inline_query.answer(
                results=[
                    InlineQueryResultArticle(
                        title="Error",
                        input_message_content=InputTextMessageContent(
                            "AN ERROR OCCURRED WHILE SEARCHING"
                        ),
                        description="Failed to retrieve results from TMDb.",
                    )
                ],
                cache_time=0,
            )

    @staticmethod
    def _format_reply_text(value: str | int) -> str:
        return f"<code>{html.escape(str(value))}</code>"

    async def _reply_text(self, message: Message, value: str | int):
        try:
            await message.reply_text(
                self._format_reply_text(value),
                parse_mode=ParseMode.HTML,
            )
        except FloodWait as exc:
            self.logger.warning(
                "FloodWait while sending reply | wait_seconds=%s | message=%s",
                exc.value,
                value,
            )

    async def _try_send_searching_message(self, message: Message) -> Message | None:
        try:
            return await message.reply_text(
                self._format_reply_text("SEARCHING..."),
                parse_mode=ParseMode.HTML,
            )
        except FloodWait as exc:
            self.logger.warning(
                "FloodWait while sending searching message | wait_seconds=%s | chat_id=%s",
                exc.value,
                message.chat.id,
            )
            return None

    async def _answer_callback(
        self,
        callback_query: CallbackQuery,
        text: str | None = None,
        show_alert: bool = False,
    ):
        try:
            if text is None:
                await callback_query.answer()
            else:
                await callback_query.answer(text, show_alert=show_alert)
        except FloodWait as exc:
            self.logger.warning(
                "FloodWait while answering callback | wait_seconds=%s | data=%s",
                exc.value,
                callback_query.data,
            )

    def _get_access_decision(self, user_id: int, chat_id: int) -> AccessDecision:
        if self._is_owner(user_id):
            return AccessDecision(True, "owner")
        if self.auth_service.is_configured_id_authorized(chat_id):
            return AccessDecision(True, "configured chat")
        if self.auth_service.is_temporary_id_authorized(chat_id):
            return AccessDecision(True, "temporary chat")
        if user_id and self.auth_service.is_configured_id_authorized(user_id):
            return AccessDecision(True, "configured user")
        if user_id and self.auth_service.is_temporary_id_authorized(user_id):
            return AccessDecision(True, "temporary user")
        return AccessDecision(False, "no matching user or chat authorization")

    def _is_authorized(self, user_id: int, chat_id: int) -> bool:
        return self._get_access_decision(user_id, chat_id).allowed

    def _is_owner(self, user_id: int) -> bool:
        return self.config.owner_id != 0 and user_id == self.config.owner_id

    def _extract_auth_target(
        self, message: Message
    ) -> tuple[AuthTarget | None, str | None]:
        command_parts = message.text.split()[1:] if message.text else []

        if command_parts:
            raw_target = command_parts[0].strip()
            try:
                target_id = int(raw_target)
            except ValueError:
                return (
                    None,
                    "Invalid target ID. Use /auth <id> or reply to a user message.",
                )
            return AuthTarget(
                target_id, self._infer_entity_type(target_id), "explicit id"
            ), None

        if message.reply_to_message and message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
            return AuthTarget(target_id, "user", "replied user"), None

        target_id = message.chat.id
        return AuthTarget(target_id, "chat", "current chat"), None

    @staticmethod
    def _infer_entity_type(entity_id: int) -> str:
        return "chat" if entity_id < 0 else "user"

    async def _delete_message(self, message: Message):
        try:
            await message.delete()
        except FloodWait as exc:
            self.logger.warning(
                "FloodWait while deleting message | wait_seconds=%s | message_id=%s",
                exc.value,
                message.id,
            )
        except Exception:
            pass

    def _create_pagination_session(
        self,
        requester_user_id: int,
        chat_id: int,
        query: str,
        golden_popcorn: bool,
        results: list[SearchResult],
    ) -> ReleasePaginationSession:
        self._prune_expired_sessions()

        session = ReleasePaginationSession(
            session_id=uuid.uuid4().hex[:12],
            requester_user_id=requester_user_id,
            chat_id=chat_id,
            query=query,
            golden_popcorn=golden_popcorn,
            results=results,
            created_at=time.time(),
        )
        self._pagination_sessions[session.session_id] = session
        return session

    def _get_pagination_session(
        self, session_id: str
    ) -> ReleasePaginationSession | None:
        self._prune_expired_sessions()
        return self._pagination_sessions.get(session_id)

    def _prune_expired_sessions(self):
        now = time.time()
        expired_session_ids = [
            session_id
            for session_id, session in self._pagination_sessions.items()
            if now - session.created_at > self._pagination_ttl_seconds
        ]
        for session_id in expired_session_ids:
            self._pagination_sessions.pop(session_id, None)

    def _schedule_message_redaction(self, session_id: str, message: Message):
        task = asyncio.create_task(self._redact_message_later(session_id, message))
        self._redaction_tasks.add(task)
        task.add_done_callback(self._redaction_tasks.discard)

    async def _redact_message_later(self, session_id: str, message: Message):
        await asyncio.sleep(self._redaction_delay_seconds)
        self._pagination_sessions.pop(session_id, None)
        try:
            await message.edit_text(
                "<code>RESULTS REDACTED</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=None,
            )
        except FloodWait as exc:
            self.logger.warning(
                "FloodWait while redacting release message | wait_seconds=%s | message_id=%s",
                exc.value,
                message.id,
            )
        except Exception as exc:
            self.logger.debug(
                "Failed to redact release message %s: %s", message.id, exc
            )

    def _build_page_response(
        self,
        session: ReleasePaginationSession,
        page: int,
    ) -> tuple[str, InlineKeyboardMarkup | None]:
        total_pages = self._total_pages(len(session.results))
        page = self._normalize_page(page, total_pages)

        page_size = self.config.default_max_results
        start_index = (page - 1) * page_size
        end_index = start_index + page_size

        page_results = session.results[start_index:end_index]
        body = "\n".join(result.as_html() for result in page_results)

        header_suffix = " (GP)" if session.golden_popcorn else ""
        header = (
            f"<b><u>SEARCH RESULTS{header_suffix}</u></b>\n"
            f"<b>Query:</b> <code>{html.escape(session.query)}</code>\n"
            f"<b>Page:</b> {page}/{total_pages} | <b>Total:</b> {len(session.results)}\n\n"
        )

        message_text = header + body

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        nav_buttons: list[InlineKeyboardButton] = []

        if total_pages > 1 and page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    "PREV",
                    callback_data=f"release_page:{session.session_id}:{page - 1}",
                )
            )

        if total_pages > 1 and page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    "NEXT",
                    callback_data=f"release_page:{session.session_id}:{page + 1}",
                )
            )

        if nav_buttons:
            keyboard_rows.append(nav_buttons)

        keyboard_rows.append(
            [
                InlineKeyboardButton(
                    "CLOSE",
                    callback_data=f"release_close:{session.session_id}",
                )
            ]
        )

        reply_markup = InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None
        return message_text, reply_markup

    @staticmethod
    def _sort_results_by_resolution_priority(
        results: list[SearchResult],
    ) -> list[SearchResult]:
        return sorted(
            results,
            key=lambda result: (
                CommandHandlers._resolution_priority(result.title),
                result.size_bytes,
            ),
        )

    @staticmethod
    def _resolution_priority(title: str) -> int:
        lowered = title.lower()
        if "1080p" in lowered:
            return 0
        if "2160p" in lowered:
            return 1
        return 2

    def _total_pages(self, total_results: int) -> int:
        page_size = max(self.config.default_max_results, 1)
        pages, remainder = divmod(total_results, page_size)
        return pages + (1 if remainder else 0)

    @staticmethod
    def _normalize_page(page: int, total_pages: int) -> int:
        if page < 1:
            return 1
        if page > total_pages:
            return total_pages
        return page

    @staticmethod
    def _parse_close_callback_data(data: str | None) -> str | None:
        if not data:
            return None

        parts = data.split(":")
        if len(parts) != 2 or parts[0] != "release_close":
            return None

        return parts[1]

    @staticmethod
    def _parse_pagination_callback_data(data: str | None) -> tuple[str, int] | None:
        if not data:
            return None

        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "release_page":
            return None

        session_id = parts[1]
        try:
            page = int(parts[2])
        except ValueError:
            return None

        return session_id, page
