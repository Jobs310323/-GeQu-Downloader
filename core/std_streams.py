"""Гарантирует, что sys.stdout/sys.stderr — это НАСТОЯЩИЕ файловые объекты.

Зачем это отдельный модуль и почему он вызывается первой строкой в main.py:

PyInstaller с `console=False` (см. build.spec) запускает процесс вообще без
консоли, и Python в таком режиме выставляет `sys.stdout` и `sys.stderr` в `None`.
Любая библиотека, которая просто трогает поток, падает — не пишет в никуда,
а именно падает с AttributeError. Реальный случай, из-за которого приложение
было полностью нерабочим в собранном виде:

    File "uvicorn/logging.py", line 42, in __init__
    AttributeError: 'NoneType' object has no attribute 'isatty'
    ValueError: Unable to configure formatter 'default'

uvicorn.Config() при создании настраивает своё цветное логирование и спрашивает
у stdout `isatty()`. Исключение убивало поток с API целиком: порт 8756 никто не
слушал, окно открывалось пустым, а весь интерфейс отвечал «Can't reach the app's
background service». Из исходников (`python main.py`) этого не видно НИКОГДА —
там stdout настоящий. Не видно и при запуске EXE с перенаправлением
(`NeoLoader.exe > log.txt`) — перенаправление само создаёт валидный поток.
Воспроизводится только двойным кликом, то есть ровно так, как запускает пользователь.

Поэтому потоки подменяются здесь, до импорта uvicorn и чего угодно ещё:
stdout уходит в devnull, stderr — в файл рядом с app.log, чтобы вывод из C-уровня
и сторонних библиотек (который не проходит через logging) не терялся насовсем.
"""

import os
import sys
from pathlib import Path

STDERR_FILENAME = "stderr.log"
MAX_STDERR_BYTES = 2 * 1024 * 1024


def _open_devnull():
    return open(os.devnull, "w", encoding="utf-8", errors="replace")


def _open_stderr_log(directory: Path):
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / STDERR_FILENAME
        # Простейшая ротация: файл нужен только для посмертного разбора, история не важна.
        if path.exists() and path.stat().st_size > MAX_STDERR_BYTES:
            path.unlink()
        return open(path, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return _open_devnull()


def ensure_std_streams(log_directory: Path | None = None) -> None:
    """Идемпотентно заменяет None-потоки на настоящие файловые объекты."""
    if sys.stdout is None:
        stream = _open_devnull()
        sys.stdout = stream
        sys.__stdout__ = stream
    if sys.stderr is None:
        stream = _open_stderr_log(log_directory) if log_directory else _open_devnull()
        sys.stderr = stream
        sys.__stderr__ = stream
    if sys.stdin is None:
        # Некоторые библиотеки (в т.ч. пути внутри yt-dlp) проверяют stdin перед
        # интерактивным вводом; None здесь тоже приводит к AttributeError.
        try:
            sys.stdin = open(os.devnull, "r", encoding="utf-8")
            sys.__stdin__ = sys.stdin
        except OSError:
            pass
