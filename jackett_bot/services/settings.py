from __future__ import annotations

import json
import logging
import os


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

    def toggle_category(self, category_name: str) -> None:
        disabled = self.get_disabled_categories()
        if category_name in disabled:
            disabled.remove(category_name)
        else:
            disabled.append(category_name)
        self._data["disabled_categories"] = disabled
        self._save()

    def is_category_enabled(self, category_name: str) -> bool:
        return category_name not in self.get_disabled_categories()
