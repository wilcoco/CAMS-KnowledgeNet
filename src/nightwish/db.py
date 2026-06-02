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

import contextlib
import os
from typing import Optional

#: Cross-process advisory-lock key for serialising read-modify-write on the
#: single snapshot row. Any constant shared by all instances works.
_LOCK_KEY = 0x4E494748  # "NIGH"


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


@contextlib.contextmanager
def transaction(url: str):
    """Atomic read-modify-write of the snapshot, safe across instances.

    Holds a transaction-scoped advisory lock, reads the current snapshot, and
    yields a mutable ``box``. The caller reads ``box['data']`` (the latest
    committed snapshot, or ``None``) and sets ``box['data']`` to the new
    snapshot; it is written back in the **same** locked transaction. This makes
    concurrent writers serialise instead of clobbering each other's full-row
    upsert — the bug where a second instance's stale save erases new data.
    """
    from psycopg.types.json import Jsonb

    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            cur.execute("SELECT data FROM nightwish_state WHERE id = 1")
            row = cur.fetchone()
            box = {"data": row[0] if row else None}
            yield box
            cur.execute(
                "INSERT INTO nightwish_state (id, data, updated_at) "
                "VALUES (1, %s, now()) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, "
                "updated_at = now()",
                (Jsonb(box["data"]),),
            )
        conn.commit()
    finally:
        conn.close()


def meta(url: str) -> dict:
    """When the snapshot row was last written — to prove saves are landing."""
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT updated_at FROM nightwish_state WHERE id = 1")
        row = cur.fetchone()
        return {"exists": bool(row),
                "updated_at": str(row[0]) if row else None}


def selftest(url: str) -> dict:
    """Prove a real write→commit→read round-trip against this Postgres.

    Writes to a throwaway ``nightwish_probe`` table (never touches real data),
    commits, then reads it back on a *fresh* connection. If this returns
    ``ok: true`` the database genuinely accepts writes; if it errors, the
    message is the exact Postgres failure.
    """
    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS nightwish_probe ("
                " id int PRIMARY KEY, ts timestamptz)"
            )
            cur.execute(
                "INSERT INTO nightwish_probe (id, ts) VALUES (1, now()) "
                "ON CONFLICT (id) DO UPDATE SET ts = now() RETURNING ts"
            )
            wrote = cur.fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    # read back on a brand-new connection → proves the commit is durable
    conn2 = _connect(url)
    try:
        with conn2.cursor() as cur:
            cur.execute("SELECT ts FROM nightwish_probe WHERE id = 1")
            row = cur.fetchone()
            read = row[0] if row else None
    finally:
        conn2.close()
    return {"ok": read is not None and read == wrote,
            "wrote_at": str(wrote), "read_back": str(read)}
