"""Поиск ffmpeg/ffprobe: сначала бандл рядом с приложением, потом системный PATH.

Собранный EXE не обязан зависеть от того, установлен ли у пользователя ffmpeg —
если бинарники лежат в assets/bin/ (см. build.spec datas), используем их. Из
исходников или если бандла нет — как раньше, ищем в PATH через shutil.which.
"""

import shutil
import sys
from pathlib import Path


def _bundled_bin_dir() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    bin_dir = base / "assets" / "bin"
    return bin_dir if bin_dir.is_dir() else None


def find_ffmpeg() -> str | None:
    bin_dir = _bundled_bin_dir()
    if bin_dir is not None:
        candidate = bin_dir / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffmpeg")


def find_ffprobe() -> str | None:
    bin_dir = _bundled_bin_dir()
    if bin_dir is not None:
        candidate = bin_dir / "ffprobe.exe"
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffprobe")


def ffmpeg_location() -> str | None:
    """Папка с ffmpeg-бинарниками для yt-dlp opts['ffmpeg_location'] — yt-dlp сам
    ищет ffmpeg.exe/ffprobe.exe рядом с указанным путём (файлом или папкой)."""
    ffmpeg = find_ffmpeg()
    return str(Path(ffmpeg).parent) if ffmpeg else None
