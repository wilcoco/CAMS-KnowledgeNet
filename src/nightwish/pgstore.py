"""Normalized PostgreSQL persistence — one row per entity, not one JSON blob.

The earlier ``db.py`` stored the *whole* application state as a single JSONB
row. That works but it isn't a real database design: every read deserialises
everything, every write rewrites everything, and individual nodes can't be
queried or indexed. This module replaces that with a proper schema:

    node            one row per knowledge node (indexed by id, author, space, parent)
    node_link       wikilinks  [[Title]]            (node → target slug)
    linker          evaluation/authorship order      (node → evaluator, ordered)
    node_authority  per-node authority (권위)
    user_hub        per-user foresight (안목)
    stake           per (node, account) staked points
    endorser        endorsement order                (node → account, ordered)
    balance         per-account available points
    meta            scalars (clock, rates, mode, burned, …)

The data-shape logic — turning the in-memory snapshot into rows and back — lives
in the *pure* functions :func:`snapshot_to_rows` / :func:`rows_to_snapshot`,
which round-trip losslessly (unit-tested). The SQL functions are thin CRUD on
top, so point reads (a single node, a count, a search) touch only the rows they
need instead of loading the entire graph.
"""

from __future__ import annotations

import contextlib
import json
from typing import Optional

from nightwish.db import _LOCK_KEY, _connect, database_url  # reuse connection + lock

# --------------------------------------------------------------------------- #
# pure data-shape logic (no DB) — round-trip tested                           #
# --------------------------------------------------------------------------- #
# A snapshot is the unified app's ``{"schema": "unified-1", "tree": ..., "econ": ...}``.

_META_NUM = ("clock", "large_stake_threshold", "burned", "dividend_rate", "burn_rate")


def snapshot_to_rows(snap: dict) -> dict[str, list[dict]]:
    """Decompose a full snapshot into per-table row lists (pure)."""
    tree = snap.get("tree", {})
    econ = snap.get("econ", {})
    scoring = tree.get("scoring", {})

    node_rows, link_rows, linker_rows = [], [], []
    for ordn, n in enumerate(tree.get("nodes", [])):
        node_rows.append({
            "id": n["id"], "slug": n.get("slug", ""), "question": n.get("question", ""),
            "answer": n.get("answer", ""), "author": n.get("author", ""),
            "last_editor": n.get("last_editor", ""), "action": n.get("action", "root"),
            "status": n.get("status", "active"), "space": n.get("space", "public"),
            "parent_id": n.get("parent_id"), "stake": float(n.get("stake", 0.0)),
            "value_add": bool(n.get("value_add", True)), "frozen": bool(n.get("frozen", False)),
            "model": n.get("model", ""), "answered_at": n.get("answered_at", ""),
            "created_at": int(n.get("created_at", 0)), "updated_at": int(n.get("updated_at", 0)),
            "ord": ordn, "anchor": n.get("anchor", ""),
        })
        for i, target in enumerate(n.get("links", [])):
            link_rows.append({"node_id": n["id"], "ord": i, "target": target})

    for node_id, evaluators in scoring.get("linkers", {}).items():
        for i, ev in enumerate(evaluators):
            linker_rows.append({"node_id": node_id, "ord": i, "evaluator": ev})

    authority_rows = [{"node_id": k, "value": float(v)}
                      for k, v in scoring.get("authority", {}).items()]
    hub_rows = [{"account": k, "value": float(v)} for k, v in scoring.get("hub", {}).items()]

    stake_rows = [{"node_id": nid, "account": acct, "amount": float(amt)}
                  for nid, per in econ.get("staked", {}).items()
                  for acct, amt in per.items()]
    endorser_rows = [{"node_id": nid, "ord": i, "account": acct}
                     for nid, accts in econ.get("endorsers", {}).items()
                     for i, acct in enumerate(accts)]
    balance_rows = [{"account": k, "available": float(v)}
                    for k, v in econ.get("available", {}).items()]

    meta_rows = [
        {"k": "schema", "v": str(snap.get("schema", "unified-1"))},
        {"k": "tree_schema", "v": str(tree.get("schema", 1))},
        {"k": "scoring_mode", "v": str(scoring.get("mode", "harmonic"))},
        # Per-group private scorers are kept as a single JSON blob (small,
        # write-rarely) rather than parallel normalized tables — see
        # docs/design/05-private-public-endorse.md.
        {"k": "group_scoring", "v": json.dumps(tree.get("group_scoring", {}))},
        {"k": "clock", "v": str(tree.get("clock", 0))},
        {"k": "large_stake_threshold", "v": str(tree.get("large_stake_threshold", 25.0))},
        {"k": "burned", "v": str(econ.get("burned", 0.0))},
        {"k": "dividend_rate", "v": str(econ.get("dividend_rate", 0.20))},
        {"k": "burn_rate", "v": str(econ.get("burn_rate", 0.02))},
    ]
    return {"node": node_rows, "node_link": link_rows, "linker": linker_rows,
            "node_authority": authority_rows, "user_hub": hub_rows,
            "stake": stake_rows, "endorser": endorser_rows,
            "balance": balance_rows, "meta": meta_rows}


