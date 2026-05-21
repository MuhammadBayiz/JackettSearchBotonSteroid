from __future__ import annotations

import json
import logging
import os


AVAILABLE_CATEGORIES = [
    "Movies",
    "TV",
    "XXX",
    "Audio",
    "Books",
    "PC",
    "Console",
    "Others",
]

CATEGORY_ID_MAP = {
    "Movies": "2000",
    "TV": "5000",
    "XXX": "6000",
    "Audio": "3000",
    "Books": "7000",
    "PC": "4000",
    "Console": "1000",
    "Others": "8000",
}


class SettingsService:
    def __init__(self, settings_file: str = "settings.json"):
        self.settings_file = settings_file
        self.logger = logging.getLogger(__name__)
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.exists(self.settings_file):
            return {"disabled_categories": []}
        try:
            with open(self.settings_file) as f:
                return json.load(f)
        except Exception as exc:
            self.logger.error("Failed to load settings: %s", exc)
            return {"disabled_categories": []}

    def _save(self) -> None:
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self._data, f, indent=4)
        except Exception as exc:
            self.logger.error("Failed to save settings: %s", exc)

    def get_disabled_categories(self) -> list[str]:
        return self._data.get("disabled_categories", [])

    def toggle_category(self, category: str) -> None:
        disabled = self.get_disabled_categories()
        if category in disabled:
            disabled.remove(category)
        else:
            disabled.append(category)
        self._data["disabled_categories"] = disabled
        self._save()

    def get_active_categories(self) -> list[str]:
        disabled = self.get_disabled_categories()
        return [c for c in AVAILABLE_CATEGORIES if c not in disabled]

    def category_to_id(self, category: str) -> str | None:
        return CATEGORY_ID_MAP.get(category)
