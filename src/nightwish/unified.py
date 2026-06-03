"""The unified Nightwish app — one recursive knowledge graph, one HTTP surface.

This is the single app the two earlier prototypes (``mvp`` wiki + ``service``
ontology) converge into. Everything is one :class:`~nightwish.tree.Node`:

* a question/answer page, an open query, a link-stub, an AI answer, and every
  follow/fork/contribution on a thread — all the *same* node kind, so the same
  "ask → answer → augment / follow-up / correct / fork" module applies to **any**
  slot that needs filling, recursively (an answer is itself a slot);
* layers (``space``: public commons + group overlays, one-way membrane);
* wikilinks (``[[Title]]``) that auto-create stubs and accrue authority;
* a light point economy (:class:`~nightwish.wiki_economy.WikiEconomy`): mint +
  endorse-with-dividend, keyed by node id.

Run it::

    nightwish-app            # or: uvicorn nightwish.unified:app --reload
"""

from __future__ import annotations

import contextlib
import json
import os
import threading
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nightwish.tree import Action, OntologyError, OntologyTree, slugify
from nightwish.wiki_economy import InsufficientPoints, WikiEconomy

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_DB = os.environ.get("NIGHTWISH_APP_DB", "data/app.json")


# --------------------------------------------------------------------------- #
# pluggable AI (offline-deterministic by default — no key/network needed)     #
# --------------------------------------------------------------------------- #
def offline_answer(question: str, prompt: str = "") -> str:
    q = question.strip()
    return (
        f"(AI 초안) '{q}' 에 대한 합성 답변입니다. "
        "사람의 보강·정정·후속질문으로 정제되며, 채택된 가지가 다음 질문의 답이 됩니다. "
        "관련 개념은 [[관련 개념]] 으로 연결하세요."
    )


_ai_fn: Callable[[str, str], str] = offline_answer
_ai_model: str = "offline-stub"


def set_ai(fn: Callable[[str, str], str], *, model: str = "custom") -> None:
    """Install a real LLM backend. Signature: ``fn(question, prompt) -> markdown``."""
    global _ai_fn, _ai_model
    _ai_fn, _ai_model = fn, model


def configure_ai() -> bool:
    """Activate the Claude backend if ``NIGHTWISH_ENABLE_LLM`` + key are present."""
    if os.environ.get("NIGHTWISH_ENABLE_LLM", "").lower() not in ("1", "true", "yes"):
        return False
    try:
        from nightwish.llm import DEFAULT_MODEL, make_draft_fn

        draft = make_draft_fn()
        if draft is not None:
            set_ai(draft, model=DEFAULT_MODEL)
            return True
    except Exception:
        pass
    return False


def configure_embeddings() -> bool:
    """Activate a real embedding backend for semantic search if configured.

    No-op (offline deterministic embedding stays in place) unless
    ``NIGHTWISH_ENABLE_EMBEDDINGS`` + an embeddings API key are present.
    """
    try:
        from nightwish.embeddings import make_embed_fn
        from nightwish.search import set_embedder

        fn = make_embed_fn()
        if fn is not None:
            set_embedder(fn)
            return True
    except Exception:
        pass
    return False


def _ask_ai(question: str, prompt: str = "") -> str:
    try:
        return _ai_fn(question, prompt)
    except Exception:
        return offline_answer(question, prompt)


def _ai_status() -> dict:
    """Whether the real LLM is active — so the UI can show stub vs Claude."""
    active = _ai_model != "offline-stub"
    return {
        "model": _ai_model,
        "active": active,
        "hint": "" if active else
                "오프라인 스텁 — 실제 LLM을 켜려면 NIGHTWISH_ENABLE_LLM=1 + ANTHROPIC_API_KEY",
    }


def _anchor_prompt(tree, node_id: str) -> str:
    """Context for a follow-up: the chain of Q&A from the root down to this node,
    so the AI answers *in the thread* instead of treating it as a fresh question.
    """
    chain, cur, seen = [], node_id, set()
    while cur and cur in tree.nodes and cur not in seen:
        seen.add(cur)
        chain.append(tree.nodes[cur])
        cur = tree.nodes[cur].parent_id
    chain.reverse()
    parts = []
    for n in chain:
        q = (n.question or "").strip()
        a = (tree.resolved_answer(n.id) or "").strip()
        if q:
            parts.append(f"질문: {q}")
        if a:
            parts.append(f"답변: {a}")
    if not parts:
        return ""
    return ("아래는 지금까지의 질문·답변 맥락이다. 이 맥락에 이어지는 후속 질문에, "
            "앞 내용을 전제로 일관되게 답하라.\n\n" + "\n".join(parts))