def rows_to_snapshot(tables: dict[str, list[dict]]) -> dict:
    """Reassemble a full snapshot from per-table rows (pure, inverse of above)."""
    meta = {r["k"]: r["v"] for r in tables.get("meta", [])}

    def num(k, default):
        v = meta.get(k)
        return type(default)(v) if v is not None else default

    links: dict[str, list[tuple[int, str]]] = {}
    for r in tables.get("node_link", []):
        links.setdefault(r["node_id"], []).append((r["ord"], r["target"]))

    nodes = sorted(tables.get("node", []), key=lambda r: r.get("ord", 0))
    # children = nodes grouped by parent, in stored order
    children: dict[str, list[str]] = {}
    for r in nodes:
        if r.get("parent_id"):
            children.setdefault(r["parent_id"], []).append(r["id"])

    node_jsons = []
    for r in nodes:
        node_jsons.append({
            "id": r["id"], "question": r.get("question", ""), "answer": r.get("answer", ""),
            "author": r.get("author", ""), "action": r.get("action", "root"),
            "parent_id": r.get("parent_id"), "stake": float(r.get("stake", 0.0)),
            "value_add": bool(r.get("value_add", True)), "created_at": int(r.get("created_at", 0)),
            "status": r.get("status", "active"), "children": children.get(r["id"], []),
            "slug": r.get("slug", ""),
            "links": [t for _o, t in sorted(links.get(r["id"], []))],
            "frozen": bool(r.get("frozen", False)), "model": r.get("model", ""),
            "answered_at": r.get("answered_at", ""), "space": r.get("space", "public"),
            "updated_at": int(r.get("updated_at", 0)), "last_editor": r.get("last_editor", ""),
            "anchor": r.get("anchor", ""),
        })

    linkers: dict[str, list[tuple[int, str]]] = {}
    for r in tables.get("linker", []):
        linkers.setdefault(r["node_id"], []).append((r["ord"], r["evaluator"]))

    staked: dict[str, dict[str, float]] = {}
    for r in tables.get("stake", []):
        staked.setdefault(r["node_id"], {})[r["account"]] = float(r["amount"])

    endorsers: dict[str, list[tuple[int, str]]] = {}
    for r in tables.get("endorser", []):
        endorsers.setdefault(r["node_id"], []).append((r["ord"], r["account"]))

    tree = {
        "schema": num("tree_schema", 1),
        "clock": num("clock", 0),
        "large_stake_threshold": num("large_stake_threshold", 25.0),
        "scoring": {
            "mode": meta.get("scoring_mode", "harmonic"),
            "authority": {r["node_id"]: float(r["value"]) for r in tables.get("node_authority", [])},
            "hub": {r["account"]: float(r["value"]) for r in tables.get("user_hub", [])},
            "linkers": {k: [e for _o, e in sorted(v)] for k, v in linkers.items()},
        },
        "group_scoring": json.loads(meta.get("group_scoring") or "{}"),
        "nodes": node_jsons,
    }
    econ = {
        "available": {r["account"]: float(r["available"]) for r in tables.get("balance", [])},
        "staked": staked,
        "endorsers": {k: [a for _o, a in sorted(v)] for k, v in endorsers.items()},
        "burned": num("burned", 0.0),
        "dividend_rate": num("dividend_rate", 0.20),
        "burn_rate": num("burn_rate", 0.02),
    }
    return {"schema": meta.get("schema", "unified-1"), "tree": tree, "econ": econ}


# --------------------------------------------------------------------------- #
# schema                                                                      #
# --------------------------------------------------------------------------- #
_DDL = [
    """CREATE TABLE IF NOT EXISTS node (
        id text PRIMARY KEY, slug text, question text, answer text,
        author text, last_editor text, action text, status text, space text,
        parent_id text, stake double precision, value_add boolean,
        frozen boolean, model text, answered_at text,
        created_at bigint, updated_at bigint, ord bigint, anchor text)""",
    # migration: add columns to a pre-existing node table (idempotent)
    "ALTER TABLE node ADD COLUMN IF NOT EXISTS anchor text",
    "CREATE INDEX IF NOT EXISTS node_author_idx ON node(author)",
    "CREATE INDEX IF NOT EXISTS node_space_idx ON node(space)",
    "CREATE INDEX IF NOT EXISTS node_parent_idx ON node(parent_id)",
    "CREATE TABLE IF NOT EXISTS node_link (node_id text, ord int, target text)",
    "CREATE INDEX IF NOT EXISTS node_link_target_idx ON node_link(target)",
    "CREATE TABLE IF NOT EXISTS linker (node_id text, ord int, evaluator text)",
    "CREATE TABLE IF NOT EXISTS node_authority (node_id text PRIMARY KEY, value double precision)",
    "CREATE TABLE IF NOT EXISTS user_hub (account text PRIMARY KEY, value double precision)",
    "CREATE TABLE IF NOT EXISTS stake (node_id text, account text, amount double precision,"
    " PRIMARY KEY (node_id, account))",
    "CREATE TABLE IF NOT EXISTS endorser (node_id text, ord int, account text)",
    "CREATE TABLE IF NOT EXISTS balance (account text PRIMARY KEY, available double precision)",
    "CREATE TABLE IF NOT EXISTS meta (k text PRIMARY KEY, v text)",
]

