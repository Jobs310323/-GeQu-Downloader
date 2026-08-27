"""Точка входа: инициализация QApplication, фонового API-сервера и главного окна.

Запускает React-интерфейс (NeoLoader) внутри QWebEngineView. Старый чисто-виджетный
UI (ui/main_window.py, ui/widgets.py) заархивирован — файлы остались в репозитории,
но main.py их больше не подключает; флаг --legacy сохранён только как понятная
заглушка на случай, если кто-то по привычке его передаст.
"""

# ВАЖНО: до любых других импортов. В windowed-сборке sys.stdout/sys.stderr равны None,
# и uvicorn.Config() падает на sys.stdout.isatty() ещё до того, как что-то успеет
# залогироваться. Подробности — в core/std_streams.py.
from core.std_streams import ensure_std_streams  # isort:skip

ensure_std_streams()  # isort:skip

import logging  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import uvicorn  # noqa: E402
from PyQt6.QtGui import QIcon  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from api.server import create_app  # noqa: E402
from core.download_manager import DownloadManager  # noqa: E402
from core.logging_setup import configure_logging, log_dir  # noqa: E402
from core.media_jobs import MediaJobManager  # noqa: E402
from core.settings_manager import SettingsManager  # noqa: E402
from ui.single_instance import SingleInstanceServer, try_acquire  # noqa: E402

logger = logging.getLogger("neoloader.main")

API_HOST = "127.0.0.1"
API_PORT = 8756
# Если 8756 занят чем-то посторонним (зависший прошлый процесс, другая программа),
# раньше поток API просто падал и окно открывалось мёртвым. Теперь пробуем соседние
# порты и сообщаем выбранный фронтенду через query-параметр (см. ui/web_window.py).
API_PORT_CANDIDATES = tuple(range(API_PORT, API_PORT + 10))
API_STARTUP_TIMEOUT = 30
API_MAX_RESTARTS = 3


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def _load_app_icon() -> QIcon:
    icon_path = _app_base_dir() / "assets" / "icon.ico"
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # SO_REUSEADDR намеренно НЕ ставим: нужно узнать, сможет ли забиндиться uvicorn,
        # а не то, разрешит ли ядро разделить порт.
        try:
            sock.bind((API_HOST, port))
            return True
        except OSError:
            return False


def _pick_port() -> int:
    for port in API_PORT_CANDIDATES:
        if _port_is_free(port):
            return port
    return API_PORT  # все заняты — пусть падает штатно и напишет причину в лог


class ApiSupervisor:
    """Держит uvicorn живым в фоновом потоке и перезапускает его, если он упал.

    Раньше это был обычный daemon-поток без присмотра: одно исключение при старте
    (например uvicorn.Config на None-stdout) — и бэкенда нет до перезапуска всего
    приложения, причём снаружи это выглядит просто как «ничего не работает».
    """

    def __init__(
        self,
        settings: SettingsManager,
        download_manager: DownloadManager,
        media_manager: MediaJobManager,
    ) -> None:
        self._settings = settings
        self._download_manager = download_manager
        # Менеджер ffmpeg-задач живёт ДОЛЬШЕ приложения FastAPI: при перезапуске
        # uvicorn создаётся новый app, и если бы очередь конвертаций принадлежала ему,
        # она бы обнулялась вместе с ним — прямо посреди часового перекодирования.
        self._media_manager = media_manager
        self._ready = threading.Event()
        self._stopped = False
        self.port = API_PORT
        self.last_error: str = ""
        self._server: uvicorn.Server | None = None

    def start(self) -> None:
        threading.Thread(target=self._run_forever, name="api-supervisor", daemon=True).start()

    def wait_ready(self, timeout: float) -> bool:
        return self._ready.wait(timeout=timeout)

    def stop(self) -> None:
        self._stopped = True
        if self._server is not None:
            self._server.should_exit = True

    def _run_forever(self) -> None:
        for attempt in range(API_MAX_RESTARTS + 1):
            if self._stopped:
                return
            try:
                self._serve_once()
            except BaseException as exc:  # noqa: BLE001 — uvicorn зовёт sys.exit(); это SystemExit
                self.last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("API-поток упал (попытка %s)", attempt + 1)
            else:
                self.last_error = "сервер завершился сам"
                logger.warning("API-сервер завершился без исключения (попытка %s)", attempt + 1)
            if self._stopped:
                return
            self._ready.clear()
            time.sleep(1.0)
        logger.error("API не удалось поднять после %s попыток: %s", API_MAX_RESTARTS + 1, self.last_error)

    def _serve_once(self) -> None:
        self.port = _pick_port()
        app = create_app(self._settings, self._download_manager, self._media_manager)

        @app.on_event("startup")
        async def _signal_ready() -> None:  # noqa: ANN202
            self._ready.set()

        config = uvicorn.Config(
            app,
            host=API_HOST,
            port=self.port,
            # log_config=None обязателен: дефолтный конфиг uvicorn строит
            # ColourizedFormatter, который в конструкторе зовёт sys.stdout.isatty().
            # Даже с подменёнными потоками не нужен — своё логирование у нас уже есть.
            log_config=None,
            access_log=False,
        )
        server = uvicorn.Server(config)
        self._server = server
        logger.info("Стартую API на %s:%s", API_HOST, self.port)
        server.run()


