import json
import os
from typing import Dict, Any

DEFAULT_SETTINGS = {
    "test_interval_seconds": 300,
    "request_timeout_seconds": 30,
    "max_workers": 5,
    "test_prompt": "say hello in world",
    "race_timeout_seconds": 0
}

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runtime", "settings.json")


class SettingsManager:
    def __init__(self):
        self._settings: Dict[str, Any] = {}
        self._load()

    def _load(self):
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                self._settings = json.load(f)
        else:
            self._settings = dict(DEFAULT_SETTINGS)
            self._save()

    def _save(self):
        os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, indent=2, ensure_ascii=False)

    def get(self, key: str, default=None):
        return self._settings.get(key, default)

    def get_all(self) -> Dict[str, Any]:
        return dict(self._settings)

    def update(self, updates: Dict[str, Any]):
        self._settings.update(updates)
        self._save()

    def reset_to_defaults(self):
        self._settings = dict(DEFAULT_SETTINGS)
        self._save()
