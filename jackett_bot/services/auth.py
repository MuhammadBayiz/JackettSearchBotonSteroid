import threading
from typing import Iterable


class AuthorizationService:
    def __init__(
        self,
        bootstrap_ids: Iterable[int] | None = None,
    ):
        self._lock = threading.RLock()
        self._configured_ids: set[int] = set()
        self._temporary_ids: set[int] = set()

        if bootstrap_ids:
            self.bootstrap_authorizations(bootstrap_ids)

    def add_authorized(self, entity_id: int) -> bool:
        normalized_id = self._normalize_id(entity_id)
        with self._lock:
            if normalized_id in self._configured_ids or normalized_id in self._temporary_ids:
                return False
            self._temporary_ids.add(normalized_id)
            return True

    def remove_authorized(self, entity_id: int) -> bool:
        normalized_id = self._normalize_id(entity_id)
        with self._lock:
            if normalized_id in self._temporary_ids:
                self._temporary_ids.remove(normalized_id)
                return True
            return False

    def clear_authorized(self) -> int:
        with self._lock:
            removed_count = len(self._temporary_ids)
            self._temporary_ids.clear()
            return removed_count

    def list_configured_ids(self) -> list[int]:
        with self._lock:
            return sorted(self._configured_ids)

    def list_temporary_ids(self) -> list[int]:
        with self._lock:
            return sorted(self._temporary_ids)

    def is_configured_id_authorized(self, entity_id: int) -> bool:
        normalized_id = self._normalize_id(entity_id)
        with self._lock:
            return normalized_id in self._configured_ids

    def is_temporary_id_authorized(self, entity_id: int) -> bool:
        normalized_id = self._normalize_id(entity_id)
        with self._lock:
            return normalized_id in self._temporary_ids

    def bootstrap_authorizations(self, entity_ids: Iterable[int]):
        normalized_ids = {self._normalize_id(entity_id) for entity_id in entity_ids}
        with self._lock:
            self._configured_ids.update(normalized_ids)

    @staticmethod
    def _normalize_id(entity_id: int) -> int:
        return int(entity_id)
