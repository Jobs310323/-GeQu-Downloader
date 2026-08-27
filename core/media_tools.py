"""ffmpeg-движок для локальных операций над файлами: ремукс, обрезка, замена
аудиодорожки, конвертация, извлечение аудио, GIF и картинки.

Главный принцип, позаимствованный у Shutter Encoder: **если операцию можно сделать
без перекодирования — она делается без перекодирования**. Смена контейнера
(MKV -> MP4), обрезка по времени и подмена звуковой дорожки не трогают сами
видеоданные: ffmpeg переписывает только оболочку (`-c copy`). Это и мгновенно
(упор в скорость диска, а не процессора), и без единой потери качества.

Перекодирование включается ТОЛЬКО когда:
  * пользователь явно попросил другой кодек/разрешение/битрейт, либо
  * целевой контейнер физически не умеет хранить исходный кодек
    (например VP9 в .avi или H.264 в .webm) — тогда перекодируется РОВНО ТОТ
    поток, который мешает, а остальные всё равно копируются.

Прогресс берётся из `-progress pipe:1` (out_time_us) и делится на длительность из
ffprobe — это работает одинаково для всех операций, в отличие от парсинга stderr.
"""

import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from core.ffmpeg_locator import find_ffmpeg, find_ffprobe

logger = logging.getLogger("neoloader.media")

# На Windows не поднимаем консольное окно на каждый вызов ffmpeg — в windowed-сборке
# это выглядело бы как мигающие чёрные окна на каждую операцию.
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _popen_kwargs() -> dict:
    return {"creationflags": _CREATE_NO_WINDOW} if _CREATE_NO_WINDOW else {}


class FFmpegMissing(RuntimeError):
    """ffmpeg/ffprobe не найден — без них ни одна операция невозможна."""


class MediaError(RuntimeError):
    """Операция не удалась; текст содержит последние строки stderr ffmpeg."""


# --- матрица «контейнер -> какие кодеки он умеет хранить» ---
#
# Нужна ровно для одного вопроса: можно ли уложить исходные потоки в новый контейнер
# БЕЗ перекодирования. Списки намеренно консервативные — лучше лишний раз перекодировать
# один поток, чем отдать файл, который не откроется в плеере.


@dataclass(frozen=True)
class Container:
    ext: str
    label: str
    kind: str  # "video" | "audio" | "image"
    video: frozenset = frozenset()
    audio: frozenset = frozenset()
    subtitles: frozenset = frozenset()
    default_video: str = "h264"
    default_audio: str = "aac"


CONTAINERS: dict = {
    c.ext: c
    for c in [
        Container("mp4", "MP4", "video",
                  frozenset({"h264", "hevc", "av1", "mpeg4", "vp9"}),
                  frozenset({"aac", "mp3", "ac3", "eac3", "alac", "opus", "flac"}),
                  frozenset({"mov_text"}), "h264", "aac"),
        Container("mkv", "Matroska (MKV)", "video",
                  frozenset({"h264", "hevc", "av1", "vp8", "vp9", "mpeg4", "mpeg2video", "theora", "prores", "mjpeg"}),
                  frozenset({"aac", "mp3", "ac3", "eac3", "dts", "opus", "vorbis", "flac", "pcm", "alac", "truehd"}),
                  frozenset({"subrip", "ass", "ssa", "webvtt"}), "h264", "aac"),
        Container("webm", "WebM", "video",
                  frozenset({"vp8", "vp9", "av1"}),
                  frozenset({"opus", "vorbis"}),
                  frozenset({"webvtt"}), "vp9", "opus"),
        Container("mov", "QuickTime (MOV)", "video",
                  frozenset({"h264", "hevc", "prores", "mpeg4"}),
                  frozenset({"aac", "alac", "pcm", "mp3"}),
                  frozenset({"mov_text"}), "h264", "aac"),
        Container("avi", "AVI", "video",
                  frozenset({"h264", "mpeg4", "mjpeg", "mpeg2video"}),
                  frozenset({"mp3", "ac3", "pcm"}),
                  frozenset(), "mpeg4", "mp3"),
        Container("ts", "MPEG-TS", "video",
                  frozenset({"h264", "hevc", "mpeg2video"}),
                  frozenset({"aac", "mp3", "ac3", "eac3"}),
                  frozenset(), "h264", "aac"),
        Container("flv", "FLV", "video",
                  frozenset({"h264", "flv1"}),
                  frozenset({"aac", "mp3"}),
                  frozenset(), "h264", "aac"),
        # --- только аудио ---
        Container("mp3", "MP3", "audio", frozenset(), frozenset({"mp3"}), frozenset(), "", "mp3"),
        Container("m4a", "M4A (AAC/ALAC)", "audio", frozenset(), frozenset({"aac", "alac"}), frozenset(), "", "aac"),
        Container("opus", "Opus", "audio", frozenset(), frozenset({"opus"}), frozenset(), "", "opus"),
        Container("ogg", "OGG", "audio", frozenset(), frozenset({"vorbis", "opus", "flac"}), frozenset(), "", "vorbis"),
        Container("flac", "FLAC", "audio", frozenset(), frozenset({"flac"}), frozenset(), "", "flac"),
        Container("wav", "WAV", "audio", frozenset(), frozenset({"pcm"}), frozenset(), "", "pcm"),
        Container("ac3", "AC-3", "audio", frozenset(), frozenset({"ac3"}), frozenset(), "", "ac3"),
        Container("aac", "AAC (ADTS)", "audio", frozenset(), frozenset({"aac"}), frozenset(), "", "aac"),
        # --- картинки ---
        Container("png", "PNG", "image", frozenset({"png"}), frozenset(), frozenset(), "png", ""),
        Container("jpg", "JPEG", "image", frozenset({"mjpeg"}), frozenset(), frozenset(), "mjpeg", ""),
        Container("webp", "WebP", "image", frozenset({"webp"}), frozenset(), frozenset(), "webp", ""),
        Container("gif", "GIF", "image", frozenset({"gif"}), frozenset(), frozenset(), "gif", ""),
        Container("bmp", "BMP", "image", frozenset({"bmp"}), frozenset(), frozenset(), "bmp", ""),
        Container("tiff", "TIFF", "image", frozenset({"tiff"}), frozenset(), frozenset(), "tiff", ""),
    ]
}

