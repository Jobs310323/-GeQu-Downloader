"""Краткое саммери видео по субтитрам.

Пайплайн: yt-dlp отдаёт список дорожек субтитров (ручных и авто-сгенерированных) ->
скачиваем текстовую дорожку -> чистим -> сжимаем.

Сжатие двухрежимное и это осознанно:
  * если пользователь вписал в настройках ключ Anthropic API — саммери делает Claude
    (связный пересказ, тезисы, тайм-коды);
  * если ключа нет — работает встроенный экстрактивный алгоритм (частотное
    взвешивание предложений). Он заметно проще по качеству, но не требует ни ключа,
    ни интернета сверх самого YouTube, поэтому кнопка не превращается в мёртвую
    для тех, кто ключ заводить не хочет.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Optional

import requests
from yt_dlp import YoutubeDL

from core.video_info import base_ydl_opts

logger = logging.getLogger("neoloader.summary")

# Порядок предпочтения дорожек субтитров: сначала язык интерфейса, потом оригинал.
PREFERRED_SUB_FORMATS = ("json3", "srv3", "srv1", "vtt", "ttml")
TRANSCRIPT_TIMEOUT = 30
MAX_TRANSCRIPT_CHARS = 400_000  # ~100k токенов: лимита 1M контекста хватает с запасом

DEFAULT_MODEL = "claude-opus-5"

# Стоп-слова для локального (без API) алгоритма. Список короткий и намеренно
# двуязычный — саммери чаще всего строится по русским или английским субтитрам.
STOPWORDS = set(
    """
    и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по
    только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если
    уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей
    может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз
    тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом
    один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец
    два об другой хоть после над больше тот через эти нас про всего них какая много
    разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой
    им более всегда конечно всю между это
    the be to of and a in that have i it for not on with he as you do at this but his by
    from they we say her she or an will my one all would there their what so up out if
    about who get which go me when make can like time no just him know take people into
    year your good some could them see other than then now look only come its over think
    also back after use two how our work first well way even new want because any these
    give day most us is are was were been has had did does
    """.split()
)


class TranscriptUnavailable(Exception):
    """У видео нет ни ручных, ни авто-субтитров — саммери построить не из чего."""


# --------------------------------------------------------------------------- transcript


def _pick_track(tracks: dict, langs: list[str]) -> Optional[list]:
    """Выбирает дорожку субтитров по списку предпочитаемых языков.

    Ключи у YouTube бывают и "ru", и "ru-RU", и "a.ru" — поэтому сравниваем по префиксу,
    а не по точному совпадению (иначе для половины видео "субтитров нет")."""
    if not tracks:
        return None
    for lang in langs:
        for key, formats in tracks.items():
            normalized = key.lower().replace("_", "-").lstrip("a.")
            if normalized == lang or normalized.startswith(lang + "-"):
                return formats
    return next(iter(tracks.values()), None)


def _pick_format(formats: list) -> Optional[dict]:
    for ext in PREFERRED_SUB_FORMATS:
        for fmt in formats:
            if fmt.get("ext") == ext and fmt.get("url"):
                return fmt
    return next((f for f in formats if f.get("url")), None)


def _parse_json3(payload: str) -> str:
    data = json.loads(payload)
    lines: list[str] = []
    for event in data.get("events") or []:
        text = "".join(seg.get("utf8", "") for seg in (event.get("segs") or []))
        text = " ".join(text.split())
        if not text:
            continue
        # Авто-субтитры YouTube «накатываются»: каждая следующая реплика повторяет
        # хвост предыдущей. Без этой проверки транскрипт раздувается вдвое, а
        # экстрактивное саммери состоит из одних повторов.
        if lines and (text == lines[-1] or lines[-1].endswith(text) or text.startswith(lines[-1])):
            if text.startswith(lines[-1]) and text != lines[-1]:
                lines[-1] = text
            continue
        lines.append(text)
    return " ".join(lines)


_VTT_TIMECODE = re.compile(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->")
_TAG = re.compile(r"<[^>]+>")


def _parse_timed_text(payload: str) -> str:
    """Общий разбор VTT/SRT/TTML: выкидываем тайм-коды, номера, разметку и дубли.

    Авто-субтитры YouTube приходят «лесенкой»: каждая следующая реплика повторяет
    хвост предыдущей. Без дедупликации текст раздувается в 2-3 раза, а саммери
    получается из повторов."""
    if payload.lstrip().startswith("<"):
        payload = re.sub(r"<[^>]*>", "\n", payload)
    out: list[str] = []
    for raw in payload.splitlines():
        line = _TAG.sub("", raw).strip()
        if not line or line in ("WEBVTT",) or line.isdigit():
            continue
        if _VTT_TIMECODE.match(line) or "-->" in line:
            continue
        if line.startswith(("Kind:", "Language:", "NOTE ")):
            continue
        if out and (line == out[-1] or line in out[-1]):
            continue
        out.append(line)
    return " ".join(out)


def fetch_transcript(url: str, langs: list[str] | None = None, settings=None) -> tuple[str, str]:
    """Возвращает (текст субтитров, код языка дорожки). Бросает TranscriptUnavailable."""
    langs = [l.lower() for l in (langs or ["ru", "en"])]
    opts = base_ydl_opts(settings)
    opts.update({"skip_download": True, "noplaylist": True})
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    # Ручные субтитры точнее авто-распознавания — пробуем их первыми.
    formats = _pick_track(manual, langs) or _pick_track(auto, langs)
    if not formats:
        raise TranscriptUnavailable("У видео нет субтитров, по которым можно построить саммери")

    chosen = _pick_format(formats)
    if not chosen:
        raise TranscriptUnavailable("Субтитры есть, но ни одна дорожка не отдала ссылку")

    lang_code = chosen.get("name") or ""
    response = requests.get(chosen["url"], timeout=TRANSCRIPT_TIMEOUT)
    response.raise_for_status()
    payload = response.text

    if chosen.get("ext") == "json3":
        text = _parse_json3(payload)
    else:
        text = _parse_timed_text(payload)

    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise TranscriptUnavailable("Дорожка субтитров пуста")
    return text[:MAX_TRANSCRIPT_CHARS], lang_code


# --------------------------------------------------------------------------- local mode

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
_WORD = re.compile(r"[\w']+", re.UNICODE)


def _split_sentences(text: str) -> list[str]:
    parts = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if len(parts) > 1:
        return parts
    # Авто-субтитры часто идут вообще без знаков препинания — режем по словам,
    # иначе весь транскрипт это одно «предложение» и ранжировать нечего.
    words = text.split()
    return [" ".join(words[i : i + 25]) for i in range(0, len(words), 25)] or [text]


def summarize_locally(text: str, max_sentences: int = 7) -> dict:
    """Экстрактивное саммери без внешних сервисов: берём предложения с наибольшей
    плотностью частотных (не стоп-) слов и возвращаем их в исходном порядке."""
    sentences = _split_sentences(text)
    if len(sentences) <= max_sentences:
        return {"summary": " ".join(sentences), "bullets": sentences, "engine": "local"}

    freq = Counter(
        w for w in (m.group(0).lower() for m in _WORD.finditer(text)) if w not in STOPWORDS and len(w) > 2
    )
    if not freq:
        return {"summary": " ".join(sentences[:max_sentences]), "bullets": sentences[:max_sentences], "engine": "local"}
    top = freq.most_common(200)
    weights = {w: c for w, c in top}

    scored = []
    for index, sentence in enumerate(sentences):
        words = [m.group(0).lower() for m in _WORD.finditer(sentence)]
        if not words:
            continue
        score = sum(weights.get(w, 0) for w in words) / (len(words) ** 0.5)
        scored.append((score, index, sentence))

    best = sorted(scored, key=lambda t: t[0], reverse=True)[:max_sentences]
    best.sort(key=lambda t: t[1])
    bullets = [s for _, _, s in best]
    return {"summary": " ".join(bullets), "bullets": bullets, "engine": "local"}


# --------------------------------------------------------------------------- Claude mode

SYSTEM_PROMPT = (
    "Ты делаешь краткие пересказы видео по расшифровке субтитров. "
    "Пиши на том же языке, на котором говорят в видео. "
    "Не выдумывай фактов, которых нет в расшифровке. "
    "Субтитры могут быть авто-распознанными и содержать ошибки — опирайся на смысл."
)

USER_TEMPLATE = """Вот расшифровка видео «{title}»{duration}.

