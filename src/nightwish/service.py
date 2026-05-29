"""HTTP service for the living-ontology system (design §6 made runnable).

A thin FastAPI layer over the in-memory domain library. It holds one
:class:`~nightwish.store.AppState`, persists every mutation to a JSON snapshot,
and exposes the three-stage query flow plus the tree actions (follow / fork /
contribute), staking, dividends, and ground-truth verification.

The AI used by stage ② is **pluggable**. By default an offline, deterministic
stub answers (so the service runs with no API key and no network — important in
locked-down environments). Wire a real model with :func:`set_ai`.

Run it::

    pip install -e ".[service]"
    nightwish-serve                 # or: uvicorn nightwish.service:app --reload

then open http://127.0.0.1:8000/ .
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nightwish import store
from nightwish.pipeline import QueryPipeline, Stage
from nightwish.scoring import HUB_MODES
from nightwish.store import AppState
from nightwish.tree import Action, OntologyError
from nightwish.verification import Direction, Measurement

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_DB = os.environ.get("NIGHTWISH_DB", "data/state.json")


# --------------------------------------------------------------------------- #
# pluggable AI (stage ②)                                                      #
# --------------------------------------------------------------------------- #
def offline_ai(question: str) -> Optional[str]:
    """Deterministic offline answer.

    Returns ``None`` (AI declines → stage ③) when the question is flagged as
    tacit knowledge with the ``[tacit]`` marker — this lets the demo exercise
    the human-routing path without a real model.
    """
    if "[tacit]" in question.lower():
        return None
    return (
        f"(AI 초안) '{question.strip()}' 에 대한 합성 답변입니다. "
        "사람의 검증·포크·기여로 정제되며, 채택된 가지가 다음 질문의 답이 됩니다."
    )


#: the current AI callable; swap with :func:`set_ai`
_ai_fn: Callable[[str], Optional[str]] = offline_ai


def set_ai(fn: Callable[[str], Optional[str]]) -> None:
    """Install a real AI backend (e.g. a Claude call). Must return str or None."""
    global _ai_fn
    _ai_fn = fn


def _search(question: str, tree) -> Optional[str]:
    """Stage ①: cheapest possible search of the existing human ontology.

    Exact-question match first, then substring overlap. Returns the best
    existing answer node id, or ``None`` if the ontology cannot answer yet.
    """
    q = question.strip().lower()
    if not q:
        return None
    best: Optional[str] = None
    best_authority = -1.0
    for node in tree.nodes.values():
        if not node.is_answer:
            continue
        nq = node.question.strip().lower()
        if nq == q or (len(q) > 8 and (q in nq or nq in q)):
            a = tree.scoring.authority_of(node.id)
            if a > best_authority:
                best, best_authority = node.id, a
    return best


# --------------------------------------------------------------------------- #
# state + persistence                                                         #
# --------------------------------------------------------------------------- #
class Service:
    """Owns the :class:`AppState`, a lock, and snapshot persistence."""

    def __init__(self, db_path: str = DEFAULT_DB, *, hub_mode: str = "harmonic"):
        self.db_path = db_path
        self._lock = threading.RLock()
        loaded = store.load(db_path)
        self.state: AppState = loaded or AppState.fresh(hub_mode=hub_mode)

    def save(self) -> None:
        store.save(self.state, self.db_path)

    def pipeline(self) -> QueryPipeline:
        return QueryPipeline(
            tree=self.state.tree,
            search_fn=_search,
            ask_ai_fn=_ai_fn,
            route_to_human_fn=lambda q: None,  # humans answer via /contribute
        )


_service: Optional[Service] = None


def get_service() -> Service:
    global _service
    if _service is None:
        _service = Service()
    return _service


def reset_service(db_path: str, *, hub_mode: str = "harmonic") -> Service:
    """(Re)initialise the global service — used by tests for isolation."""
    global _service
    _service = Service(db_path, hub_mode=hub_mode)
    return _service


# --------------------------------------------------------------------------- #
# request / response models                                                   #
# --------------------------------------------------------------------------- #
class AskBody(BaseModel):
    question: str
    asker: str
    parent_id: Optional[str] = None
    ai_stake: float = 0.0
    human_stake: float = 0.0
    node_id: Optional[str] = None


class FollowBody(BaseModel):
    follower: str
    stake: float = Field(gt=0)
    node_id: Optional[str] = None


class ForkBody(BaseModel):
    author: str
    answer: str
    stake: float = Field(ge=0)
    question: Optional[str] = None
    node_id: Optional[str] = None


class ContributeBody(BaseModel):
    author: str
    answer: str
    stake: float = Field(ge=0)
    value_add: bool = True
    question: Optional[str] = None
    node_id: Optional[str] = None


class MintBody(BaseModel):
    account: str
    amount: float = Field(gt=0)


class VerifyBody(BaseModel):
    metric: str
    baseline: float
    observed: float
    direction: Direction = Direction.HIGHER_BETTER
    unit: str = ""
    min_rel_improvement: float = 0.0


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _node_view(svc: Service, node_id: str) -> dict:
    tree = svc.state.tree
    n = tree.nodes[node_id]
    return {
        "id": n.id,
        "question": n.question,
        "answer": n.answer,
        "author": n.author,
        "action": n.action.value,
        "parent_id": n.parent_id,
        "stake": n.stake,
        "value_add": n.value_add,
        "status": n.status.value,
        "created_at": n.created_at,
        "children": list(n.children),
        "authority": round(tree.scoring.authority_of(n.id), 4),
        "verified": svc.state.verification.is_verified(n.id),
    }


def _next_id(svc: Service, prefix: str) -> str:
    return f"{prefix}-{svc.state.tree._clock + 1:04d}"


# --------------------------------------------------------------------------- #
# app                                                                         #
# --------------------------------------------------------------------------- #
def create_app() -> FastAPI:
    app = FastAPI(title="Nightwish — living ontology", version="0.1.0")

    @app.get("/api/state")
    def state_summary():
        svc = get_service()
        with svc._lock:
            tree = svc.state.tree
            led = svc.state.economy.ledger
            return {
                "hub_mode": svc.state.hub_mode,
                "hub_modes": list(HUB_MODES),
                "phase": svc.state.governance.phase.value,
                "node_count": len(tree.nodes),
                "root_count": len(tree.roots()),
                "supply_available": round(sum(led.available.values()), 4),
                "burned": round(led.burned, 4),
                "liquidity_pool": round(led.liquidity_pool, 4),
            }

    @app.post("/api/ask")
    def ask(body: AskBody):
        svc = get_service()
        with svc._lock:
            svc.state.governance.register(body.asker)
            node_id = body.node_id or _next_id(svc, "q")
            try:
                result = svc.pipeline().ask(
                    body.question,
                    asker=body.asker,
                    new_node_id=node_id,
                    parent_id=body.parent_id,
                    ai_stake=body.ai_stake,
                    human_stake=body.human_stake,
                )
            except OntologyError as e:
                raise HTTPException(400, str(e))
            svc.save()
            return {
                "stage": result.stage.value,
                "answer": result.answer,
                "node": _node_view(svc, result.node_id) if result.node_id else None,
                "resolved": result.stage is not Stage.UNRESOLVED,
            }

    @app.get("/api/tree")
    def tree_view():
        svc = get_service()
        with svc._lock:
            return {
                "roots": [n.id for n in svc.state.tree.roots()],
                "nodes": [_node_view(svc, nid) for nid in svc.state.tree.nodes],
            }

    @app.get("/api/nodes/{node_id}")
    def node_detail(node_id: str):
        svc = get_service()
        with svc._lock:
            if node_id not in svc.state.tree.nodes:
                raise HTTPException(404, f"unknown node {node_id!r}")
            view = _node_view(svc, node_id)
            view["ancestors"] = [a.id for a in svc.state.tree.ancestors(node_id)]
            view["linkers"] = svc.state.tree.scoring.link_order(node_id)
            return view

    def _materialise_action(action: str, parent_id: str, body, fn):
        svc = get_service()
        with svc._lock:
            if parent_id not in svc.state.tree.nodes:
                raise HTTPException(404, f"unknown node {parent_id!r}")
            svc.state.governance.register(getattr(body, "author", None)
                                          or getattr(body, "follower"))
            nid = body.node_id or _next_id(svc, action)
            try:
                node = fn(svc, nid, parent_id, body)
            except OntologyError as e:
                raise HTTPException(400, str(e))
            svc.save()
            return _node_view(svc, node.id)

    @app.post("/api/nodes/{parent_id}/follow")
    def follow(parent_id: str, body: FollowBody):
        return _materialise_action(
            "follow", parent_id, body,
            lambda svc, nid, pid, b: svc.state.tree.follow(nid, pid, b.follower, b.stake),
        )

    @app.post("/api/nodes/{parent_id}/fork")
    def fork(parent_id: str, body: ForkBody):
        return _materialise_action(
            "fork", parent_id, body,
            lambda svc, nid, pid, b: svc.state.tree.fork(
                nid, pid, b.author, b.answer, b.stake, question=b.question),
        )

    @app.post("/api/nodes/{parent_id}/contribute")
    def contribute(parent_id: str, body: ContributeBody):
        return _materialise_action(
            "contribute", parent_id, body,
            lambda svc, nid, pid, b: svc.state.tree.contribute(
                nid, pid, b.author, b.answer, b.stake,
                question=b.question, value_add=b.value_add),
        )

    @app.post("/api/nodes/{node_id}/verify")
    def verify(node_id: str, body: VerifyBody):
        svc = get_service()
        with svc._lock:
            if node_id not in svc.state.tree.nodes:
                raise HTTPException(404, f"unknown node {node_id!r}")
            m = Measurement(
                metric=body.metric, baseline=body.baseline, observed=body.observed,
                direction=body.direction, unit=body.unit,
                min_rel_improvement=body.min_rel_improvement,
            )
            passed = svc.state.verification.record(node_id, m)
            svc.save()
            return {
                "node_id": node_id,
                "passed": passed,
                "relative_improvement": round(m.relative_improvement, 4),
                "verified": svc.state.verification.is_verified(node_id),
            }

    @app.post("/api/mint")
    def mint(body: MintBody):
        svc = get_service()
        with svc._lock:
            svc.state.governance.register(body.account)
            svc.state.economy.ledger.mint(body.account, body.amount)
            svc.save()
            return {"account": body.account,
                    "balance": svc.state.economy.ledger.balance(body.account)}

    @app.get("/api/ledger")
    def ledger():
        svc = get_service()
        with svc._lock:
            led = svc.state.economy.ledger
            return {
                "available": {k: round(v, 4) for k, v in led.available.items() if v},
                "staked_by_node": {
                    k: {a: round(s, 4) for a, s in v.items()}
                    for k, v in led.staked.items() if v
                },
                "burned": round(led.burned, 4),
                "liquidity_pool": round(led.liquidity_pool, 4),
            }

    @app.get("/api/scores")
    def scores():
        svc = get_service()
        with svc._lock:
            sc = svc.state.tree.scoring
            hubs = sorted(sc.hub.items(), key=lambda kv: -kv[1])
            auths = sorted(sc.authority.items(), key=lambda kv: -kv[1])
            return {
                "mode": sc.mode,
                "hub_ranking": [{"evaluator": k, "hub": round(v, 4)}
                                for k, v in hubs if v],
                "authority_ranking": [{"node": k, "authority": round(v, 4)}
                                      for k, v in auths if v],
            }

    # static web UI -------------------------------------------------------- #
    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()


def main() -> None:
    """Console entrypoint: ``nightwish-serve``."""
    import uvicorn

    host = os.environ.get("NIGHTWISH_HOST", "127.0.0.1")
    port = int(os.environ.get("NIGHTWISH_PORT", "8000"))
    uvicorn.run("nightwish.service:app", host=host, port=port, reload=False)
