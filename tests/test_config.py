import os
import unittest
from unittest.mock import patch

from jackett_bot.config import BotConfig


class BotConfigValidationTests(unittest.TestCase):
    def test_max_results_must_be_positive(self):
        env = {
            "TELEGRAM_TOKEN": "token",
            "API_ID": "123",
            "API_HASH": "hash",
            "JACKETT_API_KEY": "apikey",
            "JACKETT_URL": "http://localhost:9117",
            "OWNER_ID": "1",
            "MAX_RESULTS": "0",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError) as ctx:
                BotConfig.from_env("nonexistent.env")
            self.assertIn("MAX_RESULTS", str(ctx.exception))

    def test_authorized_chat_ids_must_be_integers(self):
        env = {
            "TELEGRAM_TOKEN": "token",
            "API_ID": "123",
            "API_HASH": "hash",
            "JACKETT_API_KEY": "apikey",
            "JACKETT_URL": "http://localhost:9117",
            "OWNER_ID": "1",
            "AUTHORIZED_CHAT_IDS": "123,abc",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError) as ctx:
                BotConfig.from_env("nonexistent.env")
            self.assertIn("AUTHORIZED_CHAT_IDS", str(ctx.exception))

    def test_minimal_valid_config_uses_defaults(self):
        env = {
            "TELEGRAM_TOKEN": "token",
            "API_ID": "123",
            "API_HASH": "hash",
            "JACKETT_API_KEY": "apikey",
            "JACKETT_URL": "http://localhost:9117",
            "OWNER_ID": "1",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = BotConfig.from_env("nonexistent.env")

        self.assertEqual(cfg.default_max_results, 10)
        self.assertEqual(cfg.redact_after_seconds, 300)
        self.assertEqual(cfg.authorized_chat_ids, [])


if __name__ == "__main__":
    unittest.main()
