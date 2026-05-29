"""JSON snapshot persistence for the service.

The MVP domain objects (:mod:`nightwish.tree`, :mod:`nightwish.economy`, …) are
plain in-memory dataclasses. To make a *service* — something that survives a
restart — we serialise the whole application state to a single JSON file and
restore it on startup. This is deliberately a flat-file snapshot, not a
database: it keeps the prototype dependency-free and the state human-readable
and diff-able. (A real deployment would swap this for SQLite/Postgres behind the
same :class:`AppState` interface.)

The snapshot is the single source of truth for what the service knows; every
mutating request re-saves it.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field

from nightwish.economy import Economy, Ledger
from nightwish.governance import Governance
from nightwish.scoring import ScoreEngine
from nightwish.tree import Action, Node, NodeStatus, OntologyTree
from nightwish.verification import Direction, Measurement, VerificationRegistry

SCHEMA_VERSION = 1


@dataclass
class AppState:
    """Everything the running service holds, wired together."""

    tree: OntologyTree
    economy: Economy
    verification: VerificationRegistry
    governance: Governance
    #: the hub-update rule in force (mirrors ``tree.scoring.mode``)
    hub_mode: str = "harmonic"

    @classmethod
    def fresh(cls, *, admin: str = "Json", hub_mode: str = "harmonic") -> "AppState":
        """A brand-new, empty state with a chosen scoring mode."""
        return cls(
            tree=OntologyTree(scoring=ScoreEngine(mode=hub_mode)),
            economy=Economy(),
            verification=VerificationRegistry(),
            governance=Governance(admin=admin),
            hub_mode=hub_mode,
        )


# --------------------------------------------------------------------------- #
# serialisation                                                               #
# --------------------------------------------------------------------------- #
def _node_to_dict(n: Node) -> dict:
    return {
        "id": n.id,
        "question": n.question,
        "answer": n.answer,
        "author": n.author,
        "action": n.action.value,
        "parent_id": n.parent_id,
        "stake": n.stake,
        "value_add": n.value_add,
        "created_at": n.created_at,
        "status": n.status.value,
        "children": list(n.children),
    }


def _node_from_dict(d: dict) -> Node:
    return Node(
        id=d["id"],
        question=d["question"],
        answer=d["answer"],
        author=d["author"],
        action=Action(d["action"]),
        parent_id=d.get("parent_id"),
        stake=d.get("stake", 0.0),
        value_add=d.get("value_add", True),
        created_at=d.get("created_at", 0),
        status=NodeStatus(d.get("status", "active")),
        children=list(d.get("children", [])),
    )


def _measurement_to_dict(m: Measurement) -> dict:
    return {
        "metric": m.metric,
        "baseline": m.baseline,
        "observed": m.observed,
        "direction": m.direction.value,
        "unit": m.unit,
        "min_rel_improvement": m.min_rel_improvement,
    }


def _measurement_from_dict(d: dict) -> Measurement:
    return Measurement(
        metric=d["metric"],
        baseline=d["baseline"],
        observed=d["observed"],
        direction=Direction(d.get("direction", "higher_better")),
        unit=d.get("unit", ""),
        min_rel_improvement=d.get("min_rel_improvement", 0.0),
    )


def to_json(state: AppState) -> dict:
    """Serialise the whole state into a JSON-able dict."""
    tree = state.tree
    sc = tree.scoring
    led = state.economy.ledger
    return {
        "schema": SCHEMA_VERSION,
        "hub_mode": state.hub_mode,
        "tree": {
            "clock": tree._clock,
            "large_stake_threshold": tree.large_stake_threshold,
            "nodes": [_node_to_dict(n) for n in tree.nodes.values()],
        },
        "scoring": {
            "mode": sc.mode,
            "authority": dict(sc.authority),
            "hub": dict(sc.hub),
            "linkers": {k: list(v) for k, v in sc._linkers.items()},
        },
        "economy": {
            "dividend_rate": state.economy.dividend_rate,
            "burn_rate": state.economy.burn_rate,
            "reclaimed": {k: dict(v) for k, v in state.economy._reclaimed.items()},
            "ledger": {
                "available": dict(led.available),
                "staked": {k: dict(v) for k, v in led.staked.items()},
                "escrow": {k: list(v) for k, v in led.escrow.items()},
                "burned": led.burned,
                "liquidity_pool": led.liquidity_pool,
            },
        },
        "verification": {
            node_id: [_measurement_to_dict(m) for m in ms]
            for node_id, ms in state.verification.results.items()
        },
        "governance": {
            "admin": state.governance.admin,
            "decentralize_at": state.governance.decentralize_at,
            "council_quorum": state.governance.council_quorum,
            "rules": dict(state.governance.rules),
            "participants": sorted(state.governance.participants),
            "council": sorted(state.governance.council),
            "log": list(state.governance.log),
        },
    }


def from_json(data: dict) -> AppState:
    """Rebuild an :class:`AppState` from a snapshot dict."""
    hub_mode = data.get("hub_mode", "harmonic")

    sc_data = data.get("scoring", {})
    scoring = ScoreEngine(mode=sc_data.get("mode", hub_mode))
    scoring.authority = defaultdict(float, sc_data.get("authority", {}))
    scoring.hub = defaultdict(float, sc_data.get("hub", {}))
    scoring._linkers = defaultdict(
        list, {k: list(v) for k, v in sc_data.get("linkers", {}).items()}
    )

    tree_data = data.get("tree", {})
    tree = OntologyTree(
        scoring=scoring,
        large_stake_threshold=tree_data.get("large_stake_threshold", 25.0),
    )
    tree._clock = tree_data.get("clock", 0)
    tree.nodes = {n["id"]: _node_from_dict(n) for n in tree_data.get("nodes", [])}

    eco_data = data.get("economy", {})
    led_data = eco_data.get("ledger", {})
    ledger = Ledger(
        available=defaultdict(float, led_data.get("available", {})),
        staked=defaultdict(
            lambda: defaultdict(float),
            {k: defaultdict(float, v) for k, v in led_data.get("staked", {}).items()},
        ),
        escrow={k: tuple(v) for k, v in led_data.get("escrow", {}).items()},
        burned=led_data.get("burned", 0.0),
        liquidity_pool=led_data.get("liquidity_pool", 0.0),
    )
    economy = Economy(
        ledger=ledger,
        dividend_rate=eco_data.get("dividend_rate", 0.20),
        burn_rate=eco_data.get("burn_rate", 0.02),
        _reclaimed={
            k: dict(v) for k, v in eco_data.get("reclaimed", {}).items()
        },
    )

    verification = VerificationRegistry()
    for node_id, ms in data.get("verification", {}).items():
        verification.results[node_id] = [_measurement_from_dict(m) for m in ms]

    gov_data = data.get("governance", {})
    governance = Governance(
        admin=gov_data.get("admin", "Json"),
        decentralize_at=gov_data.get("decentralize_at", 100),
        council_quorum=gov_data.get("council_quorum", 0.5),
        rules=dict(gov_data.get("rules", {})),
        participants=set(gov_data.get("participants", [])),
        council=set(gov_data.get("council", [])),
        log=list(gov_data.get("log", [])),
    )

    return AppState(
        tree=tree,
        economy=economy,
        verification=verification,
        governance=governance,
        hub_mode=hub_mode,
    )


# --------------------------------------------------------------------------- #
# file I/O                                                                    #
# --------------------------------------------------------------------------- #
def save(state: AppState, path: str) -> None:
    """Atomically write the snapshot to ``path``."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(to_json(state), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)  # atomic on POSIX
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load(path: str) -> AppState | None:
    """Load a snapshot from ``path``, or ``None`` if it does not exist."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return from_json(json.load(fh))
