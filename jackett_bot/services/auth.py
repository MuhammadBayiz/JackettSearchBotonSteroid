import logging
import os
import sqlite3
from typing import Iterable


class AuthorizationService:
    def __init__(
        self,
        db_path: str = "auth.db",
        bootstrap_ids: Iterable[int] | None = None,
        logger: logging.Logger | None = None,
    ):
        self.db_path = db_path
        self.logger = logger or logging.getLogger("JackettSearchBot")
        self._ensure_parent_directory()
        self._initialize_db()

        if bootstrap_ids:
            self.bootstrap_authorizations(bootstrap_ids)

    def is_authorized(self, user_id: int, chat_id: int) -> bool:
        if self.is_id_authorized(chat_id):
            return True
        if user_id and self.is_id_authorized(user_id):
            return True
        return False

    def is_id_authorized(self, entity_id: int) -> bool:
        normalized_id = self._normalize_id(entity_id)

        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM authorized_entities WHERE entity_id = ? LIMIT 1",
                (normalized_id,),
            )
            return cursor.fetchone() is not None

    def add_authorized(self, entity_id: int) -> bool:
        normalized_id = self._normalize_id(entity_id)

        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO authorized_entities (entity_id) VALUES (?)",
                (normalized_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def remove_authorized(self, entity_id: int) -> bool:
        normalized_id = self._normalize_id(entity_id)

        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM authorized_entities WHERE entity_id = ?",
                (normalized_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_authorized(self) -> int:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM authorized_entities")
            conn.commit()

            if cursor.rowcount is not None and cursor.rowcount >= 0:
                return int(cursor.rowcount)
            return int(conn.total_changes)

    def list_authorized_ids(self) -> list[int]:
        with self._connect() as conn:
            cursor = conn.execute(
                "SELECT entity_id FROM authorized_entities ORDER BY entity_id"
            )
            return [row[0] for row in cursor.fetchall()]

    def bootstrap_authorizations(self, entity_ids: Iterable[int]):
        normalized_ids = [self._normalize_id(entity_id) for entity_id in entity_ids]
        if not normalized_ids:
            return

        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO authorized_entities (entity_id) VALUES (?)",
                [(entity_id,) for entity_id in normalized_ids],
            )
            conn.commit()

    def _initialize_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS authorized_entities (
                    entity_id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def _ensure_parent_directory(self):
        parent_dir = os.path.dirname(os.path.abspath(self.db_path))
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _normalize_id(entity_id: int) -> int:
        return int(entity_id)
