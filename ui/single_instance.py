"""Гарантия единственного экземпляра приложения.

Пользователь запускает EXE двойным кликом — если он уже запущен (окно свёрнуто
в трей или просто открыто), повторный запуск не должен поднимать второй uvicorn
на том же порту: он молча активирует уже работающее окно и завершается сам."""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

_KEY = "NeoLoaderSingleInstance"


def try_acquire() -> bool:
    """True — это первый (единственный) экземпляр. False — уже есть другой, и ему
    только что отправлен сигнал "покажись"."""
    socket = QLocalSocket()
    socket.connectToServer(_KEY)
    if socket.waitForConnected(200):
        socket.write(b"show")
        socket.flush()
        socket.waitForBytesWritten(200)
        socket.close()
        return False

    # Не достучались — либо никого нет, либо остался мёртвый сокет после падения
    # процесса (Windows иногда не подчищает такие сразу). Освобождаем имя и слушаем.
    QLocalServer.removeServer(_KEY)
    return True


class SingleInstanceServer(QObject):
    """Слушает сигналы "show" от последующих попыток запуска и поднимает окно."""

    show_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        self._server.listen(_KEY)

    def _on_new_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is None:
            return
        conn.readyRead.connect(lambda: self._on_ready_read(conn))
        conn.disconnected.connect(conn.deleteLater)

    def _on_ready_read(self, conn: QLocalSocket) -> None:
        conn.readAll()
        self.show_requested.emit()