# Кодек -> имена энкодеров ffmpeg по убыванию предпочтения. Первый ДОСТУПНЫЙ в системе
# выигрывает: минимальные сборки ffmpeg часто идут без libx265/libsvtav1, и предлагать
# пользователю кодек, который упадёт на старте, — худший вариант из возможных.
VIDEO_ENCODERS: dict = {
    "h264": ("libx264", "h264_nvenc", "h264_qsv", "libopenh264"),
    "hevc": ("libx265", "hevc_nvenc", "hevc_qsv"),
    "vp9": ("libvpx-vp9",),
    "vp8": ("libvpx",),
    "av1": ("libsvtav1", "libaom-av1", "librav1e"),
    "prores": ("prores_ks", "prores"),
    "mpeg4": ("mpeg4",),
    "mjpeg": ("mjpeg",),
    "png": ("png",),
    "webp": ("libwebp", "libwebp_anim"),
    "gif": ("gif",),
    "bmp": ("bmp",),
    "tiff": ("tiff",),
}

AUDIO_ENCODERS: dict = {
    "aac": ("libfdk_aac", "aac", "aac_mf"),
    "mp3": ("libmp3lame", "mp3_mf"),
    "opus": ("libopus",),
    "vorbis": ("libvorbis", "vorbis"),
    "flac": ("flac",),
    "pcm": ("pcm_s16le",),
    "ac3": ("ac3", "ac3_mf"),
    "eac3": ("eac3",),
    "alac": ("alac",),
}

VIDEO_CODEC_LABELS = {
    "h264": "H.264 / AVC", "hevc": "H.265 / HEVC", "vp9": "VP9", "vp8": "VP8",
    "av1": "AV1", "prores": "Apple ProRes", "mpeg4": "MPEG-4", "mjpeg": "MJPEG",
}
AUDIO_CODEC_LABELS = {
    "aac": "AAC", "mp3": "MP3", "opus": "Opus", "vorbis": "Vorbis", "flac": "FLAC",
    "pcm": "PCM (WAV)", "ac3": "AC-3", "eac3": "E-AC-3", "alac": "ALAC",
}


def canonical_codec(name: Optional[str]) -> str:
    """ffprobe называет один и тот же кодек по-разному (pcm_s16le/pcm_s24le, srt/subrip),
    а матрица контейнеров работает с короткими именами."""
    if not name:
        return ""
    name = name.lower()
    if name.startswith("pcm_"):
        return "pcm"
    return {"h265": "hevc", "avc1": "h264", "srt": "subrip", "vp08": "vp8", "vp09": "vp9"}.get(name, name)


_encoder_cache: Optional[set] = None


