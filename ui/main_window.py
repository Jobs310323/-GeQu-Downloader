"""Главное окно приложения: вкладки, форма загрузки, очередь, история, настройки."""

import io

import requests
from PIL import Image
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices, QImage, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.download_manager import DownloadManager, QueueItem
from core.settings_manager import SettingsManager
from core.video_info import LinkType, VideoInfoWorker, detect_link_type
from ui.styles import get_theme
from ui.widgets import ColorLogConsole, GradientButton, QueueItemCard

QUALITY_OPTIONS = ["4K", "2K", "1080p", "720p", "480p", "360p"]
AUDIO_FORMAT_OPTIONS = ["mp3", "m4a", "original"]
AUDIO_BITRATE_OPTIONS = ["128", "192", "320"]
VIDEO_CODEC_OPTIONS = ["any", "h264", "vp9", "av1"]
AUDIO_CODEC_OPTIONS = ["any", "aac", "opus"]

ERROR_MESSAGES = {
    "no_space": "Недостаточно места на диске для загрузки.",
    "age_restricted": "Видео требует подтверждения возраста и недоступно без авторизации.",
    "geo_blocked": "Видео недоступно в вашем регионе.",
    "unavailable": "Видео недоступно или было удалено.",
    "network": "Проблема с подключением к интернету. Проверьте соединение.",
    "invalid_url": "Ссылка некорректна или не поддерживается.",
    "unknown": "Произошла ошибка при загрузке.",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("YouTube Downloader")
        self.resize(920, 680)

        self.settings = SettingsManager()
        self.download_manager = DownloadManager(self.settings)
        self._connect_manager_signals()

        self._info_worker: VideoInfoWorker | None = None
        self._pending_info: dict | None = None
        self._queue_cards: dict[str, QueueItemCard] = {}

        self._build_ui()
        self._apply_theme(self.settings.get("theme", "dark"))
        self._setup_shortcuts()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        tabs.addTab(self._build_download_tab(), "Загрузка")
        tabs.addTab(self._build_history_tab(), "История")
        tabs.addTab(self._build_settings_tab(), "Настройки")

    def _build_download_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)

        # --- строка ввода URL ---
        url_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Вставьте ссылку на видео или плейлист YouTube...")
        self.url_input.textChanged.connect(self._on_url_changed)
        url_row.addWidget(self.url_input, stretch=1)

        paste_btn = QPushButton("Вставить")
        paste_btn.clicked.connect(self._paste_from_clipboard)
        url_row.addWidget(paste_btn)

        clear_btn = QPushButton("Очистить")
        clear_btn.clicked.connect(lambda: self.url_input.clear())
        url_row.addWidget(clear_btn)
        layout.addLayout(url_row)

        # --- карточка предпросмотра ---
        preview_row = QHBoxLayout()
        self.preview_thumb = QLabel()
        self.preview_thumb.setFixedSize(160, 90)
        self.preview_thumb.setStyleSheet("background-color: #000; border-radius: 8px;")
        self.preview_thumb.setScaledContents(True)
        preview_row.addWidget(self.preview_thumb)

        preview_text = QVBoxLayout()
        self.preview_title = QLabel("Вставьте ссылку, чтобы увидеть превью")
        self.preview_title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.preview_title.setWordWrap(True)
        self.preview_meta = QLabel("")
        self.preview_meta.setStyleSheet("color: #8A8D93;")
        preview_text.addWidget(self.preview_title)
        preview_text.addWidget(self.preview_meta)
        preview_text.addStretch()
        preview_row.addLayout(preview_text, stretch=1)
        layout.addLayout(preview_row)

        # --- параметры загрузки ---
        options_row = QHBoxLayout()

        options_row.addWidget(QLabel("Качество:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(QUALITY_OPTIONS)
        self.quality_combo.setCurrentText(self.settings.get("default_quality", "1080p"))
        options_row.addWidget(self.quality_combo)

        self.audio_only_check = QCheckBox("Только аудио")
        self.audio_only_check.setChecked(self.settings.get("audio_only", False))
        self.audio_only_check.toggled.connect(self._on_audio_only_toggled)
        options_row.addWidget(self.audio_only_check)

        self.audio_format_combo = QComboBox()
        self.audio_format_combo.addItems(AUDIO_FORMAT_OPTIONS)
        self.audio_format_combo.setCurrentText(self.settings.get("audio_format", "mp3"))
        options_row.addWidget(self.audio_format_combo)

        self.audio_bitrate_combo = QComboBox()
        self.audio_bitrate_combo.addItems(AUDIO_BITRATE_OPTIONS)
        self.audio_bitrate_combo.setCurrentText(self.settings.get("audio_bitrate", "192"))
        options_row.addWidget(self.audio_bitrate_combo)

        self.subtitles_check = QCheckBox("Субтитры (.srt)")
        options_row.addWidget(self.subtitles_check)

        self.neuro_dub_check = QCheckBox("Русская озвучка (нейродубляж)")
        self.neuro_dub_check.setEnabled(False)
        self.neuro_dub_check.setToolTip("Доступно, если YouTube предоставляет русскую аудиодорожку")
        options_row.addWidget(self.neuro_dub_check)

        options_row.addStretch()
        layout.addLayout(options_row)

        # --- кодеки ---
        codec_row = QHBoxLayout()
        codec_row.addWidget(QLabel("Видеокодек:"))
        self.video_codec_combo = QComboBox()
        self.video_codec_combo.addItems(VIDEO_CODEC_OPTIONS)
        codec_row.addWidget(self.video_codec_combo)

        codec_row.addWidget(QLabel("Аудиокодек:"))
        self.audio_codec_combo = QComboBox()
        self.audio_codec_combo.addItems(AUDIO_CODEC_OPTIONS)
        codec_row.addWidget(self.audio_codec_combo)

        codec_row.addStretch()
        layout.addLayout(codec_row)
        self._on_audio_only_toggled(self.audio_only_check.isChecked())

        # --- папка сохранения ---
        folder_row = QHBoxLayout()
        self.folder_input = QLineEdit(self.settings.get("download_folder", ""))
        self.folder_input.setReadOnly(True)
        folder_row.addWidget(self.folder_input, stretch=1)
        browse_btn = QPushButton("Обзор...")
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse_btn)

        self.playlist_folder_check = QCheckBox("Папка для плейлиста")
        self.playlist_folder_check.setChecked(self.settings.get("create_playlist_folder", True))
        folder_row.addWidget(self.playlist_folder_check)

        self.remove_after_check = QCheckBox("Удалить из очереди после скачивания")
        self.remove_after_check.setChecked(self.settings.get("remove_after_download", False))
        folder_row.addWidget(self.remove_after_check)
        layout.addLayout(folder_row)

        add_btn = GradientButton("Добавить в очередь")
        add_btn.clicked.connect(self._add_to_queue)
        layout.addWidget(add_btn)

        # --- очередь загрузок ---
        layout.addWidget(QLabel("Очередь загрузок:"))
        self.queue_scroll = QScrollArea()
        self.queue_scroll.setWidgetResizable(True)
        self.queue_container = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_container)
        self.queue_layout.addStretch()
        self.queue_scroll.setWidget(self.queue_container)
        layout.addWidget(self.queue_scroll, stretch=1)

        # --- лог ---
        layout.addWidget(QLabel("Лог:"))
        self.log_console = ColorLogConsole()
        self.log_console.setMaximumHeight(140)
        layout.addWidget(self.log_console)

        return root

    def _build_history_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)

        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Название", "Ссылка", ""])
        self.history_table.horizontalHeader().setStretchLastSection(False)
        self.history_table.setColumnWidth(0, 400)
        self.history_table.setColumnWidth(1, 300)
        layout.addWidget(self.history_table)

        self._reload_history_table()
        return root

    def _build_settings_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Папка по умолчанию:"))
        self.settings_folder_input = QLineEdit(self.settings.get("download_folder", ""))
        self.settings_folder_input.setReadOnly(True)
        folder_row.addWidget(self.settings_folder_input, stretch=1)
        browse_btn = QPushButton("Обзор...")
        browse_btn.clicked.connect(self._browse_default_folder)
        folder_row.addWidget(browse_btn)
        layout.addLayout(folder_row)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Тема оформления:"))
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.settings.get("theme", "dark"))
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_combo)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel("Язык:"))
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["ru", "en"])
        self.lang_combo.setCurrentText(self.settings.get("language", "ru"))
        self.lang_combo.currentTextChanged.connect(lambda v: self.settings.set("language", v))
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch()
        layout.addLayout(lang_row)

        update_row = QHBoxLayout()
        update_btn = QPushButton("Обновить yt-dlp")
        update_btn.clicked.connect(self._update_ytdlp)
        update_row.addWidget(update_btn)
        update_row.addStretch()
        layout.addLayout(update_row)

        layout.addStretch()
        return root

    def _setup_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+V"), self.url_input, self._paste_from_clipboard)
        self.url_input.returnPressed.connect(self._add_to_queue)

    # ------------------------------------------------------------- события

    def _on_url_changed(self, text: str) -> None:
        url = text.strip()
        link_type = detect_link_type(url)
        self.neuro_dub_check.setEnabled(False)
        self.neuro_dub_check.setChecked(False)
        if link_type == LinkType.INVALID:
            return
        # Перезапускаем воркер на каждое существенное изменение; поле url хранится на воркере,
        # чтобы в колбэке отбросить устаревший результат, если пользователь уже правил ссылку дальше.
        self._info_worker = VideoInfoWorker(url)
        self._info_worker.finished_ok.connect(lambda info, u=url: self._on_info_ready(u, info))
        self._info_worker.failed.connect(lambda msg, u=url: self._on_info_failed(u, msg))
        self._info_worker.start()

    def _is_stale(self, url: str) -> bool:
        return url != self.url_input.text().strip()

    def _on_info_ready(self, url: str, info: dict) -> None:
        if self._is_stale(url):
            return
        self._pending_info = info
        self.preview_title.setText(info["title"])
        if info["is_playlist"]:
            self.preview_meta.setText(f"Плейлист · {info['entries_count']} видео")
        else:
            duration = info.get("duration") or 0
            minutes, seconds = divmod(int(duration), 60)
            self.preview_meta.setText(f"{info.get('uploader', '')} · {minutes}:{seconds:02d}")

        self.neuro_dub_check.setEnabled(bool(info.get("has_ru_dub")))

        thumb_url = info.get("thumbnail")
        if thumb_url:
            self._load_thumbnail_async(thumb_url, self.preview_thumb)

    def _on_info_failed(self, url: str, message: str) -> None:
        if self._is_stale(url):
            return
        self.preview_title.setText("Не удалось получить информацию о видео")
        self.preview_meta.setText(message)

    def _load_thumbnail_async(self, url: str, label: QLabel) -> None:
        # Загрузка обложки — быстрая операция, но чтобы не блокировать UI даже на слабой сети,
        # выполняем её через requests с коротким таймаутом; при желании можно вынести в QThread.
        try:
            response = requests.get(url, timeout=5)
            image = Image.open(io.BytesIO(response.content)).convert("RGB")
            qimage = QImage(
                image.tobytes(), image.width, image.height, image.width * 3, QImage.Format.Format_RGB888
            )
            label.setPixmap(QPixmap.fromImage(qimage))
        except Exception:
            pass  # обложка необязательна — тихо пропускаем при сетевой ошибке

    def _paste_from_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text().strip())

    def _on_audio_only_toggled(self, checked: bool) -> None:
        self.quality_combo.setEnabled(not checked)
        self.audio_format_combo.setEnabled(checked)
        self.audio_bitrate_combo.setEnabled(checked)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку", self.folder_input.text())
        if folder:
            self.folder_input.setText(folder)

    def _browse_default_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку", self.settings_folder_input.text())
        if folder:
            self.settings_folder_input.setText(folder)
            self.settings.set("download_folder", folder)
            self.folder_input.setText(folder)

    def _on_theme_changed(self, theme: str) -> None:
        self.settings.set("theme", theme)
        self._apply_theme(theme)

    def _apply_theme(self, theme: str) -> None:
        QApplication.instance().setStyleSheet(get_theme(theme))

    def _update_ytdlp(self) -> None:
        import subprocess
        import sys

        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", "yt-dlp"])
            QMessageBox.information(self, "Обновление", "yt-dlp обновлён до последней версии.")
        except subprocess.CalledProcessError as exc:
            QMessageBox.warning(self, "Обновление", f"Не удалось обновить yt-dlp: {exc}")

    # --------------------------------------------------------------- очередь

    def _add_to_queue(self) -> None:
        url = self.url_input.text().strip()
        link_type = detect_link_type(url)
        if link_type == LinkType.INVALID:
            QMessageBox.warning(self, "Некорректная ссылка", "Введите корректную ссылку на видео YouTube.")
            return

        info = self._pending_info or {}
        item = QueueItem(
            url=url,
            title=info.get("title", url),
            quality=self.quality_combo.currentText(),
            audio_only=self.audio_only_check.isChecked(),
            audio_format=self.audio_format_combo.currentText(),
            audio_bitrate=self.audio_bitrate_combo.currentText(),
            subtitles=self.subtitles_check.isChecked(),
            neuro_dub_ru=self.neuro_dub_check.isEnabled() and self.neuro_dub_check.isChecked(),
            video_codec=self.video_codec_combo.currentText(),
            audio_codec=self.audio_codec_combo.currentText(),
            output_folder=self.folder_input.text(),
            is_playlist=info.get("is_playlist", link_type == LinkType.PLAYLIST),
            create_playlist_folder=self.playlist_folder_check.isChecked(),
            remove_after_download=self.remove_after_check.isChecked(),
        )

        card = QueueItemCard(item.id, item.title)
        card.pause_clicked.connect(self._on_pause_clicked)
        card.cancel_clicked.connect(self._on_cancel_clicked)
        self._queue_cards[item.id] = card
        # Вставляем перед финальным stretch-элементом.
        self.queue_layout.insertWidget(self.queue_layout.count() - 1, card)

        self.download_manager.add_to_queue(item)
        self.url_input.clear()
        self.preview_title.setText("Вставьте ссылку, чтобы увидеть превью")
        self.preview_meta.setText("")
        self.preview_thumb.clear()
        self.neuro_dub_check.setEnabled(False)
        self.neuro_dub_check.setChecked(False)
        self._pending_info = None

    def _on_pause_clicked(self, item_id: str) -> None:
        # Пауза/отмена в DownloadManager применяются только к активной (текущей) загрузке —
        # клик по карточке, которая ещё ждёт своей очереди, не должен трогать чужую загрузку.
        if item_id != self.download_manager.get_current_item_id():
            return
        card = self._queue_cards.get(item_id)
        if card and card.pause_btn.text() == "Пауза":
            self.download_manager.pause_current()
        else:
            self.download_manager.resume_current()

    def _on_cancel_clicked(self, item_id: str) -> None:
        if item_id == self.download_manager.get_current_item_id():
            self.download_manager.cancel_current()
            return
        # Элемент ещё не начал скачиваться — просто убираем его из очереди и списка на экране.
        self.download_manager.remove_from_queue(item_id)
        card = self._queue_cards.pop(item_id, None)
        if card:
            card.setParent(None)
            card.deleteLater()
        self.log_console.append_log("info", "Удалено из очереди")

    # ---------------------------------------------------- сигналы менеджера

    def _connect_manager_signals(self) -> None:
        self.download_manager.progress_changed.connect(self._on_progress_changed)
        self.download_manager.status_changed.connect(self._on_status_changed)
        self.download_manager.log_message.connect(self._on_log_message)
        self.download_manager.error_occurred.connect(self._on_error_occurred)
        self.download_manager.item_finished.connect(self._on_item_finished)

    def _on_progress_changed(self, item_id: str, percent: float, speed: str) -> None:
        card = self._queue_cards.get(item_id)
        if card:
            card.update_progress(percent, speed)

    def _on_status_changed(self, item_id: str, status: str) -> None:
        card = self._queue_cards.get(item_id)
        if card:
            card.set_status(status)

    def _on_log_message(self, level: str, text: str) -> None:
        self.log_console.append_log(level, text)

    def _on_error_occurred(self, item_id: str, code: str, message: str) -> None:
        text = ERROR_MESSAGES.get(code, message)
        QMessageBox.warning(self, "Ошибка загрузки", text)

    def _on_item_finished(self, item_id: str, meta: dict) -> None:
        self.settings.add_history_entry(meta)
        self._reload_history_table()

    # --------------------------------------------------------------- история

    def _reload_history_table(self) -> None:
        history = self.settings.get_history()
        self.history_table.setRowCount(len(history))
        for row, entry in enumerate(history):
            self.history_table.setItem(row, 0, QTableWidgetItem(entry.get("title", "")))
            self.history_table.setItem(row, 1, QTableWidgetItem(entry.get("url", "")))
            redownload_btn = QPushButton("Скачать снова")
            url = entry.get("url", "")
            redownload_btn.clicked.connect(lambda _, u=url: self._redownload(u))
            self.history_table.setCellWidget(row, 2, redownload_btn)

    def _redownload(self, url: str) -> None:
        self.url_input.setText(url)
        self._add_to_queue()

    def closeEvent(self, event) -> None:
        self.download_manager.stop()
        self.download_manager.cancel_current()
        self.download_manager.wait(2000)
        super().closeEvent(event)