# --------------------------------------------------------------------------- #
# service: state + persistence                                                #
# --------------------------------------------------------------------------- #
class UnifiedService:
    """Owns the knowledge graph + economy, a lock, and snapshot persistence."""

    def __init__(self, db_path: str = DEFAULT_DB, *, hub_mode: str = "harmonic"):
        self.db_path = db_path
        self._lock = threading.RLock()
        self._seq = 0
        tree, econ = self._load(db_path, hub_mode)
        self.tree, self.econ = tree, econ

    # -- persistence ----------------------------------------------------------
    @staticmethod
    def _load(path: str, hub_mode: str) -> tuple[OntologyTree, WikiEconomy]:
        # Durable first: on Railway (DATABASE_URL set) the local disk is
        # *ephemeral* — it's wiped on every restart/redeploy, which silently
        # drops freshly-asked nodes (endorse/follow-up then 404 against a node
        # the browser still shows). So persist to Postgres when available,
        # exactly like ``nightwish-mvp`` does, and fall back to a local file
        # only for offline/dev runs.
        from nightwish import db, pgstore

        url = db.database_url()
        if url:
            pgstore.init(url)
            snapshot = pgstore.load(url)
            if snapshot is None:
                # One-time migration: if the old single-row JSONB blob exists,
                # fan it out into the normalized tables (the blob is left intact
                # for rollback). Otherwise seed fresh.
                db.init(url)
                blob = db.load(url)
                if blob is not None:
                    pgstore.save(url, blob)
                    snapshot = pgstore.load(url)
            if snapshot is not None:
                return UnifiedService._from_data(snapshot)
            return UnifiedService._seed(path, hub_mode)
        if os.path.exists(path):
            return UnifiedService._from_file(path)
        return UnifiedService._seed(path, hub_mode)

    @staticmethod
    def _seed(path: str, hub_mode: str) -> tuple[OntologyTree, WikiEconomy]:
        # Cutover convenience: if there's a legacy ``wiki.json`` from the old MVP
        # next to where the unified snapshot would live, seed from it (migrating
        # the flat thread onto the recursive model). The legacy file is left
        # untouched — the unified app writes forward, so rolling back still works.
        legacy = os.path.join(os.path.dirname(os.path.abspath(path)), "wiki.json")
        if os.path.abspath(legacy) != os.path.abspath(path) and os.path.exists(legacy):
            return UnifiedService._from_file(legacy)
        from nightwish.scoring import ScoreEngine

        return OntologyTree(scoring=ScoreEngine(mode=hub_mode)), WikiEconomy()

    @staticmethod
    def _from_file(path: str) -> tuple[OntologyTree, WikiEconomy]:
        with open(path, encoding="utf-8") as fh:
            return UnifiedService._from_data(json.load(fh))

    @staticmethod
    def _from_data(data: dict) -> tuple[OntologyTree, WikiEconomy]:
        if "tree" in data:  # native unified snapshot
            return (
                OntologyTree.from_json(data["tree"]),
                WikiEconomy.from_json(data.get("econ", {})),
            )
        # legacy wiki/mvp snapshot (flat pages) → migrate onto the unified model
        wiki = data.get("wiki", data)
        econ = WikiEconomy.from_json(data.get("econ", data.get("economy", {})))
        return OntologyTree.from_wiki_json(wiki), econ

    def _snapshot(self) -> dict:
        return {"schema": "unified-1", "tree": self.tree.to_json(),
                "econ": self.econ.to_json()}

    def _install(self, data: Optional[dict]) -> None:
        """Replace in-memory state from a snapshot (or seed if empty)."""
        if data is None:
            self.tree, self.econ = self._seed(self.db_path, self.tree.scoring.mode)
        else:
            self.tree, self.econ = self._from_data(data)

    def save(self) -> None:
        from nightwish import db, pgstore

        url = db.database_url()
        if url:
            pgstore.save(url, self._snapshot())
            return
        directory = os.path.dirname(os.path.abspath(self.db_path))
        os.makedirs(directory, exist_ok=True)
        tmp = self.db_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._snapshot(), fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.db_path)

    # -- request-scoped state access ------------------------------------------
    # In DB mode the snapshot — not this process's memory — is the source of
    # truth, because several instances (or a redeploy race) may share it. Reads
    # reload the latest; writes reload-mutate-save atomically under a DB lock so
    # a stale instance can never clobber another's data.
    @contextlib.contextmanager
    def reading(self):
        from nightwish import db, pgstore

        url = db.database_url()
        with self._lock:
            if url:
                self._install(pgstore.load(url))
            yield

    @contextlib.contextmanager
    def writing(self):
        from nightwish import db, pgstore

        url = db.database_url()
        with self._lock:
            if url:
                with pgstore.transaction(url) as box:
                    self._install(box["data"])
                    yield
                    box["data"] = self._snapshot()
            else:
                yield
                self.save()

    # -- id minting -----------------------------------------------------------
    def persistence_info(self) -> dict:
        """What backend writes actually go to — so the UI can prove durability.

        On an ephemeral host (Railway) ``file`` mode means data is lost on every
        restart; ``postgres`` mode means it survives. If ``DATABASE_URL`` is set
        we also ping the DB so a misconfigured/unreachable Postgres surfaces as
        an explicit error instead of silent data loss.
        """
        from nightwish import db, pgstore

        url = db.database_url()
        if not url:
            return {"backend": "file", "durable": False, "path": self.db_path,
                    "hint": "DATABASE_URL 미설정 — 임시 파일에 저장, 재시작 시 유실됨"}
        info = {"backend": "postgres (normalized)", "durable": True}
        try:
            info["last_saved_at"] = pgstore.meta_info(url).get("updated_at")
            info["db_ok"] = True
        except Exception as e:  # noqa: BLE001 — report, don't crash the page
            info.update(durable=False, db_ok=False, error=str(e))
        return info

    def _new_id(self, base: str) -> str:
        slug = slugify(base) or "node"
        if slug not in self.tree.nodes:
            return slug
        self._seq += 1
        cand = f"{slug}-{self._seq}"
        while cand in self.tree.nodes:
            self._seq += 1
            cand = f"{slug}-{self._seq}"
        return cand

    def _child_id(self, parent_id: str) -> str:
        self._seq += 1
        cand = f"{parent_id}~{self._seq}"
        while cand in self.tree.nodes:
            self._seq += 1
            cand = f"{parent_id}~{self._seq}"
        return cand


