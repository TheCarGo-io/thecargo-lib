"""Database URL utilities shared across services.

Async services (FastAPI + SQLAlchemy AsyncSession) use ``postgresql+asyncpg``.
Sync workers (Celery tasks, idle workers) need ``postgresql+psycopg2`` for
the synchronous engine. This module normalises between the two so each
task module stops re-implementing the conversion.
"""

from __future__ import annotations


def to_sync_url(url: str) -> str:
    """Convert an async Postgres URL (``+asyncpg``) to its sync (``+psycopg2``) form.

    Idempotent: a URL already using ``+psycopg2`` (or a non-async dialect)
    passes through unchanged. A bare ``postgresql://`` is treated as async
    by default - we attach ``+psycopg2`` so SQLAlchemy picks the sync
    driver explicitly.
    """
    out = url.replace("+asyncpg", "+psycopg2")
    if out.startswith("postgresql://") and "+psycopg2" not in out:
        out = out.replace("postgresql://", "postgresql+psycopg2://", 1)
    return out
