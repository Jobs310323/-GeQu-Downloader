"""Иконка приложения в системном трее.

Даёт то, ради чего запаковали GUI в один EXE: пользователю не нужен отдельный
main.py/консоль/localhost — приложение живёт в трее, правый клик по иконке
показывает текущий статус (сколько качается/в очереди) прямо в меню без открытия
окна, левый/двойной клик открывает окно, "Выход" завершает процесс по-настоящему
(закрытие окна крестиком только прячет его — см. WebMainWindow.closeEvent)."""

from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.download_manager import DownloadManager
from ui.web_window import WebMainWindow

STATUS_REFRESH_MS = 3000


class TrayIcon(QSystemTrayIcon):
    def __init__(
        self,
        icon: QIcon,
        window: WebMainWindow,
        download_manager: DownloadManager,
        log_directory: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(icon, parent)
        self._window = window
        self._download_manager = download_manager
        self._log_directory = log_directory

        self._menu = QMenu()

        self._status_action = QAction("Нет активных загрузок")
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)
        self._menu.addSeparator()

        # QAction без сохранённой Python-ссылки может быть собран GC даже после
        # addAction() (PyQt держит владение через C++-parent, но не всегда надёжно
        # в связке с onefile-сборкой) — держим все три как атрибуты self.
        self._open_action = QAction("Открыть NeoLoader")
        self._open_action.triggered.connect(self.show_window)
        self._menu.addAction(self._open_action)

        self._logs_action: QAction | None = None
        if self._log_directory is not None:
            self._logs_action = QAction("Открыть папку логов")
            self._logs_action.triggered.connect(self._open_logs)
            self._menu.addAction(self._logs_action)

        self._quit_action = QAction("Выход")
        self._quit_action.triggered.connect(self._quit)
        self._menu.addAction(self._quit_action)

        self.setContextMenu(self._menu)
        self._menu.aboutToShow.connect(self._refresh_status)
        self.activated.connect(self._on_activated)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_status)
        self._timer.start(STATUS_REFRESH_MS)
        self._refresh_status()

    def _refresh_status(self) -> None:
        active = len(self._download_manager.get_active_item_ids())
        total = len(self._download_manager.get_queue_snapshot())
        queued = max(0, total - active)

        if active and queued:
            text = f"Качается: {active}, в очереди: {queued}"
        elif active:
            text = f"Качается: {active}"
        elif queued:
            text = f"В очереди: {queued}"
        else:
            text = "Нет активных загрузок"

        self._status_action.setText(text)
        self.setToolTip(f"NeoLoader — {text}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_window()

    def show_window(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()

    def _open_logs(self) -> None:
        if self._log_directory is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._log_directory)))

    def _quit(self) -> None:
        # DownloadManager — QThread с собственным циклом while (см. run()); Qt не убивает
        # такие потоки сам при QApplication.quit(), и интерпретатор при выходе может зависнуть
        # в ожидании, пока поток не завершится сам по себе. stop()+wait() гарантируют, что
        # процесс реально исчезнет из диспетчера задач, а не останется висеть после "Выход".
        self._download_manager.stop()
        self._download_manager.wait(2000)
        self._window.close_for_real()
        QApplication.quit()
