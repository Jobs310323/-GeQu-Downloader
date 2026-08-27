"""FastAPI + WebSocket мост между React-фронтендом и существующим Python-движком
(SettingsManager/VideoInfo/DownloadManager). Существующая логика скачивания не меняется —
этот слой только транслирует её сигналы/методы в HTTP/WS API.

Важное свойство слоя: НИ ОДИН эндпоинт не должен занимать общий пул потоков FastAPI
надолго. Синхронный `def`-эндпоинт FastAPI выполняет в общем threadpool (по умолчанию
40 воркеров) — а один разбор ссылки через yt-dlp занимает 10-25 секунд. Пока фронтенд
в цикле переспрашивал /api/analyze, пул выедался целиком, и тогда ВСЕ остальные
запросы (настройки, очередь, диагностика) вставали в очередь за ним. Снаружи это
выглядело как «настройки не открываются» и «бесконечный анализ» одновременно, хотя
причина одна. Поэтому: быстрые эндпоинты — `async def` (выполняются прямо в event loop),
медленные (yt-dlp) — в отдельном ограниченном executor'е с дедупликацией и кэшом.
"""

import asyncio
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PyQt6.QtCore import Qt
from yt_dlp.version import __version__ as YTDLP_VERSION

from api.models import (
    AnalyzeRequest,
    BatchQueueRequest,
    FilePickRequest,
    FolderPickRequest,
    MediaJobRequest,
    PlaylistRequest,
    ProbeRequest,
    QueueItemRequest,
    QueueMoveRequest,
    RevealRequest,
    SettingsUpdateRequest,
    SummaryRequest,
)
from core import media_tools
from core.download_manager import DownloadManager, QueueItem
from core.ffmpeg_locator import find_ffmpeg
from core.media_jobs import MediaJobManager
from core.media_tools import FFmpegMissing, MediaError
from core.settings_manager import SettingsManager
from core.summarizer import TranscriptUnavailable, build_summary
from core.video_info import (
    BATCH_LINK_TYPES,
    LinkType,
    VideoInfo,
    detect_link_type,
    fetch_playlist_entries,
)

logger = logging.getLogger("neoloader.api")

# Сопоставление внутренних кодов ошибок DownloadManager с кодами, понятными фронтенду.
ERROR_CODE_MAP = {
    "no_space": "DISK_FULL",
    "age_restricted": "AGE_RESTRICTED",
    "geo_blocked": "GEO_RESTRICTED",
    "unavailable": "VIDEO_UNAVAILABLE",
    "network": "NETWORK_ERROR",
    "invalid_url": "INVALID_URL",
    "unknown": "UNKNOWN_ERROR",
}

# Метаданные видео на YouTube меняются раз в вечность, а один разбор стоит 10-25 секунд.
ANALYZE_CACHE_TTL = 600
# yt-dlp и так делает несколько сетевых запросов на видео; больше двух параллельных
# разборов не ускоряют работу, зато отлично ловят антибот-лимит YouTube.
ANALYZE_WORKERS = 2
SUMMARY_WORKERS = 2


