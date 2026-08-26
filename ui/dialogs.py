"""Мост «фоновый HTTP-поток -> нативный Qt-диалог в главном потоке».

Кнопка «выбрать папку загрузок» в React вызывает обычный HTTP-эндпоинт, а он живёт
в потоке uvicorn. Открыть QFileDialog прямо оттуда нельзя: любые виджеты Qt создаются
и показываются ТОЛЬКО в GUI-потоке, иначе процесс падает без внятного сообщения.
Поэтому запрос уезжает в главный поток через сигнал (AutoConnection из другого потока
= QueuedConnection), а вызывающая сторона ждёт threading.Event с таймаутом.

Раньше эндпоинта не было вовсе: путь к папке загрузок показывался в настройках
как нередактируемый текст, то есть «настройки» в этой части были декорацией.
"""

import logging
import os
import subprocess
import sys
import threading

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QFileDialog

logger = logging.getLogger("neoloader.dialogs")

DIALOG_TIMEOUT_SECONDS = 300


class _DialogBridge(QObject):
    folder_requested = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.parent_window = None
        self.folder_requested.connect(self._open_folder_dialog)

    def _open_folder_dialog(self, box: dict) -> None:
        try:
            # Родитель обязателен: без него модальный диалог может открыться ПОЗАДИ
            # главного окна, и приложение выглядит зависшим — окно не отвечает
            # (ждёт закрытия диалога), а самого диалога не видно.
            box["path"] = (
                QFileDialog.getExistingDirectory(
                    self.parent_window, "Папка для загрузок", box.get("start") or ""
                )
                or ""
            )
        except Exception:  # noqa: BLE001 — диалог не должен ронять приложение
            logger.exception("Не удалось открыть диалог выбора папки")
            box["path"] = ""
        finally:
            box["event"].set()


_bridge: _DialogBridge | None = None


def install() -> None:
    """Создаётся в главном потоке (из main.py, после QApplication)."""
    global _bridge
    _bridge = _DialogBridge()


def set_parent_window(window) -> None:
    """Окно-родитель для модальных диалогов. Вызывается после создания окна."""
    if _bridge is not None:
        _bridge.parent_window = window


def pick_folder(start: str = "") -> str:
    """Блокирует вызывающий поток, пока пользователь не закроет диалог.
    Возвращает "" если диалог недоступен, отменён или не ответил за таймаут."""
    if _bridge is None:
        return ""
    box: dict = {"start": start, "path": "", "event": threading.Event()}
    _bridge.folder_requested.emit(box)
    if not box["event"].wait(timeout=DIALOG_TIMEOUT_SECONDS):
        logger.warning("Диалог выбора папки не ответил за %s с", DIALOG_TIMEOUT_SECONDS)
        return ""
    return box["path"]


def reveal(path: str) -> bool:
    """Показывает файл (или папку) в проводнике. Работает из любого потока —
    ничего от Qt тут не нужно."""
    if not path or not os.path.exists(path):
        return False
    try:
        if sys.platform == "win32":
            if os.path.isdir(path):
                os.startfile(path)  # noqa: S606
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if os.path.isfile(path) else "", path])
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось открыть проводник для %s", path)
        return False
