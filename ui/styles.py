"""QSS-стили тёмной и светлой темы в духе Telegram/Spotify: скруглённые углы, красный акцент."""

ACCENT = "#FF3B3B"
ACCENT_DARK = "#CC0000"

DARK_THEME = f"""
QWidget {{
    background-color: #17181C;
    color: #E8E8E8;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: #17181C;
}}

QTabWidget::pane {{
    border: none;
    background-color: #17181C;
}}

QTabBar::tab {{
    background-color: #1F2126;
    color: #A0A0A6;
    padding: 8px 18px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}}

QTabBar::tab:selected {{
    background-color: {ACCENT};
    color: #FFFFFF;
}}

QLineEdit, QComboBox, QTextEdit, QListWidget, QTableWidget {{
    background-color: #23252B;
    border: 1px solid #2E3138;
    border-radius: 10px;
    padding: 6px 10px;
    color: #E8E8E8;
}}

QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}

QPushButton {{
    background-color: #2A2D34;
    border: none;
    border-radius: 10px;
    padding: 8px 16px;
    color: #E8E8E8;
}}

QPushButton:hover {{
    background-color: #34373F;
}}

QPushButton:pressed {{
    background-color: #23252B;
}}

QPushButton#accentButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT_DARK});
    color: #FFFFFF;
    font-weight: 600;
}}

QPushButton#accentButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #FF5555, stop:1 {ACCENT_DARK});
}}

QProgressBar {{
    background-color: #23252B;
    border-radius: 8px;
    text-align: center;
    color: #E8E8E8;
    height: 16px;
}}

QProgressBar::chunk {{
    border-radius: 8px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT_DARK});
}}

QCheckBox {{
    spacing: 8px;
}}

QScrollBar:vertical {{
    background: #17181C;
    width: 10px;
}}

QScrollBar::handle:vertical {{
    background: #34373F;
    border-radius: 5px;
    min-height: 24px;
}}

#QueueCard {{
    background-color: #1F2126;
    border-radius: 12px;
    border: 1px solid #2E3138;
}}
"""

LIGHT_THEME = f"""
QWidget {{
    background-color: #FAFAFA;
    color: #202124;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background-color: #FAFAFA;
}}

QTabWidget::pane {{
    border: none;
    background-color: #FAFAFA;
}}

QTabBar::tab {{
    background-color: #EFEFF2;
    color: #5F6368;
    padding: 8px 18px;
    margin-right: 4px;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
}}

QTabBar::tab:selected {{
    background-color: {ACCENT};
    color: #FFFFFF;
}}

QLineEdit, QComboBox, QTextEdit, QListWidget, QTableWidget {{
    background-color: #FFFFFF;
    border: 1px solid #DADCE0;
    border-radius: 10px;
    padding: 6px 10px;
    color: #202124;
}}

QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}

QPushButton {{
    background-color: #EFEFF2;
    border: none;
    border-radius: 10px;
    padding: 8px 16px;
    color: #202124;
}}

QPushButton:hover {{
    background-color: #E2E3E7;
}}

QPushButton:pressed {{
    background-color: #D5D6DB;
}}

QPushButton#accentButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT_DARK});
    color: #FFFFFF;
    font-weight: 600;
}}

QProgressBar {{
    background-color: #EFEFF2;
    border-radius: 8px;
    text-align: center;
    color: #202124;
    height: 16px;
}}

QProgressBar::chunk {{
    border-radius: 8px;
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT}, stop:1 {ACCENT_DARK});
}}

#QueueCard {{
    background-color: #FFFFFF;
    border-radius: 12px;
    border: 1px solid #DADCE0;
}}
"""


def get_theme(name: str) -> str:
    return LIGHT_THEME if name == "light" else DARK_THEME