#: columns per table, in a stable order (used to build INSERTs generically)
_COLS = {
    "node": ["id", "slug", "question", "answer", "author", "last_editor", "action",
             "status", "space", "parent_id", "stake", "value_add", "frozen", "model",
             "answered_at", "created_at", "updated_at", "ord", "anchor"],
    "node_link": ["node_id", "ord", "target"],
    "linker": ["node_id", "ord", "evaluator"],
    "node_authority": ["node_id", "value"],
    "user_hub": ["account", "value"],
    "stake": ["node_id", "account", "amount"],
    "endorser": ["node_id", "ord", "account"],
    "balance": ["account", "available"],
    "meta": ["k", "v"],
}


def init(url: str) -> None:
    with _connect(url) as conn, conn.cursor() as cur:
        for stmt in _DDL:
            cur.execute(stmt)
        conn.commit()


def is_initialized(url: str) -> bool:
    """True once the normalized schema holds any node (i.e. migration ran)."""
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.node')")
        if cur.fetchone()[0] is None:
            return False
        cur.execute("SELECT 1 FROM meta LIMIT 1")
        return cur.fetchone() is not None


def load(url: str) -> Optional[dict]:
    """Reassemble the full snapshot from the normalized tables (or None if empty)."""
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM meta LIMIT 1")
        if cur.fetchone() is None:
            return None
        tables = {}
        for table, cols in _COLS.items():
            cur.execute(f"SELECT {', '.join(cols)} FROM {table}")
            tables[table] = [dict(zip(cols, row)) for row in cur.fetchall()]
    return rows_to_snapshot(tables)


def _write_rows(cur, snap: dict) -> None:
    """Replace all rows with the snapshot's (inside the caller's transaction).

    Full replace keeps the writer simple and correct; it runs under the advisory
    lock so it is atomic. ``node`` is the bulk of the data and is upserted by PK;
    the rest are small. (A future optimisation can diff only changed rows.)
    """
    rows = snapshot_to_rows(snap)
    for table, cols in _COLS.items():
        cur.execute(f"DELETE FROM {table}")
        data = rows[table]
        if not data:
            continue
        placeholders = ", ".join(["%s"] * len(cols))
        cur.executemany(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in cols) for r in data],
        )
    # stamp the write time so the UI can prove saves are landing
    cur.execute("INSERT INTO meta (k, v) VALUES ('saved_at', now()::text) "
                "ON CONFLICT (k) DO UPDATE SET v = now()::text")


@contextlib.contextmanager
def transaction(url: str):
    """Atomic read-modify-write across instances, like :func:`db.transaction`.

    Yields ``box``; ``box['data']`` is the current snapshot (reassembled from
    rows) and is written back as normalized rows in the same locked transaction.
    """
    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
            cur.execute("SELECT 1 FROM meta LIMIT 1")
            if cur.fetchone() is None:
                box = {"data": None}
            else:
                tables = {}
                for table, cols in _COLS.items():
                    cur.execute(f"SELECT {', '.join(cols)} FROM {table}")
                    tables[table] = [dict(zip(cols, row)) for row in cur.fetchall()]
                box = {"data": rows_to_snapshot(tables)}
            yield box
            if box["data"] is not None:
                _write_rows(cur, box["data"])
        conn.commit()
    finally:
        conn.close()


def save(url: str, snap: dict) -> None:
    """One-shot save (used for the initial blob→normalized migration)."""
    conn = _connect(url)
    try:
        with conn.cursor() as cur:
            _write_rows(cur, snap)
        conn.commit()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# point reads — touch only the rows needed, not the whole graph               #
# --------------------------------------------------------------------------- #
def wipe(url: str) -> None:
    """Delete ALL data — every normalized table *and* the legacy blob.

    Dropping ``nightwish_state`` is essential: if it survives, the next startup
    re-migrates it back and the "deleted" data reappears.
    """
    with _connect(url) as conn, conn.cursor() as cur:
        for table in _COLS:                      # node, node_link, … meta
            cur.execute(f"DELETE FROM {table}")
        cur.execute("DROP TABLE IF EXISTS nightwish_state")   # legacy blob → no re-seed
        conn.commit()