def _show_backend_failure(directory: Path, reason: str) -> None:
    """Явно говорим, что бэкенд не поднялся, вместо безмолвно мёртвого окна."""
    box = QMessageBox()
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle("NeoLoader")
    box.setText("Фоновая служба приложения не запустилась.")
    box.setInformativeText(
        "Интерфейс откроется, но скачивание и настройки работать не будут.\n\n"
        f"Причина: {reason or 'неизвестна'}\n\n"
        f"Подробности: {directory / 'app.log'}"
    )
    box.exec()


def main() -> None:
    if "--legacy" in sys.argv:
        print(
            "Legacy UI (ui/main_window.py) заархивирован и больше не подключается "
            "из main.py. Запусти без --legacy — основной интерфейс (NeoLoader/React) "
            "теперь единственный поддерживаемый."
        )
        return

    # QtWebEngineWidgets обязан импортироваться до создания QApplication/QCoreApplication —
    # иначе PyQt бросает RuntimeError уже при создании QApplication.
    from ui.web_window import WebMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("NeoLoader")
    app.setWindowIcon(_load_app_icon())

    # QLocalSocket/QLocalServer нужен живой QCoreApplication, чтобы вообще что-то
    # отправить/принять (без него connectToServer молча не находит существующий сервер) —
    # поэтому проверка "уже запущен другой экземпляр" идёт после создания QApplication,
    # а не до, иначе двойной клик по EXE при уже открытом приложении просто открывал
    # бы второе окно и второй uvicorn на том же порту.
    if not try_acquire():
        # Уже запущен другой экземпляр — он получил сигнал "show" и сам поднимет окно.
        return

    app.setQuitOnLastWindowClosed(False)  # окно прячется в трей, а не завершает процесс

    log_directory = configure_logging(debug="--debug" in sys.argv)
    # Теперь, когда каталог логов известен, перенаправляем ещё и stderr в файл рядом
    # с app.log — до этого он мог уйти в devnull (см. вызов в начале модуля).
    ensure_std_streams(log_directory)
    logger.info("Старт NeoLoader, log_directory=%s, frozen=%s", log_directory, getattr(sys, "frozen", False))

    # Мост для нативных диалогов (выбор папки загрузок из веб-интерфейса). Создаётся
    # ЗДЕСЬ, в главном потоке и после QApplication — QFileDialog нельзя ни создавать
    # из потока uvicorn, ни строить до появления приложения.
    from ui import dialogs

    dialogs.install()

    settings = SettingsManager()
    download_manager = DownloadManager(settings)
    media_manager = MediaJobManager(settings)

    supervisor = ApiSupervisor(settings, download_manager, media_manager)
    supervisor.start()
    # В собранном EXE импорт FastAPI/uvicorn/yt-dlp из запакованного PYZ-архива на холодном
    # старте заметно медленнее, чем из обычных .py на диске — окно (и React внутри него)
    # могло появиться раньше, чем uvicorn успевал забиндить порт. Пользователь успевал
    # вставить ссылку в первую секунду-две и получал сырую сетевую ошибку fetch (ECONNREFUSED),
    # которую фронтенд не умеет отличить от "видео недоступно".
    if not supervisor.wait_ready(timeout=API_STARTUP_TIMEOUT):
        logger.error("API не поднялся за %sс: %s", API_STARTUP_TIMEOUT, supervisor.last_error)
        _show_backend_failure(log_directory, supervisor.last_error)
    else:
        logger.info("API готов, порт %s", supervisor.port)

    window = WebMainWindow(api_port=supervisor.port)
    dialogs.set_parent_window(window)
    window.show()
    logger.info("Окно показано")

    try:
        from ui.tray import TrayIcon

        tray = TrayIcon(_load_app_icon(), window, download_manager, log_directory)
        tray.show()
        logger.info("Трей создан")

        single_instance = SingleInstanceServer()
        single_instance.show_requested.connect(tray.show_window)
    except Exception:
        # Если трей/single-instance не поднялись — само окно уже видимо и рабочее,
        # не роняем всё приложение из-за второстепенной части. Раньше именно так
        # (необработанное исключение здесь) выглядело "запускаю exe, а в трее не
        # видно кнопки выход" — процесс падал целиком ДО того, как меню дорисовывалось.
        logger.exception("Не удалось поднять трей/single-instance — окно всё равно работает")

    exit_code = app.exec()
    supervisor.stop()
    media_manager.shutdown()  # оборвать ffmpeg-процессы и убрать недописанные файлы
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
