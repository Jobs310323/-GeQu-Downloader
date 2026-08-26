"""Главное окно нового UI: один QWebEngineView, хостящий React-фронтенд (NeoLoader)."""

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QMainWindow

logger = logging.getLogger("neoloader.window")

DEV_SERVER_URL = "http://localhost:5173"
DEFAULT_API_PORT = 8756


def _app_base_dir() -> Path:
    """Из PyInstaller-сборки ресурсы (frontend/dist) лежат в sys._MEIPASS
    (папке распаковки), а не рядом с этим файлом."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def _frontend_dist_path() -> Path:
    return _app_base_dir() / "frontend" / "dist" / "index.html"


class _LoggingPage(QWebEnginePage):
    """Пробрасывает console.* и ошибки страницы в app.log.

    В windowed-сборке у QWebEngineView нет devtools и нет консоли, поэтому любая
    ошибка внутри React раньше была абсолютно невидимой — «просто ничего не работает».
    Фронтенд специально печатает в консоль факт успешного/неуспешного соединения
    с бэкендом (см. SettingsContext), чтобы это состояние было видно в app.log.
    """

    def javaScriptConsoleMessage(self, level, message, line, source_id):  # noqa: N802
        logger.info("[web] %s (%s:%s)", message, source_id, line)


class WebMainWindow(QMainWindow):
    """Окно-хост: PyQt отвечает только за нативное окно и WebEngine, весь UI — в React.

    Закрытие окна (крестик) сворачивает приложение в трей, а не завершает процесс —
    активные загрузки продолжаются в фоне. Полный выход — только через пункт "Выход"
    в меню трея (см. ui/tray.py), который сам явно вызывает close_for_real()."""

    def __init__(self, api_port: int = DEFAULT_API_PORT) -> None:
        super().__init__()
        self.setWindowTitle("NeoLoader")
        self.resize(1280, 800)
        self._allow_close = False
        self._api_port = api_port

        self.view = QWebEngineView()
        self.view.setPage(_LoggingPage(self.view))
        self.setCentralWidget(self.view)

        # Страховка на случай, если страница всё-таки откроется как file:// (например
        # бэкенд не поднялся и статику отдавать некому). По умолчанию QtWebEngine
        # ЗАПРЕЩАЕТ локальной странице обращаться к http:// — именно поэтому раньше
        # из браузера всё работало, а в окне приложения каждый fetch молча падал и
        # интерфейс писал «фоновая служба не запущена» при живой службе.
        web_settings = self.view.settings()
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        web_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)

        self.view.load(QUrl(self._start_url()))

    def _start_url(self) -> str:
        """Основной путь — страница с того же origin, что и API (её отдаёт uvicorn,
        см. api/server.py). Тогда никаких file://, CORS и передачи порта не нужно:
        фронтенд обращается к API относительными адресами того же origin."""
        base = f"http://127.0.0.1:{self._api_port}"
        if _frontend_dist_path().exists():
            logger.info("Открываю собранный фронтенд с %s", base)
            return base + "/"
        logger.warning("frontend/dist не найден — открываю dev-сервер Vite")
        return f"{DEV_SERVER_URL}/?api={self._api_port}"

    def reload_page(self) -> None:
        self.view.load(QUrl(self._start_url()))

    def close_for_real(self) -> None:
        self._allow_close = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            event.accept()
            return
        event.ignore()
        self.hide()