def frontend_dist_dir() -> Path | None:
    """Папка со собранным React-приложением, или None если сборки нет."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent
    candidate = base / "frontend" / "dist"
    return candidate if (candidate / "index.html").exists() else None


def create_app(
    settings: SettingsManager,
    download_manager: DownloadManager,
    media_manager: MediaJobManager | None = None,
) -> FastAPI:
    app = FastAPI(title="YouTube Downloader API")
    app.add_middleware(
        CORSMiddleware,
        # API слушает только на loopback (127.0.0.1) — источник запроса не имеет значения
        # для безопасности, а фронтенд грузится то с dev-сервера (http://localhost:5173),
        # то из локального файла (file://, origin "null") после сборки.
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.loop = None
    app.state.clients: set[WebSocket] = set()
    app.state.broadcast_queue: asyncio.Queue = asyncio.Queue()
    app.state.analyze_pool = ThreadPoolExecutor(
        max_workers=ANALYZE_WORKERS, thread_name_prefix="analyze"
    )
    app.state.summary_pool = ThreadPoolExecutor(
        max_workers=SUMMARY_WORKERS, thread_name_prefix="summary"
    )
    app.state.analyze_cache: dict[str, tuple[float, dict]] = {}
    app.state.analyze_inflight: dict[str, asyncio.Future] = {}
    # Разбор плейлиста/канала — тот же дорогой поход в YouTube, что и analyze,
    # и делит с ним пул: параллельно с уже идущим разбором его всё равно не ускорить.
    app.state.playlist_cache: dict[str, tuple[float, dict]] = {}
    app.state.media = media_manager if media_manager is not None else MediaJobManager(settings)

    def emit_event(event: dict) -> None:
        """Thread-safe мост: вызывается из потока DownloadManager (Qt-сигналы),
        безопасно перекладывает событие в asyncio-очередь потока сервера."""
        loop = app.state.loop
        if loop is None:
            return
        try:
            loop.call_soon_threadsafe(app.state.broadcast_queue.put_nowait, event)
        except RuntimeError:
            # Луп уже закрыт (приложение завершается) — событие никому не нужно.
            pass

    # DirectConnection обязателен: приёмники — обычные функции/лямбды без QObject-принадлежности,
    # а DownloadManager теперь эмитит сигналы из фоновых worker-потоков (concurrent_downloads),
    # а не только из своего QThread. Без явного типа PyQt может выбрать QueuedConnection к
    # прокси-объекту в главном потоке и тихо потерять доставку, если тот не успевает её выкачать.
    direct = Qt.ConnectionType.DirectConnection

    download_manager.progress_changed.connect(
        lambda item_id, percent, speed: emit_event(
            {"type": "progress", "id": item_id, "percent": percent, "speed": speed}
        ),
        direct,
    )
    download_manager.status_changed.connect(
        lambda item_id, status: emit_event({"type": "status", "id": item_id, "status": status}),
        direct,
    )
    download_manager.log_message.connect(
        lambda level, text: emit_event({"type": "log", "level": level, "text": text}),
        direct,
    )
    download_manager.error_occurred.connect(
        lambda item_id, code, message: emit_event(
            {
                "type": "error",
                "id": item_id,
                "code": ERROR_CODE_MAP.get(code, "UNKNOWN_ERROR"),
                "message": message,
            }
        ),
        direct,
    )

    def _on_item_finished(item_id: str, meta: dict) -> None:
        settings.add_history_entry(meta)
        emit_event({"type": "finished", "id": item_id, "meta": meta})

    download_manager.item_finished.connect(_on_item_finished, direct)

    # MediaJobManager не на Qt-сигналах — ему достаточно одного callback'а наружу
    # (см. core/media_jobs.py). Событие уходит в тот же WebSocket, что и загрузки.
    app.state.media.on_event = emit_event

    @app.on_event("startup")
    async def _startup() -> None:
        app.state.loop = asyncio.get_running_loop()
        asyncio.create_task(_broadcast_worker())

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        app.state.analyze_pool.shutdown(wait=False, cancel_futures=True)
        app.state.summary_pool.shutdown(wait=False, cancel_futures=True)
        app.state.media.shutdown()

    async def _broadcast_worker() -> None:
        while True:
            event = await app.state.broadcast_queue.get()
            dead = []
            for ws in list(app.state.clients):
                try:
                    await ws.send_json(event)
                except Exception:  # noqa: BLE001
                    dead.append(ws)
            for ws in dead:
                app.state.clients.discard(ws)

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        app.state.clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()  # клиент не шлёт данные, держим соединение живым
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001 — обрыв сокета не должен ронять сервер
            pass
        finally:
            app.state.clients.discard(websocket)

    # --- анализ ссылки ---

    def _analyze_blocking(url: str, link_type: str) -> dict:
        # noplaylist=False только для ссылок, которые сами по себе являются списком
        # (плейлист или канал) — иначе yt-dlp уходит качать весь микс из ссылки вида
        # watch?v=...&list=RD... вместо одного видео.
        return VideoInfo.fetch(url, noplaylist=link_type not in BATCH_LINK_TYPES, settings=settings)

    @app.post("/api/analyze")
    async def analyze(req: AnalyzeRequest):
        url = req.url.strip()
        link_type = detect_link_type(url)
        if link_type == LinkType.INVALID:
            raise HTTPException(400, detail={"code": "INVALID_URL", "message": "Ссылка некорректна"})

        cached = app.state.analyze_cache.get(url)
        if cached and time.monotonic() - cached[0] < ANALYZE_CACHE_TTL:
            return cached[1]

        # Дедупликация: пока один разбор этого URL идёт, все остальные запросы на него
        # ждут ТОТ ЖЕ результат, а не запускают ещё один поход в YouTube. Без этого
        # достаточно было пары лишних ре-рендеров на фронтенде, чтобы получить очередь
        # одинаковых 20-секундных запросов и антибот-блокировку в довесок.
        inflight = app.state.analyze_inflight.get(url)
        if inflight is None:
            loop = asyncio.get_running_loop()
            inflight = loop.run_in_executor(app.state.analyze_pool, _analyze_blocking, url, link_type)
            app.state.analyze_inflight[url] = inflight
            owner = True
        else:
            owner = False

        try:
            info = await asyncio.shield(inflight)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, detail={"code": "VIDEO_UNAVAILABLE", "message": str(exc)})
        finally:
            if owner:
                app.state.analyze_inflight.pop(url, None)

        app.state.analyze_cache[url] = (time.monotonic(), info)
        if len(app.state.analyze_cache) > 100:
            oldest = min(app.state.analyze_cache, key=lambda k: app.state.analyze_cache[k][0])
            app.state.analyze_cache.pop(oldest, None)
        return info

    # --- саммери по видео ---

    @app.post("/api/summary")
    async def summary(req: SummaryRequest):
        url = req.url.strip()
        if detect_link_type(url) == LinkType.INVALID:
            raise HTTPException(400, detail={"code": "INVALID_URL", "message": "Ссылка некорректна"})
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                app.state.summary_pool,
                lambda: build_summary(url, settings=settings, title=req.title, duration=req.duration),
            )
        except TranscriptUnavailable as exc:
            raise HTTPException(422, detail={"code": "NO_TRANSCRIPT", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Саммери не построено")
            raise HTTPException(500, detail={"code": "SUMMARY_FAILED", "message": str(exc)})

    # --- список видео плейлиста/канала (пакетная загрузка) ---

    @app.post("/api/playlist")
    async def playlist(req: PlaylistRequest):
        url = req.url.strip()
        link_type = detect_link_type(url)
        if link_type == LinkType.INVALID:
            raise HTTPException(400, detail={"code": "INVALID_URL", "message": "Ссылка некорректна"})
        if link_type not in BATCH_LINK_TYPES:
            raise HTTPException(
                400,
                detail={"code": "INVALID_URL", "message": "Это ссылка на одно видео, а не на список"},
            )

        cache_key = f"{url}|{req.limit}"
        cached = app.state.playlist_cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < ANALYZE_CACHE_TTL:
            return cached[1]

        loop = asyncio.get_running_loop()
        try:
            data = await loop.run_in_executor(
                app.state.analyze_pool,
                lambda: fetch_playlist_entries(url, settings=settings, limit=max(1, min(500, req.limit))),
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(422, detail={"code": "VIDEO_UNAVAILABLE", "message": str(exc)})

        app.state.playlist_cache[cache_key] = (time.monotonic(), data)
        if len(app.state.playlist_cache) > 20:
            oldest = min(app.state.playlist_cache, key=lambda k: app.state.playlist_cache[k][0])
            app.state.playlist_cache.pop(oldest, None)
        return data

    # --- очередь ---

    def _queue_row(index: int, item: QueueItem) -> dict:
        return {
            "id": item.id,
            "url": item.url,
            "title": item.title,
            "status": item.status,
            "position": index,
            "quality": item.quality,
            "audio_only": item.audio_only,
            "is_playlist": item.is_playlist,
            "neuro_dub_ru": item.neuro_dub_ru,
        }

    @app.get("/api/queue")
    async def get_queue():
        return [_queue_row(n, i) for n, i in enumerate(download_manager.get_queue_snapshot())]

    def _enqueue(req: QueueItemRequest) -> dict:
        data = req.model_dump()
        if not data.get("output_folder"):
            # Фронтенд не шлёт output_folder на каждую загрузку — папка по умолчанию
            # берётся из настроек, а не из os.getcwd() (рабочей директории приложения).
            data["output_folder"] = settings.ensure_download_folder()
        item = QueueItem(**data)
        download_manager.add_to_queue(item)
        return {"id": item.id, "url": item.url, "title": item.title, "status": item.status}

    @app.post("/api/queue")
    async def add_to_queue(req: QueueItemRequest):
        return _enqueue(req)

    @app.post("/api/queue/batch")
    async def add_batch(req: BatchQueueRequest):
        """Пакетная постановка выбранных видео плейлиста/канала.

        Каждое видео становится ОТДЕЛЬНОЙ задачей, а не одной задачей «скачай плейлист»:
        так работают пауза, отмена и повтор для конкретного ролика, а падение одного
        видео (приватное, удалённое, с региональной блокировкой) не роняет весь пакет.
        """
        if not req.items:
            raise HTTPException(400, detail={"code": "INVALID_URL", "message": "Список пуст"})
        if len(req.items) > 500:
            raise HTTPException(400, detail={"code": "INVALID_URL", "message": "Не больше 500 за раз"})
        return [_enqueue(item) for item in req.items]

    @app.post("/api/queue/pause_all")
    async def pause_all():
        return {"ok": True, "affected": download_manager.pause_all()}

    @app.post("/api/queue/resume_all")
    async def resume_all():
        return {"ok": True, "affected": download_manager.resume_all()}

    @app.delete("/api/queue")
    async def clear_queue():
        """Убирает всё, что ещё не начало качаться. Активные загрузки не трогает."""
        return {"ok": True, "removed": download_manager.clear_pending()}

    @app.post("/api/queue/{item_id}/pause")
    async def pause_item(item_id: str):
        # Пауза работает и для ожидающей задачи: «поставить очередь на паузу» иначе
        # невозможно — остановишь текущую, и тут же стартует следующая.
        if not download_manager.pause_item(item_id):
            raise HTTPException(409, "Эту задачу нельзя поставить на паузу")
        return {"ok": True}

    @app.post("/api/queue/{item_id}/resume")
    async def resume_item(item_id: str):
        if not download_manager.resume_item(item_id):
            raise HTTPException(409, "Эта задача не на паузе")
        return {"ok": True}

    @app.post("/api/queue/{item_id}/move")
    async def move_item(item_id: str, req: QueueMoveRequest):
        if not download_manager.move_item(item_id, req.delta):
            raise HTTPException(409, "Эту задачу нельзя переместить")
        return {"ok": True, "queue": [_queue_row(n, i) for n, i in enumerate(download_manager.get_queue_snapshot())]}

    @app.post("/api/queue/{item_id}/cancel")
    async def cancel_item(item_id: str):
        if item_id in download_manager.get_active_item_ids():
            download_manager.cancel_current(item_id)
        else:
            download_manager.remove_from_queue(item_id)
        return {"ok": True}

    @app.delete("/api/queue/{item_id}")
    async def remove_item(item_id: str):
        download_manager.remove_from_queue(item_id)
        return {"ok": True}

    # --- история ---

    @app.get("/api/history")
    async def get_history():
        return settings.get_history()

    @app.delete("/api/history")
    async def clear_history():
        settings.clear_history()
        return {"ok": True}

    # --- настройки ---

    @app.get("/api/settings")
    async def get_settings():
        return settings.public_settings()

    @app.post("/api/settings")
    async def update_settings(req: SettingsUpdateRequest):
        for key, value in req.model_dump(exclude_none=True).items():
            settings.set(key, value)
        return settings.public_settings()

    @app.post("/api/settings/folder")
    async def choose_folder(req: FolderPickRequest):
        """Открывает нативный диалог выбора папки и сохраняет результат в настройки."""
        from ui import dialogs

        loop = asyncio.get_running_loop()
        start = req.start or settings.get("download_folder", "")
        # Диалог блокирует свой поток на всё время, пока открыт — держим его подальше
        # от event loop, иначе на время выбора папки встанет весь остальной API.
        path = await loop.run_in_executor(None, dialogs.pick_folder, start)
        if not path:
            return {"ok": False, "download_folder": settings.get("download_folder", "")}
        settings.set("download_folder", path)
        return {"ok": True, "download_folder": path}

    @app.post("/api/reveal")
    async def reveal(req: RevealRequest):
        from ui import dialogs

        target = req.path or settings.get("download_folder", "")
        return {"ok": dialogs.reveal(target)}

    # --- локальный конвертер/редактор (ffmpeg) ---

    @app.get("/api/media/capabilities")
    async def media_capabilities():
        """Контейнеры и кодеки, доступные на ЭТОЙ машине. Единственный источник правды:
        списки зависят от сборки ffmpeg, и хардкодить их во фронтенде значит обещать
        пользователю кодек, которого у него нет."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, media_tools.capabilities)

    @app.post("/api/media/pick")
    async def media_pick(req: FilePickRequest):
        """Нативный выбор файлов. Браузерный <input type=file> отдаёт File без пути
        на диске, а ffmpeg работает именно с путём."""
        from ui import dialogs

        loop = asyncio.get_running_loop()
        paths = await loop.run_in_executor(
            None,
            lambda: dialogs.pick_files(
                start=req.start or settings.get("download_folder", ""),
                multiple=req.multiple,
                audio_only=req.audio_only,
                title=req.title,
            ),
        )
        return {"paths": paths}

    @app.post("/api/media/probe")
    async def media_probe(req: ProbeRequest):
        loop = asyncio.get_running_loop()
        try:
            info = await loop.run_in_executor(app.state.summary_pool, media_tools.probe, req.path)
        except FFmpegMissing as exc:
            raise HTTPException(422, detail={"code": "FFMPEG_MISSING", "message": str(exc)})
        except MediaError as exc:
            raise HTTPException(422, detail={"code": "MEDIA_FAILED", "message": str(exc)})
        return info.to_dict()

    @app.get("/api/media/jobs")
    async def media_jobs():
        return app.state.media.snapshot()

    @app.post("/api/media/jobs")
    async def media_submit(req: MediaJobRequest):
        params = req.model_dump(exclude={"kind", "source"}, exclude_none=True)
        # Пустая строка в container/audio_source значит «не задано» — если её пропустить
        # дальше, plan_* примет её за явный выбор и упадёт на «Неизвестный контейнер: ».
        params = {k: v for k, v in params.items() if v != ""}
        try:
            job = app.state.media.submit(req.kind, req.source, params)
        except FFmpegMissing as exc:
            raise HTTPException(422, detail={"code": "FFMPEG_MISSING", "message": str(exc)})
        except MediaError as exc:
            raise HTTPException(422, detail={"code": "MEDIA_FAILED", "message": str(exc)})
        return job.to_dict()

    @app.post("/api/media/jobs/{job_id}/cancel")
    async def media_cancel(job_id: str):
        if not app.state.media.cancel(job_id):
            raise HTTPException(409, "Задача уже завершена")
        return {"ok": True}

    @app.delete("/api/media/jobs")
    async def media_clear():
        return {"ok": True, "removed": app.state.media.clear_finished()}

    # --- диагностика / yt-dlp ---

    @app.get("/api/diagnostics")
    async def diagnostics():
        return {
            "ytdlp_version": YTDLP_VERSION,
            "ffmpeg_installed": find_ffmpeg() is not None,
            "frozen": bool(getattr(sys, "frozen", False)),
            "summary_api_key_set": bool(str(settings.get("summary_api_key", "")).strip()),
            "video_encoders": media_tools.supported_video_codecs(),
            "audio_encoders": media_tools.supported_audio_codecs(),
        }

    @app.post("/api/ytdlp/update")
    async def update_ytdlp():
        if getattr(sys, "frozen", False):
            # В собранном EXE sys.executable — это сам NeoLoader.exe, у него нет `-m pip`.
            # Раньше кнопка в этом случае молча возвращала 500 из CalledProcessError.
            raise HTTPException(
                400,
                detail={
                    "code": "UNSUPPORTED",
                    "message": "В собранной версии yt-dlp обновляется вместе с приложением",
                },
            )
        loop = asyncio.get_running_loop()

        def _pip_update() -> str:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"])
            out = subprocess.run(
                [sys.executable, "-c", "import yt_dlp;print(yt_dlp.version.__version__)"],
                capture_output=True,
                text=True,
            )
            return out.stdout.strip() or YTDLP_VERSION

        try:
            version = await loop.run_in_executor(None, _pip_update)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(500, detail={"code": "UPDATE_FAILED", "message": str(exc)})
        # Новая версия подхватится после перезапуска — модуль уже импортирован в этот процесс.
        return {"ok": True, "version": version, "restart_required": version != YTDLP_VERSION}

    # --- статика фронтенда ---
    #
    # Монтируется ПОСЛЕДНЕЙ: Starlette выбирает маршрут по порядку, и mount на "/"
    # перехватил бы /api/* и /ws, если бы стоял выше.
    #
    # Зачем вообще отдавать фронтенд через свой же uvicorn, а не грузить index.html
    # из файла: страница, открытая как file://, в QtWebEngine НЕ МОЖЕТ делать fetch на
    # http://127.0.0.1 — атрибут LocalContentCanAccessRemoteUrls выключен по умолчанию.
    # Ровно поэтому сборка вела себя так: из браузера (http://) всё работало, а в самом
    # окне приложения любой запрос молча падал и интерфейс писал «фоновая служба не
    # запущена», хотя служба была жива и слушала порт. Отдача статики с того же
    # origin убирает и это ограничение, и CORS, и передачу порта во фронтенд.
    dist = frontend_dist_dir()
    if dist is not None:
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
    else:
        logger.warning("frontend/dist не найден — окно откроет dev-сервер Vite")

    return app
