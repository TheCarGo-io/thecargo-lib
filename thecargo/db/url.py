from __future__ import annotations


def to_sync_url(url: str) -> str:
    out = url.replace("+asyncpg", "+psycopg2")
    if out.startswith("postgresql://") and "+psycopg2" not in out:
        out = out.replace("postgresql://", "postgresql+psycopg2://", 1)
    return out
