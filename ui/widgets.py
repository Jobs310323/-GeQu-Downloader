"""Кастомные виджеты: карточка очереди, цветная лог-консоль, акцентная кнопка."""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap, QTextCharFormat
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.download_manager import (
    STATUS_CANCELLED,
    STATUS_DONE,
    STATUS_DOWNLOADING,
    STATUS_ERROR,
    STATUS_PAUSED,
    STATUS_PENDING,
)

STATUS_LABELS = {
    STATUS_PENDING: "Ожидает",
    STATUS_DOWNLOADING: "Скачивается",
    STATUS_PAUSED: "Пауза",
    STATUS_DONE: "Готово",
    STATUS_ERROR: "Ошибка",
    STATUS_CANCELLED: "Отменено",
}

STATUS_COLORS = {
    STATUS_PENDING: "#8A8D93",
    STATUS_DOWNLOADING: "#3B9DFF",
    STATUS_PAUSED: "#E0A030",
    STATUS_DONE: "#3BC46B",
    STATUS_ERROR: "#E05252",
    STATUS_CANCELLED: "#8A8D93",
}


def GradientButton(text: str) -> QPushButton:
    """Кнопка с акцентным градиентом (стиль задаётся через objectName в QSS)."""
    btn = QPushButton(text)
    btn.setObjectName("accentButton")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


class QueueItemCard(QWidget):
    """Карточка одного элемента очереди: миниатюра, название, статус, прогресс, кнопки управления."""

    pause_clicked = pyqtSignal(str)
    cancel_clicked = pyqtSignal(str)
    remove_clicked = pyqtSignal(str)

    def __init__(self, item_id: str, title: str, parent=None) -> None:
        super().__init__(parent)
        self.item_id = item_id
        self.setObjectName("QueueCard")

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(64, 36)
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setStyleSheet("background-color: #000; border-radius: 6px;")
        root.addWidget(self.thumb_label)

        center = QVBoxLayout()
        title_row = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-weight: 600;")
        title_row.addWidget(self.title_label, stretch=1)

        self.status_label = QLabel()
        title_row.addWidget(self.status_label)
        center.addLayout(title_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%p%")
        center.addWidget(self.progress_bar)

        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet("color: #8A8D93; font-size: 11px;")
        center.addWidget(self.speed_label)

        root.addLayout(center, stretch=1)

        buttons = QVBoxLayout()
        self.pause_btn = QPushButton("Пауза")
        self.pause_btn.clicked.connect(lambda: self.pause_clicked.emit(self.item_id))
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(lambda: self.cancel_clicked.emit(self.item_id))
        buttons.addWidget(self.pause_btn)
        buttons.addWidget(self.cancel_btn)
        root.addLayout(buttons)

        self.set_status(STATUS_PENDING)

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb_label.setPixmap(pixmap)

    def update_progress(self, percent: float, speed: str) -> None:
        self.progress_bar.setValue(int(percent))
        self.speed_label.setText(speed)

    def set_status(self, status: str) -> None:
        self.status_label.setText(STATUS_LABELS.get(status, status))
        self._set_status_style(status)
        is_active = status in (STATUS_DOWNLOADING, STATUS_PAUSED, STATUS_PENDING)
        self.pause_btn.setEnabled(status in (STATUS_DOWNLOADING, STATUS_PAUSED))
        self.pause_btn.setText("Возобновить" if status == STATUS_PAUSED else "Пауза")
        self.cancel_btn.setEnabled(is_active)

    def _set_status_style(self, status: str) -> None:
        color = STATUS_COLORS.get(status, "#8A8D93")
        self.status_label.setStyleSheet(f"color: {color}; font-weight: 600;")


class ColorLogConsole(QTextEdit):
    """Read-only лог-консоль с цветным выводом по уровню сообщения."""

    LEVEL_COLORS = {
        "success": "#3BC46B",
        "warning": "#E0A030",
        "error": "#E05252",
        "info": "#A0A0A6",
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.document().setMaximumBlockCount(2000)

    def append_log(self, level: str, text: str) -> None:
        color = self.LEVEL_COLORS.get(level, self.LEVEL_COLORS["info"])
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(text + "\n", fmt)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