def available_encoders() -> set:
    """Энкодеры, которые реально есть в ЭТОЙ сборке ffmpeg (кэшируется на процесс).
    Пустое множество = список получить не удалось; тогда считаем доступным всё
    и позволяем ffmpeg самому сказать «нет», а не блокируем функции заранее."""
    global _encoder_cache
    if _encoder_cache is not None:
        return _encoder_cache
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        _encoder_cache = set()
        return _encoder_cache
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error", "-encoders"],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace",
            **_popen_kwargs(),
        )
        names = set()
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            # Строки таблицы выглядят как " V....D libx264   libx264 H.264 ..."
            if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
                names.add(parts[1])
        _encoder_cache = names
    except Exception:  # noqa: BLE001
        _encoder_cache = set()
    return _encoder_cache


def resolve_encoder(codec: str, is_video: bool) -> Optional[str]:
    """Первый доступный энкодер для кодека, или None если ни одного нет."""
    table = VIDEO_ENCODERS if is_video else AUDIO_ENCODERS
    have = available_encoders()
    for name in table.get(codec, ()):
        if not have or name in have:
            return name
    return None


def supported_video_codecs() -> list:
    return [c for c in VIDEO_CODEC_LABELS if resolve_encoder(c, True)]


def supported_audio_codecs() -> list:
    return [c for c in AUDIO_CODEC_LABELS if resolve_encoder(c, False)]


# --- ffprobe ---


@dataclass
class MediaStream:
    index: int
    kind: str  # video | audio | subtitle
    codec: str
    language: str = ""
    title: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    channels: int = 0
    sample_rate: int = 0
    bitrate: int = 0
    is_default: bool = False

    def to_dict(self) -> dict:
        return {
            "index": self.index, "kind": self.kind, "codec": self.codec,
            "language": self.language, "title": self.title,
            "width": self.width, "height": self.height, "fps": round(self.fps, 3),
            "channels": self.channels, "sample_rate": self.sample_rate,
            "bitrate": self.bitrate, "is_default": self.is_default,
        }


@dataclass
class MediaProbe:
    path: str
    container: str
    duration: float
    size: int
    bitrate: int
    streams: list = field(default_factory=list)

    @property
    def video_streams(self) -> list:
        return [s for s in self.streams if s.kind == "video"]

    @property
    def audio_streams(self) -> list:
        return [s for s in self.streams if s.kind == "audio"]

    def to_dict(self) -> dict:
        return {
            "path": self.path, "container": self.container, "duration": self.duration,
            "size": self.size, "bitrate": self.bitrate,
            "streams": [s.to_dict() for s in self.streams],
            "filename": os.path.basename(self.path),
        }


def _parse_fps(value: Optional[str]) -> float:
    if not value or "/" not in value:
        return 0.0
    num, den = value.split("/", 1)
    try:
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    except ValueError:
        return 0.0


def probe(path: str) -> MediaProbe:
    """Полные метаданные файла. Бросает FFmpegMissing/MediaError."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        raise FFmpegMissing("ffprobe не найден — установите ffmpeg или положите его в assets/bin")
    if not os.path.exists(path):
        raise MediaError(f"Файл не найден: {path}")
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, text=True, timeout=60, encoding="utf-8", errors="replace",
            **_popen_kwargs(),
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError("ffprobe не ответил за 60 секунд") from exc
    if out.returncode != 0:
        raise MediaError(f"ffprobe не смог прочитать файл: {(out.stderr or '').strip()[-400:]}")
    try:
        data = json.loads(out.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError("ffprobe вернул неразборчивый ответ") from exc

    fmt = data.get("format") or {}
    streams = []
    for raw in data.get("streams") or []:
        kind = raw.get("codec_type") or ""
        if kind not in ("video", "audio", "subtitle"):
            continue
        tags = raw.get("tags") or {}
        disposition = raw.get("disposition") or {}
        # Обложка альбома внутри mp3/m4a приезжает как «видеопоток» из одного кадра —
        # приняв её за видео, интерфейс предложил бы «сменить видеокодек» у песни.
        if kind == "video" and disposition.get("attached_pic"):
            continue
        streams.append(
            MediaStream(
                index=int(raw.get("index", 0)),
                kind=kind,
                codec=canonical_codec(raw.get("codec_name")),
                language=(tags.get("language") or "").lower(),
                title=tags.get("title") or "",
                width=int(raw.get("width") or 0),
                height=int(raw.get("height") or 0),
                fps=_parse_fps(raw.get("avg_frame_rate") or raw.get("r_frame_rate")),
                channels=int(raw.get("channels") or 0),
                sample_rate=int(raw.get("sample_rate") or 0),
                bitrate=int(raw.get("bit_rate") or 0),
                is_default=bool(disposition.get("default")),
            )
        )

    return MediaProbe(
        path=path,
        container=(os.path.splitext(path)[1] or "").lstrip(".").lower(),
        duration=float(fmt.get("duration") or 0.0),
        size=int(fmt.get("size") or (os.path.getsize(path) if os.path.exists(path) else 0)),
        bitrate=int(fmt.get("bit_rate") or 0),
        streams=streams,
    )


# --- планирование операции ---


@dataclass
class Plan:
    """Готовая команда ffmpeg + честный ответ, теряется ли при ней качество."""

    args: list
    output: str
    lossless: bool
    notes: list = field(default_factory=list)
    duration: float = 0.0


def _unique_path(path: str) -> str:
    """Никогда не перезаписываем исходник и не затираем чужой файл молча."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    for n in range(1, 1000):
        candidate = f"{base} ({n}){ext}"
        if not os.path.exists(candidate):
            return candidate
    return f"{base} ({os.getpid()}){ext}"


