"""Snapshot-based резолвер форматов.

Идея: yt-dlp extract_info() дёргает YouTube, а YouTube отдаёт НЕСТАБИЛЬНЫЕ списки форматов
между отдельными запросами (антибот-защита режет ответ по-разному раз от раза). Если резолвить
формат заново на каждой fallback-ступени — можно по очереди не попасть во все попытки, хотя
реальный набор потоков не менялся.

Поэтому: извлекаем видео максимум 1-2 раза (см. extract_snapshot/needs_retry_for_ru), фиксируем
результат в неизменяемый VideoSnapshot, и весь резолвинг (какой format_id брать) работает только
с этим снапшотом — без единого повторного похода в сеть. Итоговый DownloadPlan содержит
КОНКРЕТНЫЕ format_id, провалидированные против снапшота, так что на самом скачивании
"Requested format is not available" в принципе невозможен — yt-dlp получает буквальные ID,
а не выражение-селектор, которое он бы пересчитывал заново.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from yt_dlp import YoutubeDL


class FormatSnapshotMismatch(Exception):
    """format_id из DownloadPlan не найден в том снапшоте, на котором план был построен."""


def normalize_lang(value: Optional[str]) -> str:
    """YouTube отдаёт языки аудиодорожек то как "ru", то как "ru-RU", то как "en-US"
    (у оригинальной дорожки регион почти всегда есть). Сравнение строгим == пропускало
    ровно те случаи, ради которых функция и нужна: видео с оригиналом "ru-RU" считалось
    "русской дорожки нет", а дальше молча качалась дорожка по умолчанию."""
    if not value:
        return ""
    return str(value).strip().lower().replace("_", "-").split("-")[0]


def lang_matches(value: Optional[str], wanted: Optional[str]) -> bool:
    if not wanted:
        return True
    return normalize_lang(value) == normalize_lang(wanted)


def is_original_track(fmt: dict) -> bool:
    """Оригинальная (не дублированная) дорожка помечена yt-dlp в format_note
    как "... original (default)". Нужно, чтобы при выборе русского дубляжа не взять
    случайно русский ОРИГИНАЛ вместо дубляжа — и наоборот, чтобы понимать,
    что найденная ru-дорожка это и есть оригинал, а не нейродубляж."""
    note = (fmt.get("format_note") or "").lower()
    return "original" in note


@dataclass(frozen=True)
class VideoSnapshot:
    """Неизменяемый срез состояния видео на момент одного extract_info()."""

    video_id: str
    title: str
    duration: Optional[int]
    thumbnail: Optional[str]
    is_playlist: bool
    formats: tuple = field(default_factory=tuple)  # tuple[dict] — сырые format-словари yt-dlp
    subtitles: tuple = field(default_factory=tuple)  # доступные языки субтитров
    extractor: str = "youtube"
    extraction_strategy: str = "default"
    extracted_at: float = field(default_factory=time.time)
    raw_info: dict = field(default_factory=dict)  # полный info_dict — нужен yt-dlp для скачивания

    def format_ids(self) -> set:
        return {f.get("format_id") for f in self.formats}

    def audio_languages(self) -> set:
        """Нормализованные («ru», «en») языки всех аудиодорожек снапшота."""
        return {
            normalize_lang(f.get("language"))
            for f in self.formats
            if f.get("acodec") not in (None, "none") and f.get("language")
        } - {""}

    def has_language(self, wanted: str) -> bool:
        return normalize_lang(wanted) in self.audio_languages()

    def video_heights(self) -> list:
        """Доступные высоты video-only потоков, по убыванию — для пошагового понижения качества."""
        heights = {
            f.get("height")
            for f in self.formats
            if f.get("vcodec") not in (None, "none")
            and f.get("acodec") in (None, "none")
            and f.get("height")
        }
        return sorted(heights, reverse=True)


@dataclass(frozen=True)
class DownloadPlan:
    """Конкретный, уже провалидированный план скачивания — без места для повторного резолвинга."""

    video_format_id: Optional[str]
    audio_format_id: Optional[str]
    requested_quality: str
    requested_language: Optional[str]
    container: str
    needs_merge: bool
    needs_remux: bool
    needs_transcode: bool
    extraction_strategy: str
    label: str  # человекочитаемое описание ступени — для логов

    def format_selector(self) -> str:
        """Строка для yt-dlp: буквальные format_id, без переоценки селектора движком."""
        if self.video_format_id and self.audio_format_id:
            return f"{self.video_format_id}+{self.audio_format_id}"
        return self.video_format_id or self.audio_format_id or "best"


def extract_snapshot(ydl: YoutubeDL, url: str, strategy: str = "default") -> VideoSnapshot:
    """Ровно ОДИН extract_info(). Вызывающий код отвечает за то, чтобы не звать это чаще,
    чем разрешено политикой ретраев (см. build_snapshot_with_retry)."""
    info = ydl.extract_info(url, download=False)
    formats = tuple(info.get("formats") or [])
    subtitles = tuple((info.get("subtitles") or {}).keys())
    return VideoSnapshot(
        video_id=info.get("id", ""),
        title=info.get("title") or "",
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        is_playlist=info.get("_type") == "playlist",
        formats=formats,
        subtitles=subtitles,
        extractor=info.get("extractor_key", "youtube"),
        extraction_strategy=strategy,
        raw_info=info,
    )


def build_snapshot_with_retry(
    ydl: YoutubeDL, url: str, need_ru_audio: bool, log
) -> VideoSnapshot:
    """Максимум 2 extract_info(): Strategy #1, и если нужна русская дорожка, а её не видно —
    ОДИН повторный Strategy #2 (не бесконечный ретрай). Резолверы дальше работают только
    с финальным снапшотом."""
    log("EXTRACTION_STARTED", strategy="strategy_1")
    snapshot = extract_snapshot(ydl, url, strategy="strategy_1")
    log("EXTRACTION_COMPLETED", strategy="strategy_1", formats=len(snapshot.formats))

    if need_ru_audio and not snapshot.has_language("ru"):
        log("EXTRACTION_STARTED", strategy="strategy_2_retry_for_ru")
        retry_snapshot = extract_snapshot(ydl, url, strategy="strategy_2_retry_for_ru")
        log(
            "EXTRACTION_COMPLETED",
            strategy="strategy_2_retry_for_ru",
            formats=len(retry_snapshot.formats),
            ru_found=retry_snapshot.has_language("ru"),
        )
        # Берём тот снапшот, в котором русская дорожка ЕСТЬ. Раньше повторный снапшот
        # заменял первый безусловно — если YouTube на второй попытке отдал урезанный
        # ответ (а именно ради этого случая ретрай и делается), мы теряли уже найденное.
        if retry_snapshot.has_language("ru") or len(retry_snapshot.formats) > len(snapshot.formats):
            snapshot = retry_snapshot

    return snapshot


def _best_video_only(formats: tuple, height_limit: int, vcodec_prefix: str) -> Optional[dict]:
    candidates = [
        f
        for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("acodec") in (None, "none")
        and (f.get("height") or 0) <= height_limit
        and (not vcodec_prefix or (f.get("vcodec") or "").startswith(vcodec_prefix))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))


def _audio_candidates(formats: tuple, acodec_prefix: str) -> list:
    return [
        f
        for f in formats
        if f.get("acodec") not in (None, "none")
        and f.get("vcodec") in (None, "none")
        and (not acodec_prefix or (f.get("acodec") or "").startswith(acodec_prefix))
    ]


def _best_audio(
    formats: tuple,
    language: Optional[str],
    acodec_prefix: str,
    prefer_dubbed: bool = False,
) -> Optional[dict]:
    """Лучшая аудиодорожка. language сравнивается по базовому коду ("ru" совпадает с "ru-RU").

    prefer_dubbed=True — при нескольких русских дорожках (оригинал + нейродубляж) выбрать
    именно дублированную. Такое бывает редко, но если выбрать не ту, пользователь получит
    ровно то, на что жалуется: "скачал с дубляжом, а дубляжа нет"."""
    candidates = _audio_candidates(formats, acodec_prefix)
    if language:
        lang_candidates = [f for f in candidates if lang_matches(f.get("language"), language)]
        if not lang_candidates:
            return None  # запрошен конкретный язык, а такой дорожки в снапшоте нет
        if prefer_dubbed:
            dubbed = [f for f in lang_candidates if not is_original_track(f)]
            if dubbed:
                lang_candidates = dubbed
        return max(lang_candidates, key=lambda f: f.get("abr") or 0)
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.get("abr") or 0)


def _best_muxed(formats: tuple, height_limit: int) -> Optional[dict]:
    candidates = [
        f
        for f in formats
        if f.get("vcodec") not in (None, "none")
        and f.get("acodec") not in (None, "none")
        and (f.get("height") or 0) <= height_limit
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: f.get("height") or 0)


QUALITY_HEIGHTS = {"4K": 2160, "2K": 1440, "1080p": 1080, "720p": 720, "480p": 480, "360p": 360}
VIDEO_CODEC_PREFIX = {"any": "", "h264": "avc1", "vp9": "vp9", "av1": "av01"}
AUDIO_CODEC_PREFIX = {"any": "", "aac": "mp4a", "opus": "opus"}

DUB_LANGUAGE = "ru"


def _video_ladder(snapshot: VideoSnapshot, height_limit: int, vcodec_prefix: str) -> list:
    """Видео-потоки от запрошенной высоты и ВНИЗ, по одному на высоту.

    Раньше бралcя ровно один "лучший видео-поток <= запрошенной высоты", и если под
    фильтр кодека не подошло НИЧЕГО, весь блок "видео + русская дорожка" пропускался
    целиком, а следующим планом шёл progressive (muxed) поток — у него единственная,
    ВСЕГДА оригинальная звуковая дорожка. Внешне загрузка проходила успешно, галка
    "русская дорожка" стояла — а в файле был оригинал. Теперь по видео идёт лестница,
    и русская дорожка отваливается только если её реально нет в снапшоте."""
    ladder: list = []
    seen_ids: set = set()
    for prefix in ([vcodec_prefix, ""] if vcodec_prefix else [""]):
        for height in [height_limit] + [h for h in snapshot.video_heights() if h < height_limit]:
            fmt = _best_video_only(snapshot.formats, height, prefix)
            if fmt and fmt.get("format_id") not in seen_ids:
                seen_ids.add(fmt.get("format_id"))
                ladder.append(fmt)
    return ladder


def build_download_plans(snapshot: VideoSnapshot, item: Any) -> list:
    """Строит упорядоченный список ГОТОВЫХ (уже с конкретными format_id) планов —
    от точного запроса пользователя до максимально permissive. Все format_id берутся
    из ОДНОГО snapshot.formats, так что validate_plan ниже гарантированно пройдёт,
    если только резолвер не ошибся сам с собой (защита от опечаток, не от сети).

    ИНВАРИАНТ: если пользователь попросил русскую дорожку и она есть в снапшоте, то
    ВСЕ планы с ней идут строго раньше любого плана без неё — иначе первая же неудача
    на точном кодеке роняла нас на дорожку по умолчанию."""
    height = QUALITY_HEIGHTS.get(item.quality, QUALITY_HEIGHTS["1080p"])
    vcodec_prefix = VIDEO_CODEC_PREFIX.get(item.video_codec, "")
    acodec_prefix = AUDIO_CODEC_PREFIX.get(item.audio_codec, "")
    container = item.output_container or "mp4"
    want_ru = bool(item.neuro_dub_ru)
    plans: list[DownloadPlan] = []

    if item.audio_only:
        if want_ru:
            for prefix in dict.fromkeys([acodec_prefix, ""]):
                ru_audio = _best_audio(snapshot.formats, DUB_LANGUAGE, prefix, prefer_dubbed=True)
                if ru_audio:
                    plans.append(
                        DownloadPlan(
                            None, ru_audio["format_id"], item.quality, DUB_LANGUAGE, "audio",
                            False, False, True, snapshot.extraction_strategy,
                            f"audio: ru ({prefix or 'any'} codec)",
                        )
                    )
        for prefix in dict.fromkeys([acodec_prefix, ""]):
            best_audio = _best_audio(snapshot.formats, None, prefix)
            if best_audio:
                plans.append(
                    DownloadPlan(
                        None, best_audio["format_id"], item.quality, None, "audio",
                        False, False, True, snapshot.extraction_strategy,
                        f"audio: best ({prefix or 'any'} codec)",
                    )
                )
    else:
        ladder = _video_ladder(snapshot, height, vcodec_prefix)

        # 1. Всё, что содержит русскую дорожку — сначала, по всей лестнице качества.
        if want_ru:
            for prefix in dict.fromkeys([acodec_prefix, ""]):
                ru_audio = _best_audio(snapshot.formats, DUB_LANGUAGE, prefix, prefer_dubbed=True)
                if not ru_audio:
                    continue
                for video in ladder:
                    plans.append(
                        DownloadPlan(
                            video["format_id"], ru_audio["format_id"], item.quality,
                            DUB_LANGUAGE, container, True, False, False,
                            snapshot.extraction_strategy,
                            f"video {video.get('height')}p + ru audio ({prefix or 'any'} codec)",
                        )
                    )

        # 2. Только потом — дорожка по умолчанию.
        for prefix in dict.fromkeys([acodec_prefix, ""]):
            best_audio = _best_audio(snapshot.formats, None, prefix)
            if not best_audio:
                continue
            for video in ladder:
                plans.append(
                    DownloadPlan(
                        video["format_id"], best_audio["format_id"], item.quality,
                        None, container, True, False, False, snapshot.extraction_strategy,
                        f"video {video.get('height')}p + default audio ({prefix or 'any'} codec)",
                    )
                )

        # 3. Последняя надежда — progressive (muxed) поток. У него ВСЕГДА оригинальный
        #    звук, поэтому он не может стоять раньше планов с русской дорожкой.
        muxed = _best_muxed(snapshot.formats, height)
        if muxed:
            plans.append(
                DownloadPlan(
                    muxed["format_id"], None, item.quality, None, muxed.get("ext", "mp4"),
                    False, False, False, snapshot.extraction_strategy, "progressive (muxed) stream",
                )
            )

    # де-дупликация по итоговому селектору с сохранением порядка
    seen = set()
    unique_plans = []
    for p in plans:
        sel = p.format_selector()
        if sel not in seen:
            seen.add(sel)
            unique_plans.append(p)
    return unique_plans


def validate_plan(plan: DownloadPlan, snapshot: VideoSnapshot) -> None:
    """format_id валиден только в контексте своего снапшота — проверяем перед скачиванием."""
    ids = snapshot.format_ids()
    for fid in (plan.video_format_id, plan.audio_format_id):
        if fid is not None and fid not in ids:
            raise FormatSnapshotMismatch(
                f"format_id={fid} отсутствует в снапшоте {snapshot.extraction_strategy} "
                f"(video_id={snapshot.video_id})"
            )


def downloaded_audio_language(info: dict) -> Optional[str]:
    """Язык аудио в ФАКТИЧЕСКИ скачанном результате — по info_dict, который yt-dlp вернул
    из extract_info(download=True). Это метаданные самого выбранного потока, а не догадка
    ffprobe по контейнеру (после склейки DASH-потоков ffmpeg не проставляет язык, и ffprobe
    честно показывает "und"/"eng" даже для настоящей русской дорожки)."""
    requested = info.get("requested_formats")
    if requested:
        for fmt in requested:
            if fmt.get("acodec") not in (None, "none"):
                return fmt.get("language")
        return None
    return info.get("language")
