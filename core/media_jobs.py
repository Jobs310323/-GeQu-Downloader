"""Очередь локальных задач ffmpeg (конвертация/обрезка/ремукс/замена дорожки).

Отдельная от очереди загрузок сознательно: у них разные узкие места. Загрузка упирается
в сеть, и несколько параллельных потоков её ускоряют; ffmpeg упирается в процессор, и
пять одновременных перекодирований делают каждое из них в пять раз медленнее, заодно
подвешивая интерфейс. Поэтому здесь свой пул с маленьким лимитом.

Реализация НЕ на Qt-сигналах (в отличие от DownloadManager): менеджеру не нужно быть
QObject, ему нужен один callback наружу. Меньше машинерии — меньше мест, где сигнал
может потеряться между потоками.
"""

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from core import media_tools
from core.media_tools import FFmpegMissing, MediaError

logger = logging.getLogger("neoloader.media")

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "completed"
STATUS_ERROR = "failed"
STATUS_CANCELLED = "cancelled"

# ffmpeg и так грузит все ядра одним процессом. Второй параллельный job имеет смысл
# только чтобы быстрая операция (ремукс, извлечение аудио) не ждала часовое
# перекодирование — больше двух не даёт ничего, кроме борьбы за процессор.
MAX_PARALLEL_JOBS = 2

KINDS = ("remux", "trim", "replace_audio", "extract_audio", "convert", "gif", "thumbnail")