def output_path_for(source: str, ext: str, suffix: str = "", folder: str = "") -> str:
    base = os.path.splitext(os.path.basename(source))[0]
    directory = folder or os.path.dirname(source) or os.getcwd()
    os.makedirs(directory, exist_ok=True)
    return _unique_path(os.path.join(directory, f"{base}{suffix}.{ext.lstrip('.')}"))


def _ordinal(info: MediaProbe, stream: MediaStream) -> int:
    """Номер потока среди потоков своего типа: ffmpeg адресует их как -c:v:0, -c:a:1."""
    same = [s for s in info.streams if s.kind == stream.kind]
    return same.index(stream)


def _video_encode_args(codec: str, quality: Optional[int], bitrate_kbps: Optional[int]) -> list:
    encoder = resolve_encoder(codec, True)
    if encoder is None:
        raise MediaError(f"В этой сборке ffmpeg нет энкодера для {codec}")
    args = ["-c:v", encoder]
    if bitrate_kbps:
        args += ["-b:v", f"{bitrate_kbps}k"]
    elif quality is not None:
        # UI отдаёт «качество» 0-100, а у каждого энкодера своя шкала CRF/CQ,
        # причём перевёрнутая (меньше = лучше). Перевод здесь, чтобы фронтенд
        # не знал про libx264 вообще ничего.
        if encoder in ("libx264", "libx265"):
            args += ["-crf", str(max(0, min(51, round(51 - quality * 0.51))))]
        elif encoder == "libvpx-vp9":
            args += ["-crf", str(max(0, min(63, round(63 - quality * 0.63)))), "-b:v", "0"]
        elif encoder in ("libsvtav1", "libaom-av1", "librav1e"):
            args += ["-crf", str(max(0, min(63, round(63 - quality * 0.63))))]
        elif encoder.endswith("_nvenc") or encoder.endswith("_qsv"):
            args += ["-cq", str(max(1, min(51, round(51 - quality * 0.51))))]
        elif encoder in ("mpeg4", "mjpeg"):
            args += ["-q:v", str(max(2, min(31, round(31 - quality * 0.29))))]
    if encoder == "libx264":
        # yuv420p — единственный пиксельный формат, который открывается вообще везде.
        # Исходник с 10-битным цветом или 4:4:4 иначе даёт файл, который не играет
        # ни в одном системном плеере Windows.
        args += ["-pix_fmt", "yuv420p", "-preset", "medium"]
    elif encoder == "libx265":
        # hvc1 вместо hev1: без этого тега QuickTime и проводник Windows не показывают
        # ни превью, ни само видео.
        args += ["-pix_fmt", "yuv420p", "-preset", "medium", "-tag:v", "hvc1"]
    elif encoder == "prores_ks":
        args += ["-profile:v", "3", "-pix_fmt", "yuv422p10le"]
    return args


def _audio_encode_args(codec: str, bitrate_kbps: Optional[int], stream_spec: str = "a") -> list:
    encoder = resolve_encoder(codec, False)
    if encoder is None:
        raise MediaError(f"В этой сборке ffmpeg нет энкодера для {codec}")
    args = [f"-c:{stream_spec}", encoder]
    # У FLAC/PCM/ALAC битрейта не существует — задавать его бессмысленно, ffmpeg ругается.
    if bitrate_kbps and codec not in ("flac", "pcm", "alac"):
        args += [f"-b:{stream_spec}", f"{bitrate_kbps}k"]
    return args


def _scale_args(height: Optional[int]) -> list:
    if not height:
        return []
    # -2, а не -1: ширина округляется до чётной, иначе h264/hevc отказываются кодировать.
    return ["-vf", f"scale=-2:{height}"]


