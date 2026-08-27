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
# Каналы: /@handle, /channel/UC..., /c/Name, /user/Name — с необязательным
# хвостом /videos, /streams, /shorts, /playlists.
CHANNEL_RE = re.compile(r"youtube\.com/(@[\w.-]+|channel/[\w-]+|c/[\w.-]+|user/[\w.-]+)")


class LinkType:
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"
    SHORT = "short"
    INVALID = "invalid"


# Типы ссылок, которые разворачиваются в список видео (пакетная загрузка).
BATCH_LINK_TYPES = (LinkType.PLAYLIST, LinkType.CHANNEL)


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
    # Ссылку на канал раньше не распознавал никто: она не содержит ни v=, ни list=,
    # и попадала в INVALID — то есть «скачать канал» было невозможно в принципе,
    # хотя yt-dlp умеет это с самого начала.
    if CHANNEL_RE.search(url):
        return LinkType.CHANNEL
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
                # Без верхней границы разбор канала на 3000 роликов постранично тянет
                # ВЕСЬ список только ради счётчика в превью — минуты ожидания на экране
                # «Анализ...». Для одиночного видео опция не значит ничего.
                "playlistend": MAX_PLAYLIST_ENTRIES,
            }
        )
        with YoutubeDL(opts) as ydl:
            raw = ydl.extract_info(channel_videos_url(url), download=False)

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
                "link_type": detect_link_type(url),
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
            "link_type": detect_link_type(url),
            "has_ru_dub": has_ru_dub,
            "ru_is_original": ru_is_original,
            "audio_languages": audio_languages,
            # Саммери строится по субтитрам — без них кнопку показывать бессмысленно.
            "has_transcript": bool(subtitle_langs),
        }


# Верхняя граница на разбор плейлиста. Канал с тысячами роликов иначе кладёт и разбор,
# и интерфейс: extract_flat всё равно тянет по странице за раз, а список из 5000 строк
# в React перестаёт скроллиться. Больше этого числа за раз всё равно никто не выбирает.
MAX_PLAYLIST_ENTRIES = 500

# Вкладки канала, на которых лежат сами видео. Ссылка на голый канал (/@handle) отдаёт
# не список роликов, а список ВКЛАДОК (Видео/Shorts/Трансляции/Плейлисты) — и разбор
# возвращал бы четыре псевдо-«видео» с названиями вкладок вместо роликов.
CHANNEL_TABS = ("/videos", "/shorts", "/streams", "/playlists", "/featured", "/community")


def channel_videos_url(url: str) -> str:
    """Для ссылки на канал без вкладки дописывает /videos; остальные ссылки не трогает."""
    if detect_link_type(url) != LinkType.CHANNEL:
        return url
    trimmed = url.split("?")[0].rstrip("/")
    if any(trimmed.endswith(tab) for tab in CHANNEL_TABS):
        return trimmed
    return f"{trimmed}/videos"


def fetch_playlist_entries(url: str, settings=None, limit: int = MAX_PLAYLIST_ENTRIES) -> dict:
    """Список видео плейлиста/канала БЕЗ разбора каждого ролика.

    extract_flat="in_playlist" делает один запрос на страницу списка и не ходит в
    каждое видео отдельно — тысяча роликов разбирается за секунды вместо часов.
    Обратная сторона: у записей нет форматов и точной длительности не всегда, но для
    выбора «что качать» этого достаточно, а конкретные форматы всё равно резолвятся
    уже в момент загрузки (см. core/resolver.py).
    """
    opts = base_ydl_opts(settings)
    opts.update(
        {
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "playlistend": limit,
            # Приватные/удалённые ролики внутри плейлиста не должны ронять весь разбор.
            "ignoreerrors": True,
        }
    )
    with YoutubeDL(opts) as ydl:
        raw = ydl.extract_info(channel_videos_url(url), download=False)

    # ignoreerrors=True нужен, чтобы одно приватное видео внутри списка не роняло разбор
    # всего плейлиста. Побочный эффект: при недоступном САМОМ списке yt-dlp не бросает
    # исключение, а возвращает None — и всё, что дальше, падало с невнятным
    # "'NoneType' object has no attribute 'get'" вместо понятного сообщения.
    if not raw:
        raise ValueError("Плейлист или канал недоступен: ссылка не открывается или список пуст")

    raw_entries = raw.get("entries") or []
    entries = []
    for index, entry in enumerate(raw_entries, start=1):
        if not entry:
            continue  # yt-dlp кладёт None на месте недоступного видео при ignoreerrors
        video_id = entry.get("id") or ""
        entries.append(
            {
                "index": index,
                "id": video_id,
                "title": entry.get("title") or f"Видео {index}",
                "duration": entry.get("duration"),
                "uploader": entry.get("uploader") or entry.get("channel") or "",
                "url": entry.get("url") or entry.get("webpage_url")
                or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""),
                "thumbnail": (entry.get("thumbnails") or [{}])[-1].get("url")
                if entry.get("thumbnails")
                else None,
            }
        )

    return {
        "title": raw.get("title") or "Плейлист",
        "uploader": raw.get("uploader") or raw.get("channel") or "",
        "webpage_url": raw.get("webpage_url") or url,
        "entries": entries,
        "entries_count": len(entries),
        "truncated": len(raw_entries) >= limit,
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