@dataclass
class MediaJob:
    kind: str
    source: str
    params: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = STATUS_QUEUED
    progress: float = 0.0
    output: str = ""
    error: str = ""
    lossless: Optional[bool] = None
    notes: list = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "source": self.source,
            "source_name": os.path.basename(self.source),
            "params": self.params,
            "status": self.status,
            "progress": round(self.progress, 1),
            "output": self.output,
            "output_name": os.path.basename(self.output) if self.output else "",
            "size": os.path.getsize(self.output) if self.output and os.path.exists(self.output) else 0,
            "error": self.error,
            "lossless": self.lossless,
            "notes": self.notes,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class MediaJobManager:
    """Планирует и выполняет ffmpeg-операции, сообщая о ходе через on_event."""

    def __init__(self, settings=None) -> None:
        self._settings = settings
        self._jobs: dict = {}
        self._order: list = []
        self._lock = threading.Lock()
        self._running = 0
        self.on_event: Optional[Callable] = None

    # --- публичный API ---

    def submit(self, kind: str, source: str, params: Optional[dict] = None) -> MediaJob:
        if kind not in KINDS:
            raise MediaError(f"Неизвестная операция: {kind}")
        if not os.path.exists(source):
            raise MediaError(f"Файл не найден: {source}")
        job = MediaJob(kind=kind, source=source, params=dict(params or {}))
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            # История задач не должна расти бесконечно — держим последние 100
            # ЗАВЕРШЁННЫХ, активные не трогаем ни при каких условиях.
            self._trim_locked()
        self._emit(job)
        self._pump()
        return job

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status == STATUS_QUEUED:
            job.status = STATUS_CANCELLED
            job.finished_at = time.time()
            self._emit(job)
            self._pump()
            return True
        if job.status == STATUS_RUNNING:
            job.cancel_event.set()  # run_plan увидит его и уберёт недописанный файл
            return True
        return False

    def clear_finished(self) -> int:
        with self._lock:
            removed = [
                jid for jid in self._order
                if self._jobs[jid].status in (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED)
            ]
            for jid in removed:
                self._jobs.pop(jid, None)
                self._order.remove(jid)
        return len(removed)

    def snapshot(self) -> list:
        with self._lock:
            return [self._jobs[jid].to_dict() for jid in self._order]

    def get(self, job_id: str) -> Optional[MediaJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel_event.set()

    # --- внутреннее ---

    def _trim_locked(self) -> None:
        finished = [
            jid for jid in self._order
            if self._jobs[jid].status in (STATUS_DONE, STATUS_ERROR, STATUS_CANCELLED)
        ]
        for jid in finished[:-100] if len(finished) > 100 else []:
            self._jobs.pop(jid, None)
            self._order.remove(jid)

    def _emit(self, job: MediaJob) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event({"type": "media", "job": job.to_dict()})
        except Exception:  # noqa: BLE001 — сломанный слушатель не должен ронять обработку
            logger.exception("on_event упал на задаче %s", job.id[:8])

    def _pump(self) -> None:
        """Запускает столько ожидающих задач, сколько разрешает лимит параллелизма."""
        to_start: list = []
        with self._lock:
            free = MAX_PARALLEL_JOBS - self._running
            for jid in self._order:
                if free <= 0:
                    break
                job = self._jobs[jid]
                if job.status == STATUS_QUEUED:
                    job.status = STATUS_RUNNING
                    self._running += 1
                    free -= 1
                    to_start.append(job)
        for job in to_start:
            self._emit(job)
            threading.Thread(target=self._run, args=(job,), name=f"media-{job.id[:8]}", daemon=True).start()

    def _default_folder(self) -> str:
        if self._settings is not None:
            try:
                return self._settings.ensure_download_folder()
            except Exception:  # noqa: BLE001
                pass
        return ""

    def _build_plan(self, job: MediaJob):
        p = job.params
        folder = p.get("output_folder") or self._default_folder()
        if job.kind == "remux":
            return media_tools.plan_remux(job.source, p.get("container", "mp4"), folder=folder)
        if job.kind == "trim":
            return media_tools.plan_trim(
                job.source,
                float(p.get("start", 0) or 0),
                float(p["end"]) if p.get("end") not in (None, "") else None,
                lossless=bool(p.get("lossless", True)),
                container=p.get("container", "") or "",
                folder=folder,
            )
        if job.kind == "replace_audio":
            return media_tools.plan_replace_audio(
                job.source,
                p.get("audio_source", ""),
                folder=folder,
                container=p.get("container", "") or "",
                keep_original_audio=bool(p.get("keep_original_audio", False)),
                language=p.get("language", "") or "",
            )
        if job.kind == "extract_audio":
            return media_tools.plan_extract_audio(
                job.source,
                container=p.get("container", "mp3"),
                bitrate_kbps=int(p["bitrate"]) if p.get("bitrate") else None,
                stream_index=int(p["stream_index"]) if p.get("stream_index") is not None else None,
                folder=folder,
            )
        if job.kind == "convert":
            return media_tools.plan_convert(
                job.source,
                container=p.get("container", "mp4"),
                video_codec=p.get("video_codec", "copy"),
                audio_codec=p.get("audio_codec", "copy"),
                quality=int(p["quality"]) if p.get("quality") is not None else 75,
                video_bitrate_kbps=int(p["video_bitrate"]) if p.get("video_bitrate") else None,
                audio_bitrate_kbps=int(p["audio_bitrate"]) if p.get("audio_bitrate") else 192,
                height=int(p["height"]) if p.get("height") else None,
                fps=float(p["fps"]) if p.get("fps") else None,
                folder=folder,
            )
        if job.kind == "gif":
            return media_tools.plan_gif(
                job.source,
                start=float(p.get("start", 0) or 0),
                duration=float(p.get("duration", 5) or 5),
                fps=int(p.get("fps", 12) or 12),
                width=int(p.get("width", 480) or 480),
                folder=folder,
            )
        if job.kind == "thumbnail":
            return media_tools.plan_thumbnail(
                job.source,
                container=p.get("container", "png"),
                at=float(p.get("at", 0) or 0),
                folder=folder,
            )
        raise MediaError(f"Неизвестная операция: {job.kind}")

    def _run(self, job: MediaJob) -> None:
        # Прогресс от ffmpeg приходит несколько раз в секунду; в WebSocket его столько
        # не нужно — интерфейс всё равно рисует один прогресс-бар. Тот же троттлинг,
        # что и у загрузок, по той же причине: поток событий забивает рендерер.
        state = {"last": 0.0, "percent": -1.0}

        def on_progress(percent: float) -> None:
            now = time.monotonic()
            if percent < 100 and abs(percent - state["percent"]) < 1.0 and now - state["last"] < 0.25:
                return
            state["last"] = now
            state["percent"] = percent
            job.progress = percent
            self._emit(job)

        try:
            plan = self._build_plan(job)
            job.lossless = plan.lossless
            job.notes = list(plan.notes)
            self._emit(job)
            output = media_tools.run_plan(plan, on_progress=on_progress, cancel_event=job.cancel_event)
            job.output = output
            job.progress = 100.0
            job.status = STATUS_DONE
            logger.info(
                "[MEDIA_DONE] job=%s kind=%s lossless=%s out=%s",
                job.id[:8], job.kind, plan.lossless, output,
            )
        except (FFmpegMissing, MediaError) as exc:
            job.error = str(exc)
            job.status = STATUS_CANCELLED if job.cancel_event.is_set() else STATUS_ERROR
            logger.warning("[MEDIA_FAILED] job=%s kind=%s %s", job.id[:8], job.kind, exc)
        except Exception as exc:  # noqa: BLE001 — любая неожиданность должна дойти до UI
            job.error = str(exc)
            job.status = STATUS_ERROR
            logger.exception("[MEDIA_CRASH] job=%s kind=%s", job.id[:8], job.kind)
        finally:
            job.finished_at = time.time()
            with self._lock:
                self._running = max(0, self._running - 1)
            self._emit(job)
            self._pump()