def _base_args(ffmpeg: str) -> list:
    return [ffmpeg, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1"]


def _require_ffmpeg() -> str:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise FFmpegMissing("ffmpeg не найден — установите его или положите в assets/bin")
    return ffmpeg


def plan_remux(source: str, container: str, folder: str = "", auto_transcode: bool = True) -> Plan:
    """Смена контейнера. Потоки, которые новый контейнер умеет хранить, копируются
    как есть; перекодируется только то, что физически не влезает."""
    ffmpeg = _require_ffmpeg()
    target = CONTAINERS.get(container)
    if target is None:
        raise MediaError(f"Неизвестный контейнер: {container}")
    info = probe(source)

    args = _base_args(ffmpeg) + ["-i", source]
    notes: list = []
    lossless = True

    if target.kind == "image":
        raise MediaError("Смена контейнера на формат изображения невозможна — используйте кадр/GIF")

    if target.kind == "audio":
        audio = info.audio_streams
        if not audio:
            raise MediaError("В файле нет аудиодорожки")
        args += ["-map", f"0:{audio[0].index}", "-vn"]
        if audio[0].codec in target.audio:
            args += ["-c:a", "copy"]
        else:
            lossless = False
            notes.append(
                f"{audio[0].codec} нельзя положить в .{container} — "
                f"дорожка перекодирована в {target.default_audio}"
            )
            args += _audio_encode_args(target.default_audio, 192)
    else:
        args += ["-map", "0:v?", "-map", "0:a?"]
        if target.subtitles:
            args += ["-map", "0:s?"]

        for stream in info.streams:
            allowed = {"video": target.video, "audio": target.audio, "subtitle": target.subtitles}[stream.kind]
            spec_letter = {"video": "v", "audio": "a", "subtitle": "s"}[stream.kind]
            ordinal = _ordinal(info, stream)
            if stream.codec in allowed:
                args += [f"-c:{spec_letter}:{ordinal}", "copy"]
                continue
            if not auto_transcode:
                raise MediaError(f"{stream.codec} нельзя положить в .{container} без перекодирования")
            if stream.kind == "subtitle":
                if target.subtitles:
                    fallback = "mov_text" if "mov_text" in target.subtitles else sorted(target.subtitles)[0]
                    args += [f"-c:s:{ordinal}", fallback]
                    notes.append(f"субтитры пересобраны в {fallback}")
                else:
                    notes.append(f".{container} не хранит субтитры — дорожка субтитров пропущена")
                continue
            lossless = False
            if stream.kind == "video":
                notes.append(
                    f"{stream.codec} не помещается в .{container} — "
                    f"видео перекодировано в {target.default_video}"
                )
                args += _video_encode_args(target.default_video, 75, None)
            else:
                notes.append(
                    f"{stream.codec} не помещается в .{container} — "
                    f"звук перекодирован в {target.default_audio}"
                )
                args += _audio_encode_args(target.default_audio, 192, f"a:{ordinal}")

        if container in ("mp4", "mov"):
            # Индекс в начало файла: иначе плеер не начинает воспроизведение, пока не
            # прочитает файл целиком (заметно при просмотре по сети).
            args += ["-movflags", "+faststart"]

    output = output_path_for(source, container, folder=folder)
    args.append(output)
    return Plan(args, output, lossless, notes, info.duration)


def plan_trim(
    source: str,
    start: float,
    end: Optional[float],
    lossless: bool = True,
    container: str = "",
    folder: str = "",
) -> Plan:
    """Обрезка по времени.

    lossless=True — `-c copy`: мгновенно и без потери качества, но начало прыгает
    на ближайший ключевой кадр (ffmpeg физически не может начать декодирование
    с середины GOP, не перекодировав его). Расхождение обычно 0-10 секунд.
    lossless=False — точная секунда, ценой перекодирования видео.
    """
    ffmpeg = _require_ffmpeg()
    info = probe(source)
    start = max(0.0, float(start or 0.0))
    total = info.duration or 0.0
    stop = float(end) if end else total
    if total and stop > total:
        stop = total
    duration = max(0.0, stop - start)
    if duration <= 0:
        raise MediaError("Конец фрагмента должен быть позже начала")

    ext = container or info.container or "mp4"
    if ext not in CONTAINERS:
        ext = "mp4"
    args = _base_args(ffmpeg)
    notes: list = []

    if lossless:
        # -ss ДО -i = быстрый seek по индексу. Для копирования это единственный разумный
        # вариант: иначе ffmpeg декодирует весь хвост файла до точки входа.
        args += ["-ss", f"{start:.3f}", "-i", source, "-t", f"{duration:.3f}",
                 "-map", "0", "-c", "copy", "-avoid_negative_ts", "make_zero"]
        notes.append("Без перекодирования: начало сдвинется к ближайшему ключевому кадру")
    else:
        # -ss ПОСЛЕ -i = посемпльно точный отсчёт; медленнее, но кадр в кадр.
        target = CONTAINERS.get(ext, CONTAINERS["mp4"])
        args += ["-i", source, "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                 "-map", "0:v?", "-map", "0:a?"]
        args += _video_encode_args(target.default_video, 78, None)
        args += _audio_encode_args(target.default_audio, 192)
        notes.append("Точная обрезка: видео перекодировано")
    if ext in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]

    output = output_path_for(source, ext, suffix="_cut", folder=folder)
    args.append(output)
    return Plan(args, output, lossless, notes, duration)


def plan_replace_audio(
    source: str,
    audio_source: str,
    folder: str = "",
    container: str = "",
    keep_original_audio: bool = False,
    language: str = "",
) -> Plan:
    """Подмена звуковой дорожки на дорожку из другого файла. Видео не трогается вообще —
    именно так к скачанному ролику подставляют отдельно скачанный дубляж."""
    ffmpeg = _require_ffmpeg()
    video_info = probe(source)
    audio_info = probe(audio_source)
    if not video_info.video_streams:
        raise MediaError("В первом файле нет видеопотока")
    if not audio_info.audio_streams:
        raise MediaError("Во втором файле нет аудиодорожки")

    ext = container or video_info.container or "mp4"
    if ext not in CONTAINERS or CONTAINERS[ext].kind != "video":
        ext = "mp4"
    target = CONTAINERS[ext]
    new_audio = audio_info.audio_streams[0]

    args = _base_args(ffmpeg) + ["-i", source, "-i", audio_source, "-map", "0:v:0"]
    if keep_original_audio and video_info.audio_streams:
        args += ["-map", "0:a"]
    args += ["-map", "1:a:0"]
    if target.subtitles and any(s.kind == "subtitle" for s in video_info.streams):
        args += ["-map", "0:s?", "-c:s", "copy"]
    args += ["-c:v", "copy"]

    notes: list = []
    lossless = True
    if new_audio.codec in target.audio:
        args += ["-c:a", "copy"]
        notes.append("Видео и звук скопированы без перекодирования")
    else:
        lossless = False
        notes.append(
            f"{new_audio.codec} не помещается в .{ext} — новая дорожка перекодирована "
            f"в {target.default_audio} (видео всё равно не тронуто)"
        )
        args += _audio_encode_args(target.default_audio, 192)

    if language:
        # Метка языка на НОВОЙ дорожке — она идёт последней среди -map'ов аудио.
        idx = len(video_info.audio_streams) if keep_original_audio else 0
        args += [f"-metadata:s:a:{idx}", f"language={language}", f"-disposition:a:{idx}", "default"]
    # -shortest: если дорожка длиннее видео (а у дубляжа так бывает), файл не растягивается
    # чёрным кадром на разницу.
    args += ["-shortest"]
    if ext in ("mp4", "mov"):
        args += ["-movflags", "+faststart"]

    output = output_path_for(source, ext, suffix="_newaudio", folder=folder)
    args.append(output)
    return Plan(args, output, lossless, notes, video_info.duration)


def plan_extract_audio(
    source: str,
    container: str = "mp3",
    bitrate_kbps: Optional[int] = 192,
    stream_index: Optional[int] = None,
    folder: str = "",
) -> Plan:
    """Извлечение звуковой дорожки. Если её кодек уже подходит целевому контейнеру,
    дорожка копируется — «извлечь как есть» реально означает как есть, байт в байт."""
    ffmpeg = _require_ffmpeg()
    info = probe(source)
    audio = info.audio_streams
    if not audio:
        raise MediaError("В файле нет аудиодорожки")
    chosen = next((s for s in audio if s.index == stream_index), audio[0])

    notes: list = []
    if container == "original":
        container = {
            "aac": "m4a", "alac": "m4a", "opus": "opus", "vorbis": "ogg",
            "flac": "flac", "mp3": "mp3", "pcm": "wav", "ac3": "ac3", "eac3": "ac3",
        }.get(chosen.codec, "m4a")
    target = CONTAINERS.get(container)
    if target is None or target.kind != "audio":
        raise MediaError(f"{container} — не аудиоконтейнер")

    args = _base_args(ffmpeg) + ["-i", source, "-map", f"0:{chosen.index}", "-vn"]
    lossless = chosen.codec in target.audio
    if lossless:
        args += ["-c:a", "copy"]
        notes.append("Дорожка скопирована без перекодирования")
    else:
        args += _audio_encode_args(target.default_audio, bitrate_kbps)
    if container == "m4a":
        args += ["-movflags", "+faststart"]

    output = output_path_for(source, container, folder=folder)
    args.append(output)
    return Plan(args, output, lossless, notes, info.duration)


def plan_convert(
    source: str,
    container: str = "mp4",
    video_codec: str = "copy",
    audio_codec: str = "copy",
    quality: Optional[int] = 75,
    video_bitrate_kbps: Optional[int] = None,
    audio_bitrate_kbps: Optional[int] = 192,
    height: Optional[int] = None,
    fps: Optional[float] = None,
    folder: str = "",
) -> Plan:
    """Полная конвертация с явным выбором кодеков. codec="copy" означает «не трогать»,
    и если контейнер это позволяет — операция останется без потерь."""
    ffmpeg = _require_ffmpeg()
    target = CONTAINERS.get(container)
    if target is None:
        raise MediaError(f"Неизвестный контейнер: {container}")
    if target.kind == "image":
        return plan_thumbnail(source, container=container, at=0.0, folder=folder)

    info = probe(source)
    args = _base_args(ffmpeg) + ["-i", source]
    notes: list = []
    lossless = True

    if target.kind == "audio":
        if not info.audio_streams:
            raise MediaError("В файле нет аудиодорожки")
        src_a = info.audio_streams[0].codec
        args += ["-map", "0:a:0", "-vn"]
        if audio_codec == "copy" and src_a in target.audio:
            args += ["-c:a", "copy"]
            notes.append("Дорожка скопирована без перекодирования")
        else:
            chosen_a = target.default_audio if audio_codec == "copy" else audio_codec
            if chosen_a not in target.audio:
                notes.append(f".{container} не хранит {chosen_a} — взят {target.default_audio}")
                chosen_a = target.default_audio
            lossless = chosen_a in ("flac", "pcm", "alac")
            args += _audio_encode_args(chosen_a, audio_bitrate_kbps)
    else:
        if not info.video_streams:
            raise MediaError("В файле нет видеопотока — выберите аудиоформат")
        args += ["-map", "0:v:0", "-map", "0:a?"]
        src_v = info.video_streams[0].codec
        src_a = info.audio_streams[0].codec if info.audio_streams else ""

        if video_codec == "copy" and src_v in target.video and not height and not fps:
            args += ["-c:v", "copy"]
        else:
            chosen_v = target.default_video if video_codec == "copy" else video_codec
            if chosen_v not in target.video:
                notes.append(f".{container} не хранит {chosen_v} — взят {target.default_video}")
                chosen_v = target.default_video
            lossless = False
            args += _video_encode_args(chosen_v, quality, video_bitrate_kbps)
            args += _scale_args(height)
            if fps:
                args += ["-r", str(fps)]

        if not info.audio_streams:
            pass
        elif audio_codec == "copy" and src_a in target.audio:
            args += ["-c:a", "copy"]
        else:
            chosen_a = target.default_audio if audio_codec == "copy" else audio_codec
            if chosen_a not in target.audio:
                notes.append(f".{container} не хранит {chosen_a} — взят {target.default_audio}")
                chosen_a = target.default_audio
            if chosen_a not in ("flac", "pcm", "alac"):
                lossless = False
            args += _audio_encode_args(chosen_a, audio_bitrate_kbps)
        if container in ("mp4", "mov"):
            args += ["-movflags", "+faststart"]

    output = output_path_for(source, container, suffix="_conv", folder=folder)
    args.append(output)
    return Plan(args, output, lossless, notes, info.duration)


def plan_gif(
    source: str,
    start: float = 0.0,
    duration: float = 5.0,
    fps: int = 12,
    width: int = 480,
    folder: str = "",
) -> Plan:
    """Видео -> GIF. Палитра считается по самому фрагменту (palettegen/paletteuse):
    GIF умеет только 256 цветов, и без своей палитры результат выглядит грязно."""
    ffmpeg = _require_ffmpeg()
    probe(source)  # проверка читаемости; длительность здесь задаётся явно
    filters = (
        f"fps={int(fps)},scale={int(width)}:-1:flags=lanczos,split[a][b];"
        f"[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=3"
    )
    args = _base_args(ffmpeg) + [
        "-ss", f"{float(start):.3f}", "-t", f"{float(duration):.3f}", "-i", source,
        "-filter_complex", filters, "-loop", "0",
    ]
    output = output_path_for(source, "gif", folder=folder)
    args.append(output)
    return Plan(args, output, False, ["GIF всегда перекодируется — это его формат"], float(duration))


def plan_thumbnail(source: str, container: str = "png", at: float = 0.0, folder: str = "") -> Plan:
    """Один кадр в картинку (или конвертация картинки в другой формат)."""
    ffmpeg = _require_ffmpeg()
    target = CONTAINERS.get(container)
    if target is None or target.kind != "image":
        raise MediaError(f"{container} — не формат изображения")
    args = _base_args(ffmpeg)
    if at:
        args += ["-ss", f"{float(at):.3f}"]
    args += ["-i", source, "-frames:v", "1", "-map", "0:v:0"]
    encoder = resolve_encoder(target.default_video, True)
    if encoder:
        args += ["-c:v", encoder]
    if container == "jpg":
        args += ["-q:v", "2"]
    output = output_path_for(source, container, suffix="_frame" if at else "", folder=folder)
    args.append(output)
    return Plan(args, output, False, [], 0.0)


# --- запуск ---

_TIME_RE = re.compile(r"out_time_us=(\d+)")


def run_plan(
    plan: Plan,
    on_progress: Optional[Callable] = None,
    cancel_event: Optional[threading.Event] = None,
) -> str:
    """Выполняет план, отдавая проценты в on_progress. Возвращает путь к результату.

    При отмене (и при любой ошибке) недописанный выходной файл УДАЛЯЕТСЯ: иначе на
    диске остаётся обрезок, который по имени и размеру выглядит как готовый результат.
    """
    logger.info("ffmpeg %s -> %s", os.path.basename(plan.args[plan.args.index("-i") + 1]), plan.output)
    proc = subprocess.Popen(
        plan.args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_popen_kwargs(),
    )
    stderr_tail: list = []

    def drain_stderr() -> None:
        # stderr читаем в отдельном потоке: у ffmpeg он может заполнить буфер трубы и
        # намертво заблокировать процесс, пока мы читаем только stdout.
        if proc.stderr is None:
            return
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())
            del stderr_tail[:-40]

    err_thread = threading.Thread(target=drain_stderr, daemon=True)
    err_thread.start()

    cancelled = False
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    break
                match = _TIME_RE.search(line)
                if match and plan.duration > 0 and on_progress is not None:
                    seconds = int(match.group(1)) / 1_000_000
                    on_progress(max(0.0, min(100.0, seconds / plan.duration * 100)))
    finally:
        if cancelled:
            _terminate(proc)
        else:
            proc.wait()
        err_thread.join(timeout=2)

    if cancelled:
        _cleanup(plan.output)
        raise MediaError("Операция отменена")
    if proc.returncode != 0:
        _cleanup(plan.output)
        raise MediaError("\n".join(stderr_tail[-8:]) or f"ffmpeg завершился с кодом {proc.returncode}")
    if not os.path.exists(plan.output) or os.path.getsize(plan.output) == 0:
        _cleanup(plan.output)
        raise MediaError("ffmpeg отработал, но файл не создан")
    if on_progress is not None:
        on_progress(100.0)
    return plan.output


