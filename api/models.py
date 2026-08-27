"""Pydantic-модели API: нормализованные структуры для фронтенда (React)."""

from typing import Literal, Optional

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    url: str


class SummaryRequest(BaseModel):
    url: str
    title: str = ""
    duration: Optional[int] = None


class PlaylistRequest(BaseModel):
    url: str
    limit: int = 500


class FolderPickRequest(BaseModel):
    start: str = ""


class FilePickRequest(BaseModel):
    start: str = ""
    multiple: bool = True
    audio_only: bool = False
    title: str = ""


class RevealRequest(BaseModel):
    path: str = ""


class ProbeRequest(BaseModel):
    path: str


class MediaJobRequest(BaseModel):
    """Одна ffmpeg-операция. Набор полей общий на все виды операций — что именно
    из них читается, решает core/media_jobs.py по `kind`."""

    kind: Literal["remux", "trim", "replace_audio", "extract_audio", "convert", "gif", "thumbnail"]
    source: str
    container: str = ""
    output_folder: str = ""
    # trim
    start: Optional[float] = None
    end: Optional[float] = None
    lossless: bool = True
    # replace_audio
    audio_source: str = ""
    keep_original_audio: bool = False
    language: str = ""
    # extract_audio
    bitrate: Optional[int] = None
    stream_index: Optional[int] = None
    # convert
    video_codec: str = "copy"
    audio_codec: str = "copy"
    quality: Optional[int] = None
    video_bitrate: Optional[int] = None
    audio_bitrate: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    # gif / thumbnail
    duration: Optional[float] = None
    width: Optional[int] = None
    at: Optional[float] = None


class QueueMoveRequest(BaseModel):
    delta: int = -1


class VideoInfoResponse(BaseModel):
    is_playlist: bool
    link_type: str = "video"
    title: str
    uploader: str = ""
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    entries_count: int = 1
    webpage_url: str
    has_ru_dub: bool = False
    ru_is_original: bool = False
    audio_languages: list[str] = []
    has_transcript: bool = False


class QueueItemRequest(BaseModel):
    url: str
    title: str = ""
    quality: str = "1080p"
    audio_only: bool = False
    audio_format: str = "mp3"
    audio_bitrate: str = "192"
    subtitles: bool = False
    subtitle_langs: list[str] = ["ru", "en"]
    neuro_dub_ru: bool = False
    video_codec: str = "any"
    audio_codec: str = "any"
    output_container: str = "mp4"
    output_folder: str = ""
    is_playlist: bool = False
    create_playlist_folder: bool = True
    remove_after_download: bool = False


class BatchQueueRequest(BaseModel):
    """Пакетная постановка: один и тот же набор параметров на список ссылок.

    Отдельный эндпоинт, а не N вызовов /api/queue: N HTTP-запросов подряд из React
    на 200 роликов — это 200 круговых задержек и 200 срабатываний ре-рендера очереди.
    """

    items: list[QueueItemRequest] = []


class QueueItemResponse(BaseModel):
    id: str
    url: str
    title: str
    status: str


class SettingsUpdateRequest(BaseModel):
    theme: Optional[str] = None
    language: Optional[str] = None
    download_folder: Optional[str] = None
    default_quality: Optional[str] = None
    audio_only: Optional[bool] = None
    audio_format: Optional[str] = None
    audio_bitrate: Optional[str] = None
    create_playlist_folder: Optional[bool] = None
    remove_after_download: Optional[bool] = None
    concurrent_downloads: Optional[int] = None
    proxy: Optional[str] = None
    cookies_from_browser: Optional[str] = None
    filename_template: Optional[str] = None
    output_container: Optional[str] = None
    default_video_codec: Optional[str] = None
    default_audio_codec: Optional[str] = None
    auto_update_ytdlp: Optional[bool] = None
    # Поля саммери. Раньше любой ключ, отсутствующий в этой модели, Pydantic просто
    # выбрасывал — настройка "сохранялась" в UI и бесследно исчезала на бэкенде.
    summary_api_key: Optional[str] = None
    summary_model: Optional[str] = None


# Коды ошибок, понятные фронтенду (см. core/download_manager.py::_classify_error)
ErrorCode = Literal[
    "FORMAT_UNAVAILABLE",
    "NETWORK_ERROR",
    "VIDEO_UNAVAILABLE",
    "AGE_RESTRICTED",
    "GEO_RESTRICTED",
    "DISK_FULL",
    "INVALID_URL",
    "NO_TRANSCRIPT",
    "SUMMARY_FAILED",
    "FFMPEG_MISSING",
    "MEDIA_FAILED",
    "UNKNOWN_ERROR",
]
