"""PostgreSQL persistence (single-row JSONB snapshot).

The whole app state (wiki + economy) already serialises to one JSON document
(:func:`nightwish.wiki.Wiki.to_json` + economy). Rather than a relational schema
per node, we store that document in **one JSONB row** of a ``nightwish_state``
table and upsert it on every save. Minimal, durable, and reuses all existing
(de)serialisation — ideal for Railway Postgres.

Used automatically when ``DATABASE_URL`` (Railway's Postgres reference) is set;
otherwise the service falls back to a local JSON file. Requires ``psycopg``
(``pip install -e ".[service]"`` includes it).
"""

from __future__ import annotations

import os
from typing import Optional


def database_url() -> Optional[str]:
    """Railway sets ``DATABASE_URL``; allow an explicit override too."""
    return os.environ.get("NIGHTWISH_DATABASE_URL") or os.environ.get("DATABASE_URL")


def _connect(url: str):
    import psycopg  # lazy — only needed in DB mode

    return psycopg.connect(url, connect_timeout=10)


def init(url: str) -> None:
    """Create the state table if missing."""
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS nightwish_state ("
            " id int PRIMARY KEY,"
            " data jsonb NOT NULL,"
            " updated_at timestamptz DEFAULT now())"
        )
        conn.commit()


def load(url: str) -> Optional[dict]:
    """Return the stored snapshot dict, or ``None`` if the table is empty."""
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT data FROM nightwish_state WHERE id = 1")
        row = cur.fetchone()
        return row[0] if row else None  # psycopg adapts jsonb → dict


def save(url: str, data: dict) -> None:
    """Upsert the single snapshot row (id = 1)."""
    from psycopg.types.json import Jsonb

    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO nightwish_state (id, data, updated_at) "
            "VALUES (1, %s, now()) "
            "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, "
            "updated_at = now()",
            (Jsonb(data),),
        )
        conn.commit()
