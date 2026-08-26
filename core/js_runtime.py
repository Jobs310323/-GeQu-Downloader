"""Определяет, какие JS-движки (для решения челленджей YouTube) реально стоят
на машине — вместо того, чтобы всегда просить yt-dlp пробовать deno И node.
Если deno не установлен (частый случай — node куда более распространён),
yt-dlp всё равно пытается его вызвать первым при каждой загрузке/анализе,
это лишняя задержка на каждый запрос."""

import shutil


def available_js_runtimes() -> dict:
    runtimes = {}
    if shutil.which("deno"):
        runtimes["deno"] = {}
    if shutil.which("node"):
        runtimes["node"] = {}
    return runtimes
