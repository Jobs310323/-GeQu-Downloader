"""Pydantic-модели API: нормализованные структуры для фронтенда (React)."""

from typing import Literal, Optional

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    url: str


class SummaryRequest(BaseModel):
    url: str
    title: str = ""
    duration: Optional[int] = None


class FolderPickRequest(BaseModel):
    start: str = ""


class RevealRequest(BaseModel):
    path: str = ""


class VideoInfoResponse(BaseModel):
    is_playlist: bool
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
    "UNKNOWN_ERROR",
]