_service: Optional[UnifiedService] = None


def get_service() -> UnifiedService:
    global _service
    if _service is None:
        _service = UnifiedService()
    return _service


def reset_service(svc: Optional[UnifiedService]) -> None:
    """Test hook: install (or clear) the process-wide service."""
    global _service
    _service = svc


# --------------------------------------------------------------------------- #
# request bodies                                                              #
# --------------------------------------------------------------------------- #
class AskBody(BaseModel):
    question: str = Field(min_length=1)
    author: str = Field(min_length=1)
    space: str = "public"
    force: bool = False  # True면 동일 채택본이 있어도 새 답을 강제 생성


class PageBody(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    author: str = Field(min_length=1)
    space: str = "public"


class ContribBody(BaseModel):
    kind: str = "comment"  # comment | fork | follow | followup
    author: str = Field(min_length=1)
    body: str = ""
    space: str = "public"


class QueryBody(BaseModel):
    title: str = Field(min_length=1)
    detail: str = ""
    author: str = Field(min_length=1)
    space: str = "public"


class AnswerBody(BaseModel):
    body: str = ""
    author: str = Field(min_length=1)
    ai: bool = False
    space: str = "public"


class FillBody(BaseModel):
    author: str = Field(min_length=1)
    space: str = "public"


class MintBody(BaseModel):
    account: str = Field(min_length=1)
    amount: float = Field(gt=0)


class EndorseBody(BaseModel):
    account: str = Field(min_length=1)
    node_id: str = Field(min_length=1)
    amount: float = Field(gt=0)
    #: "public" spends the common coin (commons authority); a group space spends
    #: free-issue, non-convertible group coin (group-only authority overlay).
    space: str = "public"


class ExpandBody(BaseModel):
    question: str = Field(min_length=1)   # the dragged text, or a refined question
    author: str = Field(min_length=1)
    space: str = "public"


# --------------------------------------------------------------------------- #
# views                                                                       #
# --------------------------------------------------------------------------- #
class _ReadView:
    """Minimal stand-in carrying just ``tree``/``econ`` for the view helpers.

    Lets point reads render a node from a *partial* graph (its closure) using the
    same :func:`_node_view`/`_thread`/`_coauthors` code as the full service.
    """

    __slots__ = ("tree", "econ")

    def __init__(self, tree, econ):
        self.tree, self.econ = tree, econ


def _coauthors(svc: UnifiedService, node_id: str) -> list[dict]:
    """The node's authorship: the original author, then evaluators in order.

    Endorsing (evaluating) a Q&A links the evaluator to it, so the people who
    *recognised* the knowledge co-author it — earliest first, each tagged with
    the foresight(hub) their evaluation earned.
    """
    t = svc.tree
    n = t.nodes[node_id]
    chain: list[dict] = [{"user": n.author, "role": "author",
                          "hub": round(t.scoring.hub_of(n.author), 4)}]
    for ev in t.scoring.link_order(node_id):
        if ev == n.author:
            continue
        chain.append({"user": ev, "role": "evaluator",
                      "hub": round(t.scoring.hub_of(ev), 4),
                      "staked": round(svc.econ.staked_on(node_id).get(ev, 0.0), 4)})
    return chain


def _node_view(svc: UnifiedService, node_id: str, space: str, *, full: bool = False) -> dict:
    t = svc.tree
    n = t.nodes[node_id]
    view = {
        "id": n.id, "slug": n.slug, "title": n.question,
        "answer": t.resolved_answer(n.id), "own_answer": n.answer,
        "author": n.author, "last_editor": n.last_editor,
        "action": n.action.value, "status": n.status.value,
        "is_stub": n.is_stub, "is_query": n.is_query, "frozen": n.frozen,
        "model": n.model, "answered_at": n.answered_at, "space": n.space,
        "links": list(n.links), "updated_at": n.updated_at,
        "authority": round(t.authority_in(n.id, space), 4),
        "staked": round(sum(svc.econ.staked_on(n.id).values()), 4),
        "coauthors": _coauthors(svc, n.id),
    }
    # 채택 = 사람이 평가(스테이크)한 답. 평가 전 AI 초안은 검색엔 보이되 '초안'으로 표시.
    view["adopted"] = view["staked"] > 0
    if full:
        view["thread"] = _thread(svc, n.id, space)
        view["backlinks"] = [
            {"id": b.id, "title": b.question} for b in t.backlinks(n.id, space)
        ]
        view["outlinks"] = [
            {"id": s, "title": t.nodes[s].question}
            for s in n.links if s in t.nodes and t._visible(t.nodes[s], space)
        ]
    return view


def _thread(svc: UnifiedService, node_id: str, space: str) -> list[dict]:
    """Recursive contribution thread visible in ``space`` (stubs excluded)."""
    t = svc.tree
    out = []
    for child in t.children_of(node_id):
        if not t._visible(child, space) or child.is_stub:
            continue
        out.append({
            "id": child.id, "kind": child.action.value, "author": child.author,
            "title": child.question, "body": child.answer,
            "frozen": child.frozen, "model": child.model, "space": child.space,
            "authority": round(t.authority_in(child.id, space), 4),
            "staked": round(sum(svc.econ.staked_on(child.id).values()), 4),
            "replies": _thread(svc, child.id, space),
        })
    return out


# --------------------------------------------------------------------------- #
# app                                                                         #
# --------------------------------------------------------------------------- #
def create_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        configure_ai()
        configure_embeddings()
        yield

    app = FastAPI(title="Nightwish — unified knowledge graph", version="1.0.0",
                  lifespan=lifespan)

    @app.middleware("http")
    async def no_cache_api(request, call_next):
        """Never let the browser cache API reads — otherwise a freshly-saved
        node can be hidden behind a stale cached GET and look 'unsaved'."""
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/admin/reset")
    def admin_reset(confirm: str = ""):
        """Wipe ALL data (and the legacy blob, so nothing re-seeds). Destructive.

        Requires ``?confirm=DELETE-ALL``. Leaves an empty, fresh graph.
        """
        if confirm != "DELETE-ALL":
            raise HTTPException(400, "confirm=DELETE-ALL 필요 (전체 삭제 확인)")
        from nightwish import db, pgstore
        from nightwish.scoring import ScoreEngine

        svc = get_service()
        url = db.database_url()
        with svc._lock:
            if url:
                pgstore.wipe(url)
                pgstore.init(url)          # recreate empty tables
            elif os.path.exists(svc.db_path):
                os.remove(svc.db_path)
            svc.tree = OntologyTree(scoring=ScoreEngine(mode="harmonic"))
            svc.econ = WikiEconomy()
            svc._seq = 0
        return {"reset": True, "node_count": 0}

    @app.get("/api/dbcheck")
    def dbcheck():
        """Prove writes actually reach Postgres — write a probe, read it back.

        Open this URL in a browser: ``ok: true`` with a fresh ``wrote_at`` means
        the DB accepts writes (so any data loss is a deploy/config issue, not the
        DB). An ``error`` is the exact Postgres failure. In file mode it reports
        that no durable DB is configured.
        """
        from nightwish import db

        url = db.database_url()
        if not url:
            return {"backend": "file", "durable": False,
                    "hint": "DATABASE_URL 미설정 — 영속 DB 없음(임시 파일)"}
        try:
            from nightwish import pgstore

            result = db.selftest(url)
            result["backend"] = "postgres (normalized)"
            result["last_saved_at"] = pgstore.meta_info(url).get("updated_at")
            result["row_counts"] = pgstore.counts(url)
            return result
        except Exception as e:  # noqa: BLE001 — surface the real reason
            return {"backend": "postgres", "ok": False, "error": str(e)}

    @app.get("/api/state")
    def state():
        svc = get_service()
        from nightwish import db, pgstore

        url = db.database_url()
        if url:
            # point query — count rows in SQL, never load the whole graph
            try:
                c = pgstore.counts(url)
                return {**c, "persistence": svc.persistence_info(), "ai": _ai_status()}
            except Exception:  # noqa: BLE001 — fall back to in-memory below
                pass
        with svc.reading():
            real = [n for n in svc.tree.nodes.values()
                    if n.is_answer and not n.is_stub]
            return {
                "hub_mode": svc.tree.scoring.mode,
                "node_count": len(real),
                "stub_count": sum(1 for n in svc.tree.nodes.values() if n.is_stub),
                "query_count": len(svc.tree.open_queries()),
                "persistence": svc.persistence_info(),
                "ai": _ai_status(),
            }

    @app.get("/api/nodes")
    def list_nodes(space: str = "public"):
        svc = get_service()
        with svc.reading():
            return [
                _node_view(svc, n.id, space)
                for n in svc.tree.visible_nodes(space)
                if n.parent_id is None and n.is_answer and not n.is_stub
            ]

    @app.get("/api/search")
    def search(q: str = "", space: str = "public"):
        svc = get_service()
        with svc.reading():
            return [_node_view(svc, n.id, space) for n in svc.tree.search(q, space)]

    @app.get("/api/nodes/{node_id}")
    def get_node(node_id: str, space: str = "public"):
        svc = get_service()
        from nightwish import db, pgstore

        url = db.database_url()
        if url:
            # point read: load only this node's closure (not the whole graph)
            # and render it with the normal view code.
            snap = pgstore.node_closure(url, node_id)
            if snap is None:
                raise HTTPException(404, f"unknown node {node_id!r}")
            tree, econ = UnifiedService._from_data(snap)
            n = tree.nodes.get(node_id)
            if n is None or not tree._visible(n, space):
                raise HTTPException(404, f"unknown node {node_id!r}")
            return _node_view(_ReadView(tree, econ), node_id, space, full=True)
        with svc.reading():
            n = svc.tree.nodes.get(node_id)
            if n is None or not svc.tree._visible(n, space):
                raise HTTPException(404, f"unknown node {node_id!r}")
            return _node_view(svc, node_id, space, full=True)

    @app.post("/api/ask")
    def ask(body: AskBody):
        """Ask the AI. "AI에게 묻기"는 **항상** AI에게 묻는다 — 검색 결과가 따로
        밑에 떠도, 이 버튼은 늘 새 답을 생성해 새 ROOT 노드로 못박는다.

        (기존 지식을 *재사용*하고 싶으면 검색으로 그 노드를 직접 열면 된다. 관련
        기존 답은 응답의 ``related``로 함께 돌려주어 UI가 밑에 보여줄 수 있다.)
        """
        svc = get_service()
        with svc.reading():
            related = [_node_view(svc, n.id, body.space)
                       for n in svc.tree.search(body.question, body.space)[:5]
                       if n.is_answer]
            # 답 난립 완화: 같은 질문(슬러그)의 '채택본'이 이미 있으면, 새 초안을
            # 또 만들기 전에 그 답을 먼저 보여준다. force=True면 그래도 새로 생성.
            if not body.force:
                dup = svc.tree.nodes.get(slugify(body.question))
                if (dup is not None and not dup.is_stub and dup.is_answer
                        and svc.tree._visible(dup, body.space)):
                    dup_view = _node_view(svc, dup.id, body.space, full=True)
                    if dup_view["adopted"]:
                        return {"stage": "existing", "node": dup_view,
                                "related": related}
        # The AI draft is a (possibly multi-second) network call — do it WITHOUT
        # holding the lock, so the rest of the app (status poll, other users)
        # isn't frozen while a generation is in flight.
        text = _ask_ai(body.question)
        with svc.writing():
            nid = svc._new_id(body.question)
            # The concept (ROOT) is always public commons; the asker's group
            # (body.space) only frames *discovery*, never the concept's home.
            svc.tree.add_root(nid, body.question, text, body.author)
            svc.tree.mark_answered(nid, _ai_model)
            return {"stage": "ai",
                    "node": _node_view(svc, nid, body.space, full=True),
                    "related": related}

    @app.post("/api/nodes")
    def create_node(body: PageBody):
        """Create (or edit) a human-authored knowledge node.

        A ROOT concept is always public commons (its slug is a shared address),
        so ``space`` only frames the viewer's discovery, not the node's home.
        """
        svc = get_service()
        with svc.writing():
            nid = slugify(body.title)
            existing = svc.tree.nodes.get(nid)
            if existing is not None and not existing.is_stub:
                if existing.frozen:
                    raise HTTPException(
                        409, "동결된 AI 답변은 직접 수정할 수 없습니다 — 기여로 추가하세요")
                svc.tree.edit(existing.id, body.body, body.author)
                return _node_view(svc, existing.id, body.space, full=True)
            if existing is not None:           # promote an empty stub → real page
                del svc.tree.nodes[nid]
            svc.tree.add_root(nid, body.title, body.body, body.author)
            return _node_view(svc, nid, body.space, full=True)

    @app.post("/api/nodes/{node_id}/contribute")
    def contribute(node_id: str, body: ContribBody):
        """Augment / follow / correct / follow-up — on ANY node, recursively.

        ``followup`` nests a new question node and has the AI answer it as a
        child, so the answer is itself a slot that can be further refined.
        """
        svc = get_service()
        kind = body.kind if body.kind in (
            "comment", "fork", "follow", "followup") else "comment"
        if kind == "followup" and not body.body.strip():
            raise HTTPException(400, "후속질문 내용이 필요합니다")
        # A follow-up's AI answer is a slow network call: do it OUTSIDE the lock,
        # but first anchor it to the parent chain's Q&A so it answers *in thread*.
        ai_text = None
        if kind == "followup":
            from nightwish import db, pgstore

            url = db.database_url()
            if url:
                snap = pgstore.node_closure(url, node_id)
                ctx_tree = UnifiedService._from_data(snap)[0] if snap else None
            else:
                with svc.reading():
                    ctx_tree = svc.tree
            if ctx_tree is None or node_id not in ctx_tree.nodes:
                raise HTTPException(404, f"node {node_id!r} not found")
            ai_text = _ask_ai(body.body, _anchor_prompt(ctx_tree, node_id))
        with svc.writing():
            parent = svc.tree.nodes.get(node_id)
            if parent is None or not svc.tree._visible(parent, body.space):
                raise HTTPException(404, f"node {node_id!r} not found")
            try:
                if kind == "follow":
                    svc.tree.follow(svc._child_id(node_id), node_id, body.author,
                                    stake=0.0, space=body.space)
                elif kind == "fork":
                    if not body.body.strip():
                        raise HTTPException(400, "정정/다른 답에는 내용이 필요합니다")
                    svc.tree.fork(svc._child_id(node_id), node_id, body.author,
                                  body.body, stake=0.0, space=body.space)
                elif kind == "followup":
                    qid = svc._child_id(node_id)
                    svc.tree.contribute(qid, node_id, body.author, answer="",
                                        stake=0.0, question=body.body,
                                        value_add=True, space=body.space)
                    aid = svc._child_id(qid)
                    svc.tree.contribute(aid, qid, "AI", ai_text,
                                        stake=0.0, space=body.space)
                    svc.tree.mark_answered(aid, _ai_model)
                else:  # comment / 보강
                    if not body.body.strip():
                        raise HTTPException(400, "의견 내용이 필요합니다")
                    svc.tree.contribute(svc._child_id(node_id), node_id, body.author,
                                        body.body, stake=0.0, value_add=False,
                                        space=body.space)
            except OntologyError as e:
                raise HTTPException(400, str(e))
            return _node_view(svc, node_id, body.space, full=True)

    @app.post("/api/nodes/{node_id}/expand")
    def expand(node_id: str, body: ExpandBody):
        """드래그한 내용을 AI에게 물어, 답이 달린 '연결된 개념 노드'로 만든다.

        선택 텍스트(또는 다듬은 질문)를 제목으로 한 노드를 만들고(없거나 stub면 AI가
        답을 채움), 원본 노드에서 그 노드로 **위키링크 관계**를 건다(원본이 동결 답이어도
        본문은 안 건드리고 관계만 추가). 링크 행위는 거는 사람의 안목(hub)으로 적립.
        """
        svc = get_service()
        if not body.question.strip():
            raise HTTPException(400, "질문 내용이 필요합니다")
        target_slug = slugify(body.question)
        if not target_slug:
            raise HTTPException(400, "유효한 제목이 아닙니다")
        from nightwish import db, pgstore

        url = db.database_url()
        if url:
            snap = pgstore.node_closure(url, node_id)
            ctx_tree = UnifiedService._from_data(snap)[0] if snap else None
        else:
            with svc.reading():
                ctx_tree = svc.tree
        if ctx_tree is None or node_id not in ctx_tree.nodes:
            raise HTTPException(404, f"node {node_id!r} not found")
        existing = ctx_tree.nodes.get(target_slug)
        need_ai = existing is None or existing.is_stub
        # AI answer (slow) anchored to the source — outside the lock
        ai_text = _ask_ai(body.question, _anchor_prompt(ctx_tree, node_id)) if need_ai else None
        with svc.writing():
            source = svc.tree.nodes.get(node_id)
            if source is None:
                raise HTTPException(404, f"node {node_id!r} not found")
            target = svc.tree.nodes.get(target_slug)
            if target is None or target.is_stub:
                if target is not None:          # promote a stub → a real answer
                    del svc.tree.nodes[target_slug]
                try:
                    svc.tree.add_root(target_slug, body.question, ai_text or "",
                                      body.author)
                except OntologyError as e:
                    raise HTTPException(400, str(e))
                svc.tree.mark_answered(target_slug, _ai_model)
            # wikilink: source → target (relationship + foresight for the linker)
            if target_slug != source.id and target_slug not in source.links:
                source.links.append(target_slug)
                svc.tree.scoring.link(body.author, target_slug, weight=1.0)
            return {
                "source": _node_view(svc, node_id, body.space, full=True),
                "target": _node_view(svc, target_slug, body.space, full=True),
            }

    @app.post("/api/nodes/{node_id}/fill")
    def fill_stub(node_id: str, body: FillBody):
        """Fill an empty concept (stub) with an AI answer, in place.

        A ``[[wikilink]]`` auto-creates an empty concept; this is the button that
        asks the AI to write its canonical summary without changing the slug, so
        every link that pointed here keeps resolving to the same concept.
        """
        svc = get_service()
        with svc.reading():
            n = svc.tree.nodes.get(node_id)
            if n is None:
                raise HTTPException(404, f"node {node_id!r} not found")
            if not n.is_stub:
                raise HTTPException(409, "이미 채워진 개념입니다")
            question = n.question
        # AI draft is a (slow) network call — do it outside the write lock.
        text = _ask_ai(question)
        with svc.writing():
            n = svc.tree.nodes.get(node_id)
            if n is None or not n.is_stub:
                raise HTTPException(409, "이미 채워진 개념입니다")
            svc.tree.fill_stub(node_id, text, body.author, _ai_model)
            return _node_view(svc, node_id, body.space, full=True)

    @app.get("/api/queries")
    def list_queries(space: str = "public"):
        svc = get_service()
        with svc.reading():
            return [_node_view(svc, q.id, space) for q in svc.tree.open_queries(space)]

    @app.post("/api/queries")
    def create_query(body: QueryBody):
        svc = get_service()
        with svc.writing():
            nid = svc._new_id(body.title)
            q = svc.tree.open_query(nid, body.title, body.author, space=body.space)
            if body.detail.strip():
                svc.tree.contribute(svc._child_id(nid), nid, body.author,
                                    body.detail, stake=0.0, value_add=False,
                                    space=body.space)
            return _node_view(svc, q.id, body.space, full=True)

    @app.post("/api/queries/{node_id}/answer")
    def answer_query(node_id: str, body: AnswerBody):
        """Fill an open query in place — by a human, or by the AI (``ai=true``)."""
        svc = get_service()
        with svc.reading():
            q = svc.tree.nodes.get(node_id)
            if q is None or not q.is_query:
                raise HTTPException(404, f"open query {node_id!r} not found")
            question = q.question
        # AI generation is a slow network call — outside the lock.
        text = _ask_ai(question) if body.ai else body.body
        with svc.writing():
            if node_id not in svc.tree.nodes:
                raise HTTPException(404, f"open query {node_id!r} not found")
            if not text.strip():
                raise HTTPException(400, "답변 내용이 필요합니다")
            try:
                svc.tree.answer_query(node_id, text, body.author,
                                      model=_ai_model if body.ai else "")
            except OntologyError as e:
                raise HTTPException(400, str(e))
            return _node_view(svc, node_id, body.space, full=True)

    @app.get("/api/scores")
    def scores(space: str = "public"):
        svc = get_service()
        with svc.reading():
            t = svc.tree
            # A group viewer ranks on the public commons prior + its own private
            # endorse overlay; a public viewer sees only the commons. Memoised per
            # write revision (docs/design/06): repeated reads are O(1).
            ranked = t.scoreboard(space)
            hub = dict(t.scoring.hub)
            if t._is_group(space) and space in t.group_scoring:
                for u, h in t.group_scoring[space].hub.items():
                    hub[u] = hub.get(u, 0.0) + h
            hubs = sorted(((u, h) for u, h in hub.items() if h > 0),
                          key=lambda uh: -uh[1])
            # 채택 평가자 가시화: hub는 후속 평가자가 와야 붙지만, 평가(스테이크)
            # 행위 자체는 즉시 인정받아야 한다 — 콜드스타트 완화.
            evald: dict[str, float] = {}
            for stakes in svc.econ.staked.values():
                for u, amt in stakes.items():
                    if amt > 0:
                        evald[u] = evald.get(u, 0.0) + amt
            return {
                "mode": t.scoring.mode,
                "top_nodes": [
                    {"id": n.id, "title": n.question, "author": n.author,
                     "authority": round(a, 4)}
                    for n, a in ranked[:10] if a > 0
                ],
                "top_contributors": [
                    {"user": u, "hub": round(h, 4)} for u, h in hubs[:10]
                ],
                "top_evaluators": [
                    {"user": u, "staked": round(s, 4)}
                    for u, s in sorted(evald.items(), key=lambda us: -us[1])[:10]
                ],
            }

    @app.get("/api/graph")
    def graph(space: str = "public"):
        svc = get_service()
        with svc.reading():
            t = svc.tree
            vis = {n.id for n in t.visible_nodes(space)}
            nodes = [
                {"id": n.id, "title": n.question,
                 "authority": round(t.authority_in(n.id, space), 3),
                 "is_stub": n.is_stub}
                for n in t.visible_nodes(space) if n.parent_id is None
            ]
            edges = [
                {"source": n.id, "target": tgt}
                for n in t.visible_nodes(space)
                for tgt in n.links if tgt in vis
            ]
            return {"nodes": nodes, "edges": edges}

    @app.post("/api/mint")
    def mint(body: MintBody):
        svc = get_service()
        with svc.writing():
            svc.econ.mint(body.account, body.amount)
            return {"account": body.account, "balance": svc.econ.balance(body.account)}

    @app.post("/api/endorse")
    def endorse(body: EndorseBody):
        svc = get_service()
        with svc.writing():
            n = svc.tree.nodes.get(body.node_id)
            if n is None or n.is_stub:
                raise HTTPException(404, f"node {body.node_id!r} not found or empty")
            # A group endorses only what it can see (public commons ∪ its own layer).
            if not svc.tree._visible(n, body.space):
                raise HTTPException(404, f"node {body.node_id!r} not found or empty")

            # -- group-private endorse: free-issue, non-convertible group coin.
            # It feeds ONLY the group's own engine, so it never touches the common
            # coin economy and never moves the public commons authority.
            if svc.tree._is_group(body.space):
                first_time = svc.tree.group_linker_position(
                    body.space, body.account, body.node_id) is None
                if first_time and body.account != n.author:
                    svc.tree.group_endorse(
                        body.space, body.account, body.node_id, weight=body.amount)
                return {
                    "account": body.account,
                    "space": body.space,
                    "group_authority": round(
                        svc.tree.group_scoring[body.space].authority_of(body.node_id), 4
                    ) if body.space in svc.tree.group_scoring else 0.0,
                    "coauthors": _coauthors(svc, body.node_id),
                }

            # -- public endorse: spend the common coin; pay dividends up the chain.
            try:
                payouts = svc.econ.endorse(
                    body.account, body.node_id, body.amount,
                    page_author=n.author, hub_of=svc.tree.scoring.hub_of,
                )
            except (InsufficientPoints, ValueError) as e:
                raise HTTPException(400, str(e))
            # Evaluation *is* authorship: the act of endorsing links the
            # evaluator to the node, growing their 안목(hub/foresight) and the
            # node's authority. Earliest evaluators of a Q&A that later draws
            # more endorsement earn the most — the patent's "who saw it first".
            # We link once per evaluator (idempotent on repeat endorsements) so
            # the co-author set is the distinct chain of people who staked.
            first_time = svc.tree.scoring.linker_position(body.account, body.node_id) is None
            if first_time and body.account != n.author:
                svc.tree.scoring.link(body.account, body.node_id, weight=body.amount)
            svc.tree.bump()   # public authority changed → invalidate scoreboard memo
            return {
                "account": body.account,
                "balance": round(svc.econ.balance(body.account), 4),
                "payouts": {k: round(v, 4) for k, v in payouts.items()},
                "staked_on_node": round(sum(svc.econ.staked_on(body.node_id).values()), 4),
                "coauthors": _coauthors(svc, body.node_id),
            }

    @app.get("/api/ledger")
    def ledger():
        svc = get_service()
        with svc.reading():
            e = svc.econ
            return {
                "available": {k: round(v, 4) for k, v in e.available.items() if v},
                "staked_by_node": {
                    k: {a: round(s, 4) for a, s in v.items()}
                    for k, v in e.staked.items() if v
                },
                "burned": round(e.burned, 4),
            }

    @app.get("/")
    def index():
        page = STATIC_DIR / "app.html"
        if page.exists():
            return FileResponse(page)
        return {"app": "nightwish-unified", "ui": "pending (Stage 3)"}

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()


def main() -> None:
    """Console entrypoint: ``nightwish-app``. Binds 0.0.0.0:$PORT."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("NIGHTWISH_PORT", "8000")))
    uvicorn.run("nightwish.unified:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