def _terminate(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=5)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def _cleanup(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def capabilities() -> dict:
    """Всё, что фронтенду нужно знать о возможностях ЭТОЙ машины — один источник правды.
    Иначе списки кодеков дублируются в TypeScript и расходятся с реальной сборкой ffmpeg."""
    ffmpeg = find_ffmpeg()
    return {
        "ffmpeg": bool(ffmpeg),
        "ffmpeg_path": ffmpeg or "",
        "ffprobe": bool(find_ffprobe()),
        "containers": [
            {
                "ext": c.ext, "label": c.label, "kind": c.kind,
                "video": sorted(c.video), "audio": sorted(c.audio),
                "default_video": c.default_video, "default_audio": c.default_audio,
            }
            for c in CONTAINERS.values()
        ],
        "video_codecs": [
            {"id": c, "label": VIDEO_CODEC_LABELS[c], "encoder": resolve_encoder(c, True)}
            for c in supported_video_codecs()
        ],
        "audio_codecs": [
            {"id": c, "label": AUDIO_CODEC_LABELS[c], "encoder": resolve_encoder(c, False)}
            for c in supported_audio_codecs()
        ],
    }


def free_space_ok(folder: str, needed: int) -> bool:
    try:
        return shutil.disk_usage(folder or ".").free >= needed
    except OSError:
        return True
