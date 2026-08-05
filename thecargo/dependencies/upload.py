from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import HTTPException, UploadFile

from thecargo.public_storage import upload_public_bytes
from thecargo.storage import upload_bytes

_log = logging.getLogger(__name__)

IMAGE_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }
)

DOCUMENT_TYPES: frozenset[str] = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
)

PROOF_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "application/pdf",
    }
)

PERMISSIVE_PREFIXES: tuple[str, ...] = (
    "image/",
    "application/pdf",
    "application/msword",
    "application/vnd.",
)

PERMISSIVE_EXACT: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/csv",
        "application/zip",
    }
)

MAX_BYTES_TINY: int = 2 * 1024 * 1024
MAX_BYTES_SMALL: int = 10 * 1024 * 1024
MAX_BYTES_LARGE: int = 25 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class UploadResult:
    name: str
    url: str
    mime_type: str
    size_bytes: int


_FILENAME_KEEP = re.compile(r"[^A-Za-z0-9._\-]+")


def safe_filename(name: str | None) -> str:
    raw = (name or "file").strip()
    cleaned = _FILENAME_KEEP.sub("_", raw).replace("..", "_").lstrip(".") or "file"
    return cleaned[:255]


def _check_mime(content_type: str, exact: frozenset[str], prefixes: tuple[str, ...]) -> None:
    if not exact and not prefixes:
        return
    if content_type in exact:
        return
    if any(content_type.startswith(p) for p in prefixes):
        return
    raise HTTPException(415, f"Unsupported MIME type: {content_type}")


_MARKUP_PREFIXES: tuple[bytes, ...] = (
    b"<?xml",
    b"<!doctype",
    b"<html",
    b"<svg",
    b"<script",
    b"<!--",
    b"<?php",
)


def _sniff(raw: bytes) -> str | None:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    if raw.startswith(b"%PDF-"):
        return "application/pdf"
    if raw.startswith(b"PK\x03\x04"):
        return "application/zip"
    if raw.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/msword"
    return None


def _looks_like_markup(raw: bytes) -> bool:
    return raw[:512].lstrip().lower().startswith(_MARKUP_PREFIXES)


def _resolve_mime(raw: bytes, declared: str, exact: frozenset[str], prefixes: tuple[str, ...]) -> str:
    sniffed = _sniff(raw)
    if sniffed is None:
        if _looks_like_markup(raw):
            raise HTTPException(415, "Markup and script uploads are not accepted")
        _check_mime(declared, exact, prefixes)
        return declared
    if sniffed == "application/zip" and (declared == "application/zip" or declared.startswith("application/vnd.")):
        _check_mime(declared, exact, prefixes)
        return declared
    _check_mime(sniffed, exact, prefixes)
    return sniffed


PathBuilder = Callable[[str, str], str]


async def upload_to_storage(
    file: UploadFile,
    *,
    path_builder: PathBuilder,
    allowed_exact: frozenset[str] = frozenset(),
    allowed_prefixes: tuple[str, ...] = (),
    max_bytes: int = MAX_BYTES_SMALL,
    public: bool = False,
) -> UploadResult:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    if len(raw) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(413, f"File exceeds {limit_mb} MB limit")

    declared = file.content_type or "application/octet-stream"
    content_type = _resolve_mime(raw, declared, allowed_exact, allowed_prefixes)

    safe = safe_filename(file.filename)
    storage_path = path_builder(safe, content_type)

    writer = upload_public_bytes if public else upload_bytes
    try:
        url = await asyncio.to_thread(writer, storage_path, raw, content_type)
    except Exception as exc:
        _log.error("R2 upload failed for %s: %s", storage_path, exc)
        raise HTTPException(502, "Object storage unavailable") from exc
    return UploadResult(name=safe, url=url, mime_type=content_type, size_bytes=len(raw))