def meta_info(url: str) -> dict:
    """Last write time, for the durability indicator."""
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT v FROM meta WHERE k = 'saved_at'")
        row = cur.fetchone()
        return {"updated_at": row[0] if row else None}


def node_closure(url: str, node_id: str) -> Optional[dict]:
    """A *point read*: load only the rows needed to render one node's view.

    That closure = the node + its descendants (thread) + its ancestors (so a
    follow/fork's answer resolves up the chain) + nodes that wikilink to it
    (backlinks), plus the supporting link/linker/stake/endorser/authority rows
    for those nodes and the (small) hub table. Returns a partial snapshot the
    caller feeds to the normal view code — never loads the whole graph.
    """
    ncols = ", ".join(_COLS["node"])
    nsel = ", ".join("n." + c for c in _COLS["node"])
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {ncols} FROM node WHERE id = %s", (node_id,))
        if cur.fetchone() is None:
            return None
        # descendants (target + everything below it)
        cur.execute(
            f"WITH RECURSIVE sub AS ("
            f"  SELECT {ncols} FROM node WHERE id = %s"
            f"  UNION ALL SELECT {nsel} FROM node n JOIN sub ON n.parent_id = sub.id)"
            f" SELECT {ncols} FROM sub", (node_id,))
        sub = [dict(zip(_COLS["node"], r)) for r in cur.fetchall()]
        # ancestors (target + parents up to the root)
        cur.execute(
            f"WITH RECURSIVE anc AS ("
            f"  SELECT {ncols} FROM node WHERE id = %s"
            f"  UNION ALL SELECT {nsel} FROM node n JOIN anc ON anc.parent_id = n.id)"
            f" SELECT {ncols} FROM anc", (node_id,))
        anc = [dict(zip(_COLS["node"], r)) for r in cur.fetchall()]
        slug = next((r["slug"] for r in sub if r["id"] == node_id), None)
        back = []
        if slug:
            cur.execute(
                f"SELECT {ncols} FROM node WHERE id IN "
                f"(SELECT node_id FROM node_link WHERE target = %s)", (slug,))
            back = [dict(zip(_COLS["node"], r)) for r in cur.fetchall()]

        nodes = {r["id"]: r for r in (sub + anc + back)}
        # forward-link targets of THIS node, so its outlinks can show titles
        cur.execute("SELECT target FROM node_link WHERE node_id = %s", (node_id,))
        missing = [t for (t,) in cur.fetchall() if t not in nodes]
        if missing:
            cur.execute(f"SELECT {ncols} FROM node WHERE id = ANY(%s)", (missing,))
            for row in cur.fetchall():
                d = dict(zip(_COLS["node"], row))
                nodes[d["id"]] = d
        ids = list(nodes)

        def by_node(table):
            cols = _COLS[table]
            cur.execute(
                f"SELECT {', '.join(cols)} FROM {table} WHERE node_id = ANY(%s)", (ids,))
            return [dict(zip(cols, r)) for r in cur.fetchall()]

        link_rows = by_node("node_link")
        linker_rows = by_node("linker")
        auth_rows = by_node("node_authority")
        stake_rows = by_node("stake")
        endorser_rows = by_node("endorser")
        cur.execute("SELECT account, value FROM user_hub")          # small, load all
        hub_rows = [{"account": a, "value": v} for a, v in cur.fetchall()]
        cur.execute("SELECT k, v FROM meta")
        meta_rows = [{"k": k, "v": v} for k, v in cur.fetchall()]

    return rows_to_snapshot({
        "node": list(nodes.values()), "node_link": link_rows, "linker": linker_rows,
        "node_authority": auth_rows, "user_hub": hub_rows, "stake": stake_rows,
        "endorser": endorser_rows, "balance": [], "meta": meta_rows,
    })


def counts(url: str) -> dict:
    """Cheap aggregates for /api/state without loading every node."""
    with _connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM node WHERE action NOT IN ('pointer','query','stub')"
                    " AND NOT (author = '(stub)' AND coalesce(answer,'') = '')")
        node_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM node WHERE action = 'query'")
        query_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM node WHERE action = 'stub'"
                    " OR (author = '(stub)' AND coalesce(answer,'') = '')")
        stub_count = cur.fetchone()[0]
        cur.execute("SELECT v FROM meta WHERE k = 'scoring_mode'")
        row = cur.fetchone()
    return {"node_count": node_count, "query_count": query_count,
            "stub_count": stub_count, "hub_mode": row[0] if row else "harmonic"}
