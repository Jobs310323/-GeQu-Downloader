"""Извлечение метаданных видео/плейлиста без скачивания самого файла."""

import re

from PyQt6.QtCore import QThread, pyqtSignal
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from core.ffmpeg_locator import ffmpeg_location
from core.js_runtime import available_js_runtimes
from core.resolver import is_original_track, normalize_lang

# Регэкспы для быстрого определения типа ссылки до похода в yt-dlp.
PLAYLIST_RE = re.compile(r"[?&]list=([\w-]+)")
VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/live/|youtube\.com/embed/)([\w-]{11})"
)
TIMESTAMP_RE = re.compile(r"[?&]t=(\d+)")


class LinkType:
    VIDEO = "video"
    PLAYLIST = "playlist"
    SHORT = "short"
    INVALID = "invalid"


def detect_link_type(url: str) -> str:
    """Определяет тип ссылки по URL, не обращаясь в сеть."""
    if not url or "youtu" not in url:
        return LinkType.INVALID
    if "/shorts/" in url:
        return LinkType.SHORT
    if PLAYLIST_RE.search(url) and "watch" not in url:
        return LinkType.PLAYLIST
    if VIDEO_ID_RE.search(url) or PLAYLIST_RE.search(url):
        return LinkType.VIDEO
    return LinkType.INVALID


def base_ydl_opts(settings=None) -> dict:
    """Опции, общие для анализа и для скачивания.

    Раньше анализ (VideoInfo.fetch) ходил в YouTube БЕЗ прокси и БЕЗ кук из браузера,
    хотя скачивание их использовало. Из-за этого анализ и загрузка видели разные наборы
    форматов: превью писало «есть русская дорожка», а загрузчик её не находил — или
    наоборот, анализ падал с «видео недоступно» там, где загрузка сработала бы.
    """
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 20,
        "js_runtimes": available_js_runtimes(),
    }
    location = ffmpeg_location()
    if location:
        opts["ffmpeg_location"] = location
    if settings is not None:
        proxy = settings.get("proxy", "")
        if proxy:
            opts["proxy"] = proxy
        cookies_browser = settings.get("cookies_from_browser", "none")
        if cookies_browser and cookies_browser != "none":
            opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


class VideoInfo:
    """Обёртка над yt_dlp.YoutubeDL для извлечения метаданных без скачивания."""

    @staticmethod
    def fetch(url: str, noplaylist: bool = True, settings=None) -> dict:
        """Возвращает словарь с метаданными видео или плейлиста.

        noplaylist=True (по умолчанию) — если в ссылке есть list= (например YouTube
        подставляет его в URL любого видео, открытого из "радио"/микса/очереди), yt-dlp
        без этого флага уходит извлекать ВЕСЬ плейлист вместо одного видео. Для авто-сгенерированных
        "RD..." миксов это может занимать очень долго или зависать — раньше это выглядело
        как вечный "Analyzing...". Вызывающий код передаёт noplaylist=False только для
        ссылок, которые сами по себе являются плейлистом (см. detect_link_type).

        Бросает исключения yt_dlp (DownloadError и т.п.) — их разбирает вызывающий код.
        """
        opts = base_ydl_opts(settings)
        opts.update(
            {
                "skip_download": True,
                "extract_flat": "in_playlist",  # для плейлиста не тянем инфо по каждому видео
                "noplaylist": noplaylist,
            }
        )
        with YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(url, download=False)

        is_playlist = raw.get("_type") == "playlist"
        if is_playlist:
            entries = raw.get("entries") or []
            return {
                "is_playlist": True,
                "title": raw.get("title") or "Плейлист",
                "uploader": raw.get("uploader") or "",
                "thumbnail": raw.get("thumbnails", [{}])[-1].get("url") if raw.get("thumbnails") else None,
                "entries_count": len(entries),
                "duration": None,
                "webpage_url": raw.get("webpage_url") or url,
                "has_ru_dub": False,
                "audio_languages": [],
                "has_transcript": False,
            }

        formats = raw.get("formats") or []
        audio_formats = [f for f in formats if f.get("acodec") not in (None, "none")]
        # normalize_lang, а не строгое ==: YouTube отдаёт "ru" для дубляжа и "ru-RU"
        # для русского оригинала — строгое сравнение теряло второй случай.
        audio_languages = sorted({normalize_lang(f.get("language")) for f in audio_formats} - {""})
        ru_tracks = [f for f in audio_formats if normalize_lang(f.get("language")) == "ru"]
        has_ru_dub = bool(ru_tracks)
        ru_is_original = bool(ru_tracks) and all(is_original_track(f) for f in ru_tracks)

        subtitle_langs = set((raw.get("subtitles") or {}).keys()) | set(
            (raw.get("automatic_captions") or {}).keys()
        )

        return {
            "is_playlist": False,
            "title": raw.get("title") or "Без названия",
            "uploader": raw.get("uploader") or raw.get("channel") or "",
            "thumbnail": raw.get("thumbnail"),
            "duration": raw.get("duration"),
            "entries_count": 1,
            "webpage_url": raw.get("webpage_url") or url,
            "has_ru_dub": has_ru_dub,
            "ru_is_original": ru_is_original,
            "audio_languages": audio_languages,
            # Саммери строится по субтитрам — без них кнопку показывать бессмысленно.
            "has_transcript": bool(subtitle_langs),
        }


class VideoInfoWorker(QThread):
    """Выполняет VideoInfo.fetch в отдельном потоке, чтобы не блокировать UI."""

    finished_ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:
        try:
            info = VideoInfo.fetch(self._url)
            self.finished_ok.emit(info)
        except DownloadError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 — сетевые/парсинг ошибки любых типов должны дойти до UI
            self.failed.emit(str(exc))
