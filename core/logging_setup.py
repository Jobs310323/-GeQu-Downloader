"""Логирование в файл с ротацией.

В собранном EXE (console=False, см. build.spec) весь stdout/stderr уходит в никуда —
до этого момента структурированные логи DownloadManager (TASK_CREATED/DOWNLOAD_STARTED/...)
существовали только пока окно открыто, и расследовать жалобу "у меня не скачалось"
постфактум было нечем. Теперь они дополнительно пишутся в файл на диске."""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5


def log_dir() -> Path:
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA") or str(Path.home())
        base = Path(appdata) / "NeoLoader"
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "logs"


def configure_logging(debug: bool = False) -> Path:
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "app.log"

    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))

    level = logging.DEBUG if debug else logging.INFO

    # Общий родитель всех логгеров приложения. Раньше файловый handler вешался
    # ТОЛЬКО на "neoloader.download" и "neoloader.main", поэтому всё, что писали
    # "neoloader.window", "neoloader.api", "neoloader.summary" и "neoloader.dialogs",
    # пропадало бесследно. Из-за этого, в частности, не было видно вывода console.*
    # со страницы (ui/web_window.py::_LoggingPage) — единственного окна в то, что
    # происходит внутри React в собранном приложении, где devtools нет.
    root_logger = logging.getLogger("neoloader")
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
    root_logger.propagate = False

    # core/download_manager.py уже настраивает "neoloader.download" со своим
    # StreamHandler(propagate=False) для консоли при запуске из исходников — цепляем
    # файловый handler туда же напрямую, а не на родителя, иначе propagate=False его
    # никогда не увидит.
    download_logger = logging.getLogger("neoloader.download")
    download_logger.addHandler(handler)
    download_logger.setLevel(level)

    main_logger = logging.getLogger("neoloader.main")
    main_logger.setLevel(level)

    # console=False в build.spec — окно консоли нет, любое неотловленное исключение
    # в главном потоке раньше просто тихо валило процесс без единого следа: ни трея,
    # ни диалога, ни строки в логе. Теперь оно хотя бы долетает до app.log перед выходом.
    def _log_uncaught(exc_type, exc_value, exc_tb) -> None:
        main_logger.critical("Необработанное исключение", exc_info=(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_uncaught

    return directory
