import logging
import unittest
from types import SimpleNamespace

from jackett_bot.config import BotConfig
from jackett_bot.handlers.commands import CommandHandlers
from jackett_bot.services.auth import AuthorizationService
from jackett_bot.services.jackett import SearchResult


class _DummyJackettService:
    async def search(self, query: str, golden_popcorn: bool = False):
        return []


def _make_config() -> BotConfig:
    return BotConfig(
        token="x",
        api_id=1,
        api_hash="y",
        jackett_api_key="k",
        jackett_url="http://localhost:9117",
        default_max_results=10,
        redact_after_seconds=300,
        log_file_path="logs/test.log",
        console_log_level=logging.INFO,
        file_log_level=logging.DEBUG,
        authorized_chat_ids=[],
        owner_id=999,
    )


def _make_handlers(auth_service: AuthorizationService | None = None) -> CommandHandlers:
    return CommandHandlers(
        config=_make_config(),
        auth_service=auth_service or AuthorizationService(),
        jackett_service=_DummyJackettService(),
        logger=logging.getLogger("tests.handlers"),
    )


class CommandHandlersAccessTests(unittest.TestCase):
    def test_owner_access_decision(self):
        handlers = _make_handlers()
        decision = handlers._get_access_decision(user_id=999, chat_id=-1001)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "owner")

    def test_configured_chat_access_decision(self):
        auth = AuthorizationService(bootstrap_ids=[-100123])
        handlers = _make_handlers(auth)
        decision = handlers._get_access_decision(user_id=7, chat_id=-100123)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "configured chat")

    def test_temporary_user_access_decision(self):
        auth = AuthorizationService()
        auth.add_authorized(12345)
        handlers = _make_handlers(auth)
        decision = handlers._get_access_decision(user_id=12345, chat_id=-100123)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "temporary user")

    def test_unauthorized_access_decision(self):
        handlers = _make_handlers()
        decision = handlers._get_access_decision(user_id=7, chat_id=-100123)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "no matching user or chat authorization")


class CommandHandlersTargetExtractionTests(unittest.TestCase):
    def test_extract_auth_target_explicit_user(self):
        handlers = _make_handlers()
        msg = SimpleNamespace(
            text="/auth 123",
            reply_to_message=None,
            chat=SimpleNamespace(id=-1001),
        )
        target, error = handlers._extract_auth_target(msg)
        self.assertIsNone(error)
        self.assertEqual(target.entity_id, 123)
        self.assertEqual(target.entity_type, "user")
        self.assertEqual(target.source, "explicit id")

    def test_extract_auth_target_reply_user(self):
        handlers = _make_handlers()
        msg = SimpleNamespace(
            text="/auth",
            reply_to_message=SimpleNamespace(from_user=SimpleNamespace(id=456)),
            chat=SimpleNamespace(id=-1001),
        )
        target, error = handlers._extract_auth_target(msg)
        self.assertIsNone(error)
        self.assertEqual(target.entity_id, 456)
        self.assertEqual(target.entity_type, "user")
        self.assertEqual(target.source, "replied user")

    def test_extract_auth_target_default_chat(self):
        handlers = _make_handlers()
        msg = SimpleNamespace(
            text="/auth",
            reply_to_message=None,
            chat=SimpleNamespace(id=-1001),
        )
        target, error = handlers._extract_auth_target(msg)
        self.assertIsNone(error)
        self.assertEqual(target.entity_id, -1001)
        self.assertEqual(target.entity_type, "chat")
        self.assertEqual(target.source, "current chat")


class CommandHandlersParsingAndSortTests(unittest.TestCase):
    def test_parse_pagination_callback_data(self):
        parsed = CommandHandlers._parse_pagination_callback_data("release_page:abc123:2")
        self.assertEqual(parsed, ("abc123", 2))

    def test_parse_pagination_callback_data_invalid(self):
        self.assertIsNone(CommandHandlers._parse_pagination_callback_data("release_page:abc123:notint"))
        self.assertIsNone(CommandHandlers._parse_pagination_callback_data("bad:abc:2"))

    def test_parse_close_callback_data(self):
        self.assertEqual(CommandHandlers._parse_close_callback_data("release_close:abc123"), "abc123")
        self.assertIsNone(CommandHandlers._parse_close_callback_data("release_close"))

    def test_sort_results_by_resolution_priority(self):
        results = [
            SearchResult(title="Movie 720p", age="1 d", size="1 GB", size_bytes=1_000_000_000),
            SearchResult(title="Movie 2160p", age="1 d", size="2 GB", size_bytes=2_000_000_000),
            SearchResult(title="Movie 1080p big", age="1 d", size="4 GB", size_bytes=4_000_000_000),
            SearchResult(title="Movie 1080p small", age="1 d", size="3 GB", size_bytes=3_000_000_000),
        ]
        sorted_results = CommandHandlers._sort_results_by_resolution_priority(results)
        sorted_titles = [r.title for r in sorted_results]
        self.assertEqual(
            sorted_titles,
            ["Movie 1080p small", "Movie 1080p big", "Movie 2160p", "Movie 720p"],
        )


if __name__ == "__main__":
    unittest.main()
