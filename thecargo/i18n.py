from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Request

_log = logging.getLogger(__name__)

DEFAULT_LANG: str = "en"
SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"uz", "ru", "en"})

_locale_dir: Path | None = None
_cache: dict[str, dict[str, str]] = {}


def bind_locale_dir(path: Path | str) -> None:
    global _locale_dir
    _locale_dir = Path(path)
    _cache.clear()


def get_language(request: Request | None) -> str:
    if request is None:
        return DEFAULT_LANG
    raw = request.headers.get("Accept-Language", DEFAULT_LANG)
    lang = raw.split(",")[0].split("-")[0].strip().lower()
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANG


def _load(lang: str) -> dict[str, str]:
    if lang in _cache:
        return _cache[lang]
    if _locale_dir is None:
        _cache[lang] = {}
        return _cache[lang]
    path = _locale_dir / f"{lang}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _log.debug("Locale file missing: %s", path)
        data = {}
    except json.JSONDecodeError as exc:
        _log.warning("Locale file invalid JSON %s: %s", path, exc)
        data = {}
    _cache[lang] = data
    return data


def translate(key: str, lang: str, params: dict | None = None) -> str | None:
    template = _load(lang).get(key)
    if template is None and lang != DEFAULT_LANG:
        template = _load(DEFAULT_LANG).get(key)
    if template is None:
        return None
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError):
        return template
