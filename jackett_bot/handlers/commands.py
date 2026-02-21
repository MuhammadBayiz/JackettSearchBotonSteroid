import logging
import time
import uuid
from dataclasses import dataclass

import requests
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ..config import BotConfig
from ..services.auth import AuthorizationService
from ..services.jackett import JackettService, SearchResult
from ..services.ptp import check_ptp
from ..services.telegraph import TelegraphService


@dataclass
class ReleasePaginationSession:
    session_id: str
    requester_user_id: int
    chat_id: int
    query: str
    golden_popcorn: bool
    results: list[SearchResult]
    telegraph_url: str | None
    created_at: float


class CommandHandlers:
    def __init__(
        self,
        config: BotConfig,
        auth_service: AuthorizationService,
        jackett_service: JackettService,
        telegraph_service: TelegraphService,
        logger: logging.Logger,
    ):
        self.config = config
        self.auth_service = auth_service
        self.jackett_service = jackett_service
        self.telegraph_service = telegraph_service
        self.logger = logger
        self._pagination_sessions: dict[str, ReleasePaginationSession] = {}
        self._pagination_ttl_seconds = 3600

    async def start(self, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        chat_id = message.chat.id

        if self._is_authorized(user_id, chat_id):
            await message.reply_text("Bot Started")
        else:
            await message.reply_text("Not Authorized")

    async def release(self, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        chat_id = message.chat.id

        if not self._is_authorized(user_id, chat_id):
            await message.reply_text("Not Authorized")
            return

        command_parts = message.text.split()[1:] if message.text else []
        if not command_parts:
            await message.reply_text("Please Provide Query or IMDb ID/URL")
            return

        golden_popcorn = "-gp" in command_parts
        query_parts = [part for part in command_parts if part != "-gp"]
        query = " ".join(query_parts)

        if not query:
            await message.reply_text("Please Provide Query or IMDb ID/URL")
            return

        sent_message = await message.reply_text("Please Wait, Searching...")

        try:
            all_results = self.jackett_service.search(query, golden_popcorn=golden_popcorn)

            if not all_results:
                no_results_suffix = " (with GP)" if golden_popcorn else ""
                await message.reply_text(f"No Results{no_results_suffix}")
                return

            telegraph_url = self.telegraph_service.send_results_to_telegraph(
                [result.as_text() for result in all_results]
            )

            session = self._create_pagination_session(
                requester_user_id=user_id,
                chat_id=chat_id,
                query=query,
                golden_popcorn=golden_popcorn,
                results=all_results,
                telegraph_url=telegraph_url,
            )

            message_text, reply_markup = self._build_page_response(session, page=1)
            await message.reply_text(
                message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
        except requests.exceptions.HTTPError as http_err:
            self.logger.error("HTTP error occurred: %s", http_err)
            await message.reply_text("HTTP Error Occurred")
        except Exception as exc:
            self.logger.exception("Unexpected error occurred: %s", exc)
            await message.reply_text("Unexpected Error Occurred")
        finally:
            await self._delete_message(sent_message)

    async def release_page(self, callback_query: CallbackQuery):
        parsed = self._parse_pagination_callback_data(callback_query.data)
        if not parsed:
            await callback_query.answer("Invalid pagination request.", show_alert=False)
            return

        session_id, requested_page = parsed
        session = self._get_pagination_session(session_id)
        if not session:
            await callback_query.answer("Session expired. Run /release again.", show_alert=True)
            return

        requester_id = callback_query.from_user.id if callback_query.from_user else 0
        message_chat_id = callback_query.message.chat.id if callback_query.message else 0

        if requester_id != session.requester_user_id and requester_id != self.config.owner_id:
            await callback_query.answer("This pagination belongs to another user.", show_alert=True)
            return

        if message_chat_id != session.chat_id:
            await callback_query.answer("Invalid chat for this pagination.", show_alert=True)
            return

        if not callback_query.message:
            await callback_query.answer("Message no longer available.", show_alert=True)
            return

        try:
            message_text, reply_markup = self._build_page_response(session, requested_page)
            await callback_query.message.edit_text(
                message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            await callback_query.answer()
        except Exception as exc:
            self.logger.exception("Failed to update pagination message: %s", exc)
            await callback_query.answer("Unable to change page right now.", show_alert=False)

    async def check(self, message: Message):
        await check_ptp(message)

    async def auth(self, message: Message):
        requester_id = message.from_user.id if message.from_user else 0

        if not self._is_owner(requester_id):
            await message.reply_text("Only owner can use /auth")
            return

        target_id, source, error_message = self._extract_auth_target(message)
        if error_message:
            await message.reply_text(error_message)
            return

        created = self.auth_service.add_authorized(target_id)
        if created:
            await message.reply_text(
                f"Authorized <code>{target_id}</code> ({source})",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text(
                f"Already authorized <code>{target_id}</code> ({source})",
                parse_mode=ParseMode.HTML,
            )

    async def unauth(self, message: Message):
        requester_id = message.from_user.id if message.from_user else 0

        if not self._is_owner(requester_id):
            await message.reply_text("Only owner can use /unauth")
            return

        target_id, source, error_message = self._extract_auth_target(message)
        if error_message:
            await message.reply_text(error_message)
            return

        if target_id == self.config.owner_id and self.config.owner_id != 0:
            await message.reply_text("Owner is always authorized and cannot be removed.")
            return

        removed = self.auth_service.remove_authorized(target_id)
        if removed:
            await message.reply_text(
                f"Unauthorized <code>{target_id}</code> ({source})",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text(
                f"ID is not authorized: <code>{target_id}</code>",
                parse_mode=ParseMode.HTML,
            )

        remaining_reasons = self._authorization_reasons(requester_id, message.chat.id)
        if remaining_reasons:
            reason_text = ", ".join(remaining_reasons)
            await message.reply_text(
                f"You are still authorized here via: <code>{reason_text}</code>",
                parse_mode=ParseMode.HTML,
            )

    async def unauthall(self, message: Message):
        requester_id = message.from_user.id if message.from_user else 0

        if not self._is_owner(requester_id):
            await message.reply_text("Only owner can use /unauthall")
            return

        removed_count = self.auth_service.clear_authorized()
        await message.reply_text(
            f"Removed <code>{removed_count}</code> authorized ID(s) from database.",
            parse_mode=ParseMode.HTML,
        )

        if self._is_owner(requester_id):
            await message.reply_text("Owner access remains active by design.")

    async def authlist(self, message: Message):
        requester_id = message.from_user.id if message.from_user else 0

        if not self._is_owner(requester_id):
            await message.reply_text("Only owner can use /authlist")
            return

        authorized_ids = self.auth_service.list_authorized_ids()
        if not authorized_ids:
            await message.reply_text("No authorized IDs in database.")
            return

        display_ids = authorized_ids[:100]
        lines = ["<b>Authorized IDs</b>"]
        lines.extend(f"- <code>{entity_id}</code>" for entity_id in display_ids)

        if len(authorized_ids) > len(display_ids):
            lines.append(f"... and {len(authorized_ids) - len(display_ids)} more")

        await message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

    async def whoami(self, message: Message):
        user_id = message.from_user.id if message.from_user else 0
        chat_id = message.chat.id

        reasons = self._authorization_reasons(user_id, chat_id)
        is_authorized = bool(reasons)
        reason_text = ", ".join(reasons) if reasons else "none"

        response = (
            f"<b>User ID:</b> <code>{user_id}</code>\n"
            f"<b>Chat ID:</b> <code>{chat_id}</code>\n"
            f"<b>Authorized:</b> {'yes' if is_authorized else 'no'}\n"
            f"<b>Reason:</b> <code>{reason_text}</code>"
        )
        await message.reply_text(response, parse_mode=ParseMode.HTML)

    def _is_authorized(self, user_id: int, chat_id: int) -> bool:
        return bool(self._authorization_reasons(user_id, chat_id))

    def _is_owner(self, user_id: int) -> bool:
        return self.config.owner_id != 0 and user_id == self.config.owner_id

    def _authorization_reasons(self, user_id: int, chat_id: int) -> list[str]:
        reasons: list[str] = []

        if self._is_owner(user_id):
            reasons.append("owner")
        if self.auth_service.is_id_authorized(chat_id):
            reasons.append("chat")
        if user_id and self.auth_service.is_id_authorized(user_id):
            reasons.append("user")

        return reasons

    def _extract_auth_target(self, message: Message) -> tuple[int, str, str | None]:
        command_parts = message.text.split()[1:] if message.text else []

        if command_parts:
            raw_target = command_parts[0].strip()
            try:
                return int(raw_target), "explicit id", None
            except ValueError:
                return 0, "", "Invalid target ID. Use /auth <id> or reply to a user message."

        if message.reply_to_message and message.reply_to_message.from_user:
            return message.reply_to_message.from_user.id, "replied user", None

        return message.chat.id, "current chat", None

    async def _delete_message(self, message: Message):
        try:
            await message.delete()
        except Exception:
            # Deleting loading message can fail if Telegram already removed it.
            pass

    def _create_pagination_session(
        self,
        requester_user_id: int,
        chat_id: int,
        query: str,
        golden_popcorn: bool,
        results: list[SearchResult],
        telegraph_url: str | None,
    ) -> ReleasePaginationSession:
        self._prune_expired_sessions()

        session = ReleasePaginationSession(
            session_id=uuid.uuid4().hex[:12],
            requester_user_id=requester_user_id,
            chat_id=chat_id,
            query=query,
            golden_popcorn=golden_popcorn,
            results=results,
            telegraph_url=telegraph_url,
            created_at=time.time(),
        )
        self._pagination_sessions[session.session_id] = session
        return session

    def _get_pagination_session(self, session_id: str) -> ReleasePaginationSession | None:
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
            f"<b>Query:</b> <code>{session.query}</code>\n"
            f"<b>Page:</b> {page}/{total_pages} | <b>Total:</b> {len(session.results)}\n\n"
        )

        message_text = header + body
        if not session.telegraph_url:
            message_text += "\n\n<i>Telegraph unavailable, showing paginated in-chat results.</i>"

        keyboard_rows: list[list[InlineKeyboardButton]] = []
        nav_buttons: list[InlineKeyboardButton] = []

        if total_pages > 1 and page > 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    "Prev",
                    callback_data=f"release_page:{session.session_id}:{page - 1}",
                )
            )

        if total_pages > 1 and page < total_pages:
            nav_buttons.append(
                InlineKeyboardButton(
                    "Next",
                    callback_data=f"release_page:{session.session_id}:{page + 1}",
                )
            )

        if nav_buttons:
            keyboard_rows.append(nav_buttons)

        if session.telegraph_url:
            keyboard_rows.append([InlineKeyboardButton("RESULTS", url=session.telegraph_url)])

        reply_markup = InlineKeyboardMarkup(keyboard_rows) if keyboard_rows else None
        return message_text, reply_markup

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
