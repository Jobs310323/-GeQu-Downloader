# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: сборка onedir (папка dist/NeoLoader/ с NeoLoader.exe внутри).
Сборка: pyinstaller build.spec (см. README о том, что нужно сначала `npm run build`
во frontend/, чтобы frontend/dist/ существовал — иначе окно откроет пустую страницу).

Раньше был onefile — один EXE, который при каждом запуске сам себя распаковывает
во временную папку (%TEMP%\\_MEIxxxxx, новый случайный путь каждый раз). На боевой
машине пользователя это означало, что антивирус пересканировал ~200МБ заново
на КАЖДОМ старте (кэш по пути/хешу не срабатывает — путь каждый раз новый), из-за
чего бэкенд иногда не успевал подняться за отведённые секунды — непредсказуемо,
то быстро, то нет. onedir распаковывать не нужно — файлы лежат на месте постоянно,
антивирус сканирует их один раз, дальше не трогает. Из минусов — вместо одного
файла пользователь получает папку, но сам EXE внутри неё запускается так же
двойным кликом, ничего для пользователя не меняется."""

import os

from PyInstaller.utils.hooks import collect_submodules

# uvicorn/websockets выбирают конкретную реализацию (http/ws/loop) через importlib по
# строке ("auto" -> h11/websockets_impl) — статический анализ PyInstaller это не видит,
# без explicit collect_submodules сборка падает в рантайме с ModuleNotFoundError.
hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + ["yt_dlp", "anthropic", "core.summarizer", "ui.dialogs"]
)

datas = [
    ('frontend/dist', 'frontend/dist'),
    ('assets/icon.ico', 'assets'),
]
# Бандл ffmpeg.exe/ffprobe.exe — опциональный: положи их в assets/bin/ перед сборкой,
# чтобы EXE работал у пользователя без системного ffmpeg (см. core/ffmpeg_locator.py).
# Без этой папки приложение всё равно соберётся и будет работать, просто будет
# по-прежнему полагаться на ffmpeg из системного PATH, как раньше.
if os.path.isdir('assets/bin'):
    datas.append(('assets/bin', 'assets/bin'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='NeoLoader',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='NeoLoader',
)
