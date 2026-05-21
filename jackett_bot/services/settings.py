import json
import os
import logging


class SettingsService:
    def __init__(self, settings_file="settings.json"):
        self.settings_file = settings_file
        self.logger = logging.getLogger(__name__)
        self.settings = self._load_settings()

    def _load_settings(self):
        if not os.path.exists(self.settings_file):
            return {"disabled_categories": []}
        try:
            with open(self.settings_file, "r") as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(
                "Failed to load settings from %s: %s", self.settings_file, e
            )
            return {"disabled_categories": []}

    def _save_settings(self):
        try:
            with open(self.settings_file, "w") as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            self.logger.error(
                "Failed to save settings to %s: %s", self.settings_file, e
            )

    def get_disabled_categories(self) -> list[str]:
        return self.settings.get("disabled_categories", [])

    def toggle_category(self, category_name: str):
        disabled = self.get_disabled_categories()
        if category_name in disabled:
            disabled.remove(category_name)
        else:
            disabled.append(category_name)
        self.settings["disabled_categories"] = disabled
        self._save_settings()
