"""Менеджер очереди загрузок: работает в отдельном QThread, управляет yt-dlp.

Пайплайн одной задачи (см. core/resolver.py для деталей Snapshot/Plan):

    QUEUED -> ANALYZING (build_snapshot_with_retry, максимум 2 extract_info)
           -> RESOLVING  (build_download_plans + validate_plan — работа только со снапшотом,
                           без единого нового похода в сеть)
           -> STARTING   (перед первым extract_info(download=True) на выбранном плане)
           -> DOWNLOADING (прогресс по байтам)
           -> MERGING / CONVERTING (постпроцессинг ffmpeg, если нужен)
           -> COMPLETED (после проверки, что файл реально существует и не пуст)
           или FAILED / CANCELLED / PAUSED на любом шаге.
"""

import logging
import os
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field

from PyQt6.QtCore import QThread, pyqtSignal
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from core.ffmpeg_locator import ffmpeg_location, find_ffmpeg, find_ffprobe
from core.js_runtime import available_js_runtimes
from core.resolver import (
    DUB_LANGUAGE,
    FormatSnapshotMismatch,
    build_download_plans,
    build_snapshot_with_retry,
    downloaded_audio_language,
    lang_matches,
    validate_plan,
)

logger = logging.getLogger("neoloader.download")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

# Минимум свободного места на диске перед стартом загрузки (500 МБ с запасом на постобработку).
MIN_FREE_SPACE_BYTES = 500 * 1024 * 1024

# Кодеки, которые понимает yt-dlp'шный FFmpegExtractAudio. Всё, чего здесь нет
# (в частности "original"), означает «оставить поток как скачался».
AUDIO_EXTRACT_CODECS = frozenset({"aac", "alac", "flac", "m4a", "mp3", "opus", "vorbis", "wav"})

STATUS_PENDING = "queued"
STATUS_ANALYZING = "analyzing"
STATUS_RESOLVING = "resolving"
STATUS_STARTING = "starting"
STATUS_DOWNLOADING = "downloading"
STATUS_MERGING = "merging"
STATUS_CONVERTING = "converting"
STATUS_PAUSED = "paused"
STATUS_DONE = "completed"
STATUS_ERROR = "failed"
STATUS_CANCELLED = "cancelled"


class DownloadCancelledError(Exception):
    """Внутреннее исключение для прерывания скачивания из хука прогресса."""


class DownloadVerificationError(Exception):
    """Файл после скачивания не прошёл проверку (не создан / пустой)."""


def _new_pause_event() -> threading.Event:
    # Событие "не на паузе" по умолчанию — set() означает "можно качать".
    event = threading.Event()
    event.set()
    return event


@dataclass
class QueueItem:
    """Одна запись в очереди загрузок."""

    url: str
    title: str = ""
    quality: str = "1080p"
    audio_only: bool = False
    audio_format: str = "mp3"
    audio_bitrate: str = "192"
    subtitles: bool = False
    subtitle_langs: list = field(default_factory=lambda: ["ru", "en"])
    neuro_dub_ru: bool = False
    video_codec: str = "any"
    audio_codec: str = "any"
    output_container: str = "mp4"
    output_folder: str = ""
    is_playlist: bool = False
    create_playlist_folder: bool = True
    remove_after_download: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = STATUS_PENDING
    # Раньше пауза/отмена были одним общим флагом на весь DownloadManager — это работало,
    # пока очередь качалась строго по одному элементу. С параллельными загрузками (concurrent_downloads)
    # несколько задач одновременно бегут в разных потоках, поэтому у каждой свой флаг.
    pause_event: threading.Event = field(default_factory=_new_pause_event, repr=False, compare=False)
    cancelled: bool = field(default=False, repr=False, compare=False)
    # None — русская дорожка не запрашивалась; True/False — подтверждена/не подтверждена
    # по info_dict фактически скачанного потока (см. _verify_download).
    ru_dub_confirmed: bool | None = field(default=None, repr=False, compare=False)