Сделай:
1. Абзац на 3-5 предложений — о чём это видео целиком.
2. Список из 5-8 ключевых тезисов, по одному на строку, каждый начинается с "- ".
3. Одно предложение "Кому смотреть:".

Расшифровка:
<transcript>
{transcript}
</transcript>"""


def summarize_with_claude(
    text: str,
    api_key: str,
    title: str = "",
    duration: Optional[int] = None,
    model: str = DEFAULT_MODEL,
) -> dict:
    """Саммери через Claude. Ключ берётся из настроек приложения и никуда, кроме
    api.anthropic.com, не уходит; в лог он не пишется."""
    import anthropic  # локальный импорт: без ключа зависимость вообще не нужна

    client = anthropic.Anthropic(api_key=api_key)
    duration_note = ""
    if duration:
        duration_note = f" (длительность {duration // 60} мин)"

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": USER_TEMPLATE.format(
                    title=title or "без названия", duration=duration_note, transcript=text
                ),
            }
        ],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Модель отказалась обрабатывать эту расшифровку")

    body = "\n".join(block.text for block in response.content if block.type == "text").strip()
    bullets = [line.lstrip("-• ").strip() for line in body.splitlines() if line.strip().startswith(("-", "•"))]
    return {"summary": body, "bullets": bullets, "engine": f"claude:{model}"}


# --------------------------------------------------------------------------- entry point


def build_summary(url: str, settings=None, title: str = "", duration: Optional[int] = None) -> dict:
    """Полный путь: субтитры -> саммери. Возвращает dict для API."""
    langs = ["ru", "en"]
    if settings is not None and settings.get("language") == "en":
        langs = ["en", "ru"]

    transcript, track_lang = fetch_transcript(url, langs=langs, settings=settings)

    api_key = (settings.get("summary_api_key", "") if settings is not None else "") or ""
    model = (settings.get("summary_model", DEFAULT_MODEL) if settings is not None else DEFAULT_MODEL) or DEFAULT_MODEL
    if api_key.strip():
        try:
            result = summarize_with_claude(transcript, api_key.strip(), title, duration, model)
        except Exception as exc:  # noqa: BLE001
            # Неверный ключ / нет сети / лимит — не роняем фичу целиком, отдаём
            # локальное саммери и честно говорим, почему оно локальное.
            logger.warning("Claude-саммери не удалось (%s) — откат на локальный алгоритм", type(exc).__name__)
            result = summarize_locally(transcript)
            result["fallback_reason"] = str(exc)[:300]
    else:
        result = summarize_locally(transcript)

    result["transcript_language"] = track_lang
    result["transcript_chars"] = len(transcript)
    return result
