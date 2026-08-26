"""Хранение и чтение настроек приложения (JSON-конфиг + история загрузок)."""

import json
import os
import sys
from pathlib import Path
from typing import Any


def _resolve_config_dir() -> Path:
    """Из исходников — папка config/ рядом с проектом (удобно смотреть/дебажить).
    Из PyInstaller-сборки (`sys.frozen`) — %APPDATA%\\NeoLoader: exe распаковывается
    во временную папку при каждом запуске (или лежит рядом с exe только для чтения),
    поэтому писать туда settings.json/историю нельзя — они пропадут при следующем запуске."""
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or str(Path.home())
        return Path(appdata) / "NeoLoader"
    return Path(__file__).resolve().parent.parent / "config"


CONFIG_DIR = _resolve_config_dir()
CONFIG_FILE = CONFIG_DIR / "settings.json"

MAX_HISTORY_ENTRIES = 50

DEFAULT_SETTINGS: dict[str, Any] = {
    "theme": "dark",
    "language": "ru",
    "download_folder": str(Path.home() / "Downloads"),
    "auto_update_ytdlp": False,
    "default_quality": "1080p",
    "audio_only": False,
    "audio_format": "mp3",
    "audio_bitrate": "192",
    "create_playlist_folder": True,
    "remove_after_download": False,
    "concurrent_downloads": 1,
    "proxy": "",
    "cookies_from_browser": "none",
    "filename_template": "%(title)s.%(ext)s",
    "output_container": "mp4",
    # Саммери по видео: без ключа работает встроенный (экстрактивный) алгоритм,
    # с ключом — Claude. Ключ хранится только в этом файле и уходит только в
    # api.anthropic.com (см. core/summarizer.py).
    "summary_api_key": "",
    "summary_model": "claude-opus-5",
    "history": [],
}


class SettingsManager:
    """Читает/пишет settings.json и хранит историю последних загрузок."""

    def __init__(self) -> None:
        self._settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        if not CONFIG_FILE.exists():
            self.save()
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Дозаполняем недостающие ключи дефолтами (например после обновления приложения).
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            self._settings = merged
        except (json.JSONDecodeError, OSError):
            self._settings = dict(DEFAULT_SETTINGS)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self._settings, f, ensure_ascii=False, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def get_all(self) -> dict[str, Any]:
        return dict(self._settings)

    def set(self, key: str, value: Any) -> None:
        self._settings[key] = value
        self.save()

    def public_settings(self) -> dict[str, Any]:
        """Настройки для отправки во фронтенд: ключ API заменён на флаг «задан/не задан».
        Сам секрет наружу не отдаём — незачем держать его в памяти рендерера и в devtools."""
        data = dict(self._settings)
        data["summary_api_key"] = ""
        data["summary_api_key_set"] = bool(str(self._settings.get("summary_api_key", "")).strip())
        return data

    def add_history_entry(self, entry: dict[str, Any]) -> None:
        """Добавляет запись в историю (в начало списка), обрезая до MAX_HISTORY_ENTRIES."""
        history: list[dict[str, Any]] = self._settings.get("history", [])
        history.insert(0, entry)
        self._settings["history"] = history[:MAX_HISTORY_ENTRIES]
        self.save()

    def get_history(self) -> list[dict[str, Any]]:
        return list(self._settings.get("history", []))

    def clear_history(self) -> None:
        self._settings["history"] = []
        self.save()

    def ensure_download_folder(self) -> str:
        """Гарантирует существование папки загрузок и возвращает её путь."""
        folder = self._settings.get("download_folder", DEFAULT_SETTINGS["download_folder"])
        os.makedirs(folder, exist_ok=True)
        return folder