class DownloadManager(QThread):
    """Обрабатывает очередь QueueItem последовательно в фоновом потоке."""

    progress_changed = pyqtSignal(str, float, str)  # item_id, percent, speed_str
    status_changed = pyqtSignal(str, str)  # item_id, status
    log_message = pyqtSignal(str, str)  # level ("info"/"success"/"warning"/"error"), text
    error_occurred = pyqtSignal(str, str, str)  # item_id, error_code, message
    item_finished = pyqtSignal(str, dict)  # item_id, итоговые метаданные (для истории)

    def __init__(self, settings=None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings  # SettingsManager | None — источник proxy/cookies/шаблона/параллелизма
        self._queue: list[QueueItem] = []
        self._lock = threading.Lock()
        self._active_items: dict[str, QueueItem] = {}
        self._stop_worker = False
        # Раньше цикл run() крутился на time.sleep(0.3) и просыпался 3 раза в секунду
        # вечно, даже когда очередь пуста и приложение просто висит в трее. Событие даёт
        # и мгновенный старт новой задачи, и нулевой расход CPU в простое.
        self._wake = threading.Event()

    # --- управление очередью (вызывается из UI-потока) ---

    def add_to_queue(self, item: QueueItem) -> None:
        with self._lock:
            self._queue.append(item)
        self._log_event("TASK_CREATED", item)
        self._log_event("TASK_QUEUED", item)
        self.log_message.emit("info", f"Добавлено в очередь: {item.title or item.url}")
        if not self.isRunning():
            self._stop_worker = False
            self.start()
        self._wake.set()

    def remove_from_queue(self, item_id: str) -> None:
        with self._lock:
            self._queue = [i for i in self._queue if i.id != item_id]

    def get_queue_snapshot(self) -> list[QueueItem]:
        """Копия текущей очереди (для API-снимка, не для мутации)."""
        with self._lock:
            return list(self._queue)

    def move_item(self, item_id: str, delta: int) -> bool:
        """Сдвигает ОЖИДАЮЩУЮ задачу по очереди. Активные не двигаем: их порядок уже
        ничего не решает (они качаются), а перестановка сбивала бы нумерацию в UI."""
        with self._lock:
            index = next((n for n, i in enumerate(self._queue) if i.id == item_id), None)
            if index is None:
                return False
            item = self._queue[index]
            if item.status not in (STATUS_PENDING, STATUS_PAUSED):
                return False
            target = max(0, min(len(self._queue) - 1, index + delta))
            if target == index:
                return False
            self._queue.insert(target, self._queue.pop(index))
            return True

    def pause_item(self, item_id: str) -> bool:
        """Пауза для ЛЮБОГО элемента — и качающегося, и ещё ожидающего.

        Раньше пауза работала только для активной задачи, поэтому «поставить очередь
        на паузу» было невозможно: остановишь текущую — тут же стартует следующая.
        Ожидающая задача переводится в PAUSED, а _launch_available берёт только PENDING,
        так что она просто не запустится, пока её не вернут.
        """
        active = self._get_active(item_id)
        if active is not None:
            active.pause_event.clear()
            self._set_status(active, STATUS_PAUSED)
            self.log_message.emit("warning", "Загрузка приостановлена")
            return True
        with self._lock:
            item = next((i for i in self._queue if i.id == item_id), None)
        if item is None or item.status != STATUS_PENDING:
            return False
        self._set_status(item, STATUS_PAUSED)
        return True

    def resume_item(self, item_id: str) -> bool:
        active = self._get_active(item_id)
        if active is not None:
            active.pause_event.set()
            self._set_status(active, STATUS_DOWNLOADING)
            self.log_message.emit("info", "Загрузка возобновлена")
            self._wake.set()  # освободившийся слот мог ждать именно её
            return True
        with self._lock:
            item = next((i for i in self._queue if i.id == item_id), None)
        if item is None or item.status != STATUS_PAUSED:
            return False
        self._set_status(item, STATUS_PENDING)
        self._wake.set()
        return True

    def pause_all(self) -> int:
        ids = [i.id for i in self.get_queue_snapshot()] + self.get_active_item_ids()
        return sum(1 for item_id in dict.fromkeys(ids) if self.pause_item(item_id))

    def resume_all(self) -> int:
        ids = [i.id for i in self.get_queue_snapshot()] + self.get_active_item_ids()
        return sum(1 for item_id in dict.fromkeys(ids) if self.resume_item(item_id))

    def clear_pending(self) -> int:
        """Убирает из очереди всё, что ещё не начало качаться. Активные не трогает —
        их обрывают отдельной отменой, чтобы не потерять уже скачанные гигабайты молча."""
        active = set(self.get_active_item_ids())
        with self._lock:
            before = len(self._queue)
            self._queue = [i for i in self._queue if i.id in active]
            return before - len(self._queue)

    def get_current_item_id(self) -> str | None:
        """Id первой активной (реально скачивающейся) задачи, или None.
        При concurrent_downloads=1 (по умолчанию) это единственная активная задача —
        поведение совпадает со старым API для обратной совместимости со старым UI."""
        with self._lock:
            return next(iter(self._active_items), None)

    def get_active_item_ids(self) -> list[str]:
        """Id всех задач, которые скачиваются прямо сейчас (может быть больше одной)."""
        with self._lock:
            return list(self._active_items.keys())

    def _get_active(self, item_id: str | None) -> QueueItem | None:
        with self._lock:
            if item_id is not None:
                return self._active_items.get(item_id)
            return next(iter(self._active_items.values()), None)

    def pause_current(self, item_id: str | None = None) -> None:
        """Совместимость со старым виджетным UI: пауза «текущей» задачи."""
        item = self._get_active(item_id)
        if item is not None:
            self.pause_item(item.id)

    def resume_current(self, item_id: str | None = None) -> None:
        item = self._get_active(item_id)
        if item is not None:
            self.resume_item(item.id)

    def cancel_current(self, item_id: str | None = None) -> None:
        item = self._get_active(item_id)
        if item is None:
            return
        item.cancelled = True
        item.pause_event.set()  # разбудить, если стояла на паузе, чтобы дошла до проверки отмены

    def stop(self) -> None:
        """Останавливает воркер после завершения текущих задач."""
        self._stop_worker = True
        self._wake.set()

    # --- основной цикл (выполняется в фоновом потоке) ---

    def run(self) -> None:
        while not self._stop_worker:
            self._launch_available()
            # Таймаут нужен, чтобы освободившийся слот параллелизма подхватился и без
            # нового add_to_queue (задача завершилась — очередь могла остаться непустой).
            self._wake.wait(timeout=1.0)
            self._wake.clear()

    def _launch_available(self) -> None:
        """Запускает столько ожидающих задач параллельно, сколько разрешает
        concurrent_downloads (по умолчанию 1 — старое последовательное поведение)."""
        concurrency = 1
        if self._settings is not None:
            try:
                concurrency = max(1, int(self._settings.get("concurrent_downloads", 1)))
            except (TypeError, ValueError):
                concurrency = 1

        to_launch: list[QueueItem] = []
        with self._lock:
            # Задача на паузе всё ещё числится в _active_items (её поток жив, просто спит
            # в progress_hook), но байты не качает — не должна занимать слот параллелизма,
            # иначе следующая в очереди никогда не стартует, пока эту не снимут с паузы.
            downloading_count = sum(
                1 for i in self._active_items.values() if i.status != STATUS_PAUSED
            )
            slots = concurrency - downloading_count
            if slots > 0:
                for item in self._queue:
                    if len(to_launch) >= slots:
                        break
                    if item.status == STATUS_PENDING:
                        to_launch.append(item)
                for item in to_launch:
                    self._active_items[item.id] = item

        for item in to_launch:
            threading.Thread(target=self._run_item, args=(item,), daemon=True).start()

    def _run_item(self, item: QueueItem) -> None:
        try:
            self._process_item(item)
        finally:
            with self._lock:
                self._active_items.pop(item.id, None)
            self._wake.set()  # слот освободился — не ждём целую секунду до следующей задачи
            # Задача дошла до терминального статуса (completed/failed/cancelled) — история
            # уже отдельно сохранена через item_finished/settings.add_history_entry, а сам
            # _queue дальше нужен только для планирования следующих запусков и счётчика
            # в трее. Раньше завершённые задачи молча копились в _queue навсегда (если
            # remove_after_download не включён), из-за чего и трей, и /api/queue показывали
            # "в очереди N", хотя реально ничего не качалось и не ждало — это были старые
            # завершённые/упавшие/отменённые задачи.
            self.remove_from_queue(item.id)

    def _set_status(self, item: QueueItem, status: str) -> None:
        item.status = status
        self.status_changed.emit(item.id, status)

    def _log_event(self, tag: str, item: QueueItem, **fields) -> None:
        """Структурированный лог жизненного цикла задачи. Никаких cookies/токенов сюда не пишем."""
        parts = [f"[{tag}]", f"taskId={item.id[:8]}", f"t={time.time():.3f}", f"state={item.status}"]
        for k, v in fields.items():
            parts.append(f"{k}={v}")
        logger.info(" ".join(parts))

    def _process_item(self, item: QueueItem) -> None:
        self._log_event("TASK_WORKER_PICKED", item)

        if not self._check_disk_space(item):
            self._set_status(item, STATUS_ERROR)
            self.error_occurred.emit(item.id, "no_space", "Недостаточно места на диске")
            self._log_event("TASK_FAILED", item, reason="no_space")
            return

        try:
            final_path = self._run_pipeline(item)
            self._set_status(item, STATUS_DONE)
            self.log_message.emit("success", f"Готово: {item.title or item.url}")
            self._log_event("DOWNLOAD_COMPLETED", item, path=final_path)
            self.item_finished.emit(
                item.id,
                {
                    "url": item.url,
                    "title": item.title,
                    # История раньше хранила только url+title, поэтому «Открыть папку»
                    # и фильтры по дате/размеру были невозможны в принципе.
                    "path": final_path or "",
                    "size": os.path.getsize(final_path) if final_path and os.path.exists(final_path) else 0,
                    "finished_at": time.time(),
                    "audio_only": item.audio_only,
                    "quality": item.quality,
                    "ru_dub": item.ru_dub_confirmed,
                },
            )
        except DownloadCancelledError:
            self._set_status(item, STATUS_CANCELLED)
            self.log_message.emit("warning", f"Отменено: {item.title or item.url}")
            self._log_event("TASK_FAILED", item, reason="cancelled")
        except (FormatSnapshotMismatch, DownloadVerificationError) as exc:
            self._set_status(item, STATUS_ERROR)
            self.error_occurred.emit(item.id, "unknown", str(exc))
            self.log_message.emit("error", str(exc))
            self._log_event("TASK_FAILED", item, reason=type(exc).__name__, error=str(exc))
        except DownloadError as exc:
            code, message = self._classify_error(str(exc))
            self._set_status(item, STATUS_ERROR)
            self.error_occurred.emit(item.id, code, message)
            self.log_message.emit("error", message)
            self._log_event("TASK_FAILED", item, reason=code)
        except Exception as exc:  # noqa: BLE001 — любая непредвиденная ошибка должна дойти до UI, а не убить поток
            self._set_status(item, STATUS_ERROR)
            self.error_occurred.emit(item.id, "unknown", str(exc))
            self.log_message.emit("error", str(exc))
            self._log_event("TASK_FAILED", item, reason="unknown", error=str(exc))

    def _run_pipeline(self, item: QueueItem) -> str:
        """ANALYZING -> RESOLVING -> STARTING -> DOWNLOADING -> (MERGING/CONVERTING) -> проверка
        файла. Возвращает путь к итоговому файлу или бросает исключение."""
        result_holder: dict = {"path": None}
        probe_opts = self._build_ydl_opts(item, result_holder)

        with YoutubeDL(probe_opts) as ydl:
            self._set_status(item, STATUS_ANALYZING)

            def log(tag: str, **fields) -> None:
                self._log_event(tag, item, **fields)

            snapshot = build_snapshot_with_retry(ydl, item.url, need_ru_audio=item.neuro_dub_ru, log=log)

            self._set_status(item, STATUS_RESOLVING)
            log("RESOLUTION_STARTED")
            plans = build_download_plans(snapshot, item)
            if not plans:
                raise DownloadError("Не найдено ни одного пригодного формата для этого видео")
            for plan in plans:
                validate_plan(plan, snapshot)  # FormatSnapshotMismatch, если резолвер ошибся
            log("RESOLUTION_COMPLETED", plans=len(plans), first=plans[0].label)

        # ВАЖНО, разобрано и подтверждено побайтовым сравнением скачанных файлов (ffprobe +
        # точное совпадение размера с отдельно скачанным потоком): переиспользование ОДНОГО
        # YoutubeDL + уже обработанного info_dict через ydl.process_video_result(info, download=True)
        # ненадёжно для языковых format_id вида "140-16" (суффикс, которым yt-dlp различает
        # несколько аудиодорожек одного itag) — при повторном вызове на уже раз обработанном
        # info_dict внутренний пересчёт формата иногда тихо съезжает на другую дорожку того же
        # itag-семейства, без единой ошибки (план "видео+ru-аудио" реально скачивал оригинальную
        # английскую дорожку). Просто задать ydl.params["format"] или даже пересобрать
        # ydl.format_selector после конструктора — тоже не помогает, т.к. process_video_result
        # заново прогоняет весь пайплайн выбора формата поверх уже "обработанных" данных.
        # Единственный надёжный способ — НОВЫЙ YoutubeDL с "format" в опциях КОНСТРУКТОРА
        # и один настоящий ydl.extract_info(url, download=True) на каждую попытку плана —
        # это штатный, документированный путь yt-dlp, и именно так format_id гарантированно
        # соответствует скачанному файлу (проверено многократно, включая побайтовое сравнение).
        self._set_status(item, STATUS_STARTING)
        # Склейка отдельных видео- и аудиопотоков (а значит и любая русская дорожка,
        # и качество выше 360p) физически невозможна без ffmpeg. Без этой проверки
        # все merge-планы просто падали по очереди, и пользователь получал 360p
        # progressive без объяснений.
        if any(p.needs_merge for p in plans) and find_ffmpeg() is None:
            self.log_message.emit(
                "error",
                "ffmpeg не найден — доступны только потоки без склейки (низкое качество, "
                "без выбора аудиодорожки). Установите ffmpeg и перезапустите приложение",
            )
        ru_was_offered = any(p.requested_language == DUB_LANGUAGE for p in plans)
        last_exc: DownloadError | None = None
        for i, plan in enumerate(plans):
            attempt_opts = self._build_ydl_opts(item, result_holder)
            attempt_opts["format"] = plan.format_selector()
            # yt-dlp сам ретраит транзиентные сетевые обрывы (TCP reset, SSL EOF) внутри
            # одного extract_info() — свой отдельный Python-цикл ретраев тут не нужен.
            attempt_opts.setdefault("retries", 5)
            attempt_opts.setdefault("fragment_retries", 5)
            log("DOWNLOAD_STARTED", plan=plan.label, selector=plan.format_selector())
            try:
                with YoutubeDL(attempt_opts) as dl_ydl:
                    info = dl_ydl.extract_info(item.url, download=True)
                    final_path = result_holder["path"] or self._guess_output_path(dl_ydl, info)
            except DownloadError as exc:
                last_exc = exc
                log("TASK_FAILED", reason="plan_failed", plan=plan.label)
                if i < len(plans) - 1:
                    self.log_message.emit("warning", "Вариант недоступен, пробую следующий...")
                    self._set_status(item, STATUS_STARTING)
                continue

            self._verify_download(final_path, item, info, plan)
            if i > 0:
                self._announce_fallback(item, plans, i)
            if item.neuro_dub_ru and not ru_was_offered:
                # Пользователь явно попросил русскую дорожку, а в снапшоте её не оказалось
                # НИ В ОДНОМ плане — значит первый же план качал дорожку по умолчанию.
                # Раньше этот случай не логировался вообще (предупреждение висело только
                # на переходе между планами, i > 0), поэтому загрузка выглядела успешной,
                # а в файле был оригинальный звук.
                self.log_message.emit(
                    "error",
                    "Русская аудиодорожка у этого видео недоступна — скачан оригинальный звук",
                )
            return final_path
        raise last_exc

    def _announce_fallback(self, item: QueueItem, plans: list, index: int) -> None:
        prev_had_ru = plans[index - 1].requested_language == DUB_LANGUAGE
        now_has_ru = plans[index].requested_language == DUB_LANGUAGE
        if item.neuro_dub_ru and prev_had_ru and not now_has_ru:
            self.log_message.emit(
                "error",
                "Русская дорожка недоступна из-за защиты YouTube — скачана обычная версия видео",
            )
        else:
            self.log_message.emit("warning", "Точный формат недоступен — скачан ближайший рабочий вариант")

    def _guess_output_path(self, ydl: YoutubeDL, info: dict) -> str | None:
        downloads = info.get("requested_downloads") or []
        if downloads and downloads[-1].get("filepath"):
            return downloads[-1]["filepath"]
        try:
            return ydl.prepare_filename(info)
        except Exception:
            return None

    def _verify_download(
        self, path: str | None, item: QueueItem, info: dict | None = None, plan=None
    ) -> None:
        """Не считаем задачу выполненной только потому, что yt-dlp не бросил исключение —
        файл должен реально существовать и быть не пустым."""
        if not path or not os.path.exists(path):
            raise DownloadVerificationError(f"Файл не найден после скачивания: {path}")
        size = os.path.getsize(path)
        if size <= 0:
            raise DownloadVerificationError(f"Скачанный файл пуст: {path}")

        if not item.neuro_dub_ru:
            return

        # Раньше здесь БЕЗУСЛОВНО проставлялся тег language=rus, и только потом файл
        # "проверялся" ffprobe — то есть проверялось ровно то, что мы сами только что
        # и записали. Результат всегда сходился, предупреждение не появлялось никогда,
        # и пользователь получал файл, который по метаданным русский, а по звуку нет.
        # Теперь источник правды — info_dict от yt-dlp: там лежит язык РЕАЛЬНО выбранного
        # аудиопотока. Тег дописываем только после того, как язык подтверждён.
        actual_lang = downloaded_audio_language(info or {})
        planned_ru = plan is not None and plan.requested_language == DUB_LANGUAGE
        confirmed = lang_matches(actual_lang, DUB_LANGUAGE) if actual_lang else planned_ru
        item.ru_dub_confirmed = bool(confirmed)

        if confirmed:
            self._tag_ru_audio(path)
            self._log_event("DUB_CONFIRMED", item, lang=actual_lang or "unknown")
        else:
            self._log_event("DUB_MISSING", item, lang=actual_lang or "unknown")
            self.log_message.emit(
                "error",
                f"Русской дорожки в скачанном файле нет (язык потока: {actual_lang or 'неизвестен'})",
            )

    def _container_audio_language(self, path: str) -> str | None:
        """Язык аудиодорожки по метаданным КОНТЕЙНЕРА (не по info_dict). Нужен только
        чтобы не переписывать файл зря — сам факт «русская дорожка» подтверждается
        по info_dict в _verify_download, а не отсюда."""
        ffprobe = find_ffprobe()
        if not ffprobe:
            return None
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
                 "stream_tags=language", "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=15,
            )
            return out.stdout.strip().lower() or None
        except Exception:  # noqa: BLE001
            return None

    def _tag_ru_audio(self, path: str) -> None:
        """Проставляет language=rus на аудиопотоке файла (без перекодирования — только
        метаданные), чтобы плееры/проводник корректно показывали русскую дорожку."""
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return
        if self._container_audio_language(path) in ("rus", "ru"):
            return  # тег уже на месте — незачем переписывать файл целиком
        try:
            size = os.path.getsize(path)
            if shutil.disk_usage(os.path.dirname(path) or ".").free < size * 1.1:
                # Перетегирование делается через временную копию: на 4K-файле это
                # ещё столько же места. Не начинаем, если его заведомо не хватит —
                # иначе получим оборванный .retag и мусор рядом с результатом.
                self.log_message.emit(
                    "warning",
                    "Не хватает места, чтобы проставить метку языка — файл скачан, тег не записан",
                )
                return
        except OSError:
            return
        base, ext = os.path.splitext(path)
        tmp_path = f"{base}.retag{ext}"
        try:
            result = subprocess.run(
                [ffmpeg, "-y", "-i", path, "-map", "0", "-c", "copy",
                 "-metadata:s:a:0", "language=rus", tmp_path],
                capture_output=True, timeout=120,
            )
            if result.returncode == 0 and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                os.replace(tmp_path, path)
            elif os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def _target_folder(self, item: QueueItem) -> str:
        """Папка загрузки. os.getcwd() как fallback раньше означал, что при пустом
        output_folder файл уезжал в рабочую директорию процесса (для EXE — куда угодно,
        вплоть до системной папки Windows при запуске из ярлыка), а не в папку из настроек."""
        folder = item.output_folder
        if not folder and self._settings is not None:
            folder = self._settings.ensure_download_folder()
        return folder or os.path.join(os.path.expanduser("~"), "Downloads")

    def _check_disk_space(self, item: QueueItem) -> bool:
        folder = self._target_folder(item)
        os.makedirs(folder, exist_ok=True)
        usage = shutil.disk_usage(folder)
        return usage.free >= MIN_FREE_SPACE_BYTES

    def _build_ydl_opts(self, item: QueueItem, result_holder: dict) -> dict:
        """Опции yt-dlp, общие для всей задачи (extract + все ступени плана). format
        выставляется отдельно, в attempt_opts каждой ступени плана — см. _run_pipeline."""
        folder = self._target_folder(item)
        filename_template = "%(title)s.%(ext)s"
        if self._settings is not None:
            filename_template = self._settings.get("filename_template", filename_template) or filename_template
        if item.is_playlist and item.create_playlist_folder:
            out_template = os.path.join(folder, "%(playlist_title)s", filename_template)
        else:
            out_template = os.path.join(folder, filename_template)

        opts: dict = {
            "outtmpl": out_template,
            "progress_hooks": [self._make_progress_hook(item, result_holder)],
            "postprocessor_hooks": [self._make_postprocessor_hook(item, result_holder)],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": not item.is_playlist,
            "ignoreerrors": False,
            "socket_timeout": 20,
            # По умолчанию yt-dlp пробует решать JS-челлендж YouTube только через deno.
            # Прописывать оба движка вслепую значило ждать таймаут на каждом запуске
            # отсутствующего — берём только те, что реально стоят в системе.
            "js_runtimes": available_js_runtimes(),
            # Windows-safe имена файлов: заголовок ролика с ? * : " / \ иначе рушит
            # запись файла в самом конце, после того как всё уже скачано.
            "windowsfilenames": True,
            # Фрагментированные DASH-потоки качаются параллельно — на 1080p+ разница
            # в скорости кратная, а нагрузка на диск та же.
            "concurrent_fragment_downloads": 4,
        }

        # Явно указываем yt-dlp, где искать ffmpeg/ffprobe — в собранном EXE это бандл
        # в assets/bin/ (см. build.spec), а не системный PATH (см. core/ffmpeg_locator.py).
        location = ffmpeg_location()
        if location:
            opts["ffmpeg_location"] = location

        if self._settings is not None:
            proxy = self._settings.get("proxy", "")
            if proxy:
                opts["proxy"] = proxy
            cookies_browser = self._settings.get("cookies_from_browser", "none")
            if cookies_browser and cookies_browser != "none":
                # yt-dlp сам достаёт куки из профиля браузера — не храним/не логируем их сами.
                # Формат опции — кортеж (browser, profile, keyring, container); нужен только browser.
                opts["cookiesfrombrowser"] = (cookies_browser,)

        if item.audio_only:
            # "original" = вообще не запускать постпроцессор: скачанный аудиопоток
            # остаётся ровно таким, каким его отдал YouTube (обычно opus в .webm или
            # aac в .m4a). Это единственный по-настоящему без потерь вариант — любая
            # перекодировка в mp3 из lossy-источника режет качество ещё раз.
            # Раньше "original" уходил в preferredcodec как есть, а yt-dlp такого
            # кодека не знает — постпроцессор падал на списке поддерживаемых.
            if item.audio_format in AUDIO_EXTRACT_CODECS:
                opts["postprocessors"] = [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": item.audio_format,
                        "preferredquality": item.audio_bitrate,
                    }
                ]
        else:
            opts["merge_output_format"] = item.output_container or "mp4"

        if item.subtitles:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = item.subtitle_langs
            opts["subtitlesformat"] = "srt"

        return opts

    def _make_progress_hook(self, item: QueueItem, result_holder: dict):
        # yt-dlp дёргает progress_hooks на каждый прочитанный чанк — на быстром соединении
        # это может быть сотни раз в секунду. Без троттлинга такой поток WS-событий на
        # каждый тик триггерит React re-render + перекладку у framer-motion в QWebEngineView,
        # что забивает главный поток рендерера: клики (например, по "Настройки") перестают
        # обрабатываться вовремя, а если так копится достаточно долго — Windows может
        # посчитать окно зависшим. Эмитим не чаще, чем раз в MIN_EMIT_INTERVAL, плюс
        # обязательно на заметных сдвигах процента и на финальном тике.
        MIN_EMIT_INTERVAL = 0.25
        state = {"last_emit": 0.0, "last_percent": -1.0}

        def hook(d: dict) -> None:
            # Проверка отмены/паузы на каждый вызов хука — здесь единственная безопасная
            # точка прервать скачивание, т.к. QThread.terminate() может повредить файл.
            if item.cancelled:
                raise DownloadCancelledError()
            if not item.pause_event.is_set():
                # Паузу могли нажать, пока задача ещё анализировалась: тогда флаг снят,
                # а статус успел перезаписаться на analyzing/downloading следующим шагом
                # пайплайна. Здесь — первая точка, где пауза реально вступает в силу,
                # поэтому статус приводим в соответствие именно тут, иначе интерфейс
                # показывает «качается» у намертво замершей задачи.
                if item.status != STATUS_PAUSED:
                    self._set_status(item, STATUS_PAUSED)
                while not item.pause_event.is_set():
                    time.sleep(0.2)
                    if item.cancelled:
                        raise DownloadCancelledError()
                if item.status == STATUS_PAUSED:
                    self._set_status(item, STATUS_DOWNLOADING)

            if d["status"] == "downloading":
                if item.status != STATUS_DOWNLOADING:
                    self._set_status(item, STATUS_DOWNLOADING)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                percent = (downloaded / total * 100) if total else 0.0
                speed = d.get("speed")
                speed_str = f"{speed / 1024 / 1024:.2f} МБ/с" if speed else "..."

                now = time.monotonic()
                percent_jump = abs(percent - state["last_percent"]) >= 1.0
                if not percent_jump and (now - state["last_emit"]) < MIN_EMIT_INTERVAL:
                    return
                state["last_emit"] = now
                state["last_percent"] = percent
                self.progress_changed.emit(item.id, percent, speed_str)
            elif d["status"] == "finished":
                self.progress_changed.emit(item.id, 100.0, "")
                result_holder["path"] = d.get("filename") or result_holder.get("path")

        return hook

    def _make_postprocessor_hook(self, item: QueueItem, result_holder: dict):
        def hook(d: dict) -> None:
            name = d.get("postprocessor", "")
            if d.get("status") == "started":
                if "Merger" in name:
                    self._set_status(item, STATUS_MERGING)
                    self.log_message.emit("info", "Склейка видео и аудио...")
                elif "ExtractAudio" in name:
                    self._set_status(item, STATUS_CONVERTING)
                    self.log_message.emit("info", "Конвертация аудио...")
            elif d.get("status") == "finished":
                info = d.get("info_dict") or {}
                fp = info.get("filepath") or info.get("_filename")
                if fp:
                    result_holder["path"] = fp

        return hook

    @staticmethod
    def _classify_error(message: str) -> tuple[str, str]:
        """Переводит текст ошибки yt-dlp в понятный пользователю код+сообщение."""
        lower = message.lower()
        if "sign in to confirm your age" in lower or "age" in lower and "restrict" in lower:
            return "age_restricted", "Видео требует подтверждения возраста"
        if "not available in your country" in lower or "geo" in lower and "restrict" in lower:
            return "geo_blocked", "Видео недоступно в вашем регионе"
        if "video unavailable" in lower:
            return "unavailable", "Видео недоступно или удалено"
        if "unable to download webpage" in lower or "urlopen" in lower or "network" in lower:
            return "network", "Проблема с подключением к интернету"
        if "unsupported url" in lower or "is not a valid url" in lower:
            return "invalid_url", "Ссылка не поддерживается или некорректна"
        if "cookies database" in lower or "could not copy" in lower and "cookie" in lower:
            return "unknown", "Не удалось прочитать куки браузера (закройте браузер и попробуйте снова, или отключите эту опцию в настройках)"
        if "sign in to confirm" in lower and "bot" in lower:
            return "unknown", (
                "YouTube требует подтвердить, что вы не бот. Включите в настройках "
                "«Cookies from browser» (например chrome) и повторите загрузку"
            )
        if "requested format is not available" in lower:
            return "unknown", "Ни один из доступных форматов не подошёл — попробуйте другое качество"
        if "proxy" in lower and ("connect" in lower or "refused" in lower or "timed out" in lower):
            return "network", "Не удалось подключиться через прокси — проверьте адрес в настройках"
        return "unknown", message
