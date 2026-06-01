"""MVP service: a shared LLM-Wiki (Obsidian + LLM, shared between users).

Deployable on Railway. A thin FastAPI layer over :mod:`nightwish.wiki`:

* write/read interlinked markdown pages (``[[wikilinks]]``),
* an LLM "draft" assist for a page (offline stub by default; swap with
  :func:`set_ai` to use a real model),
* the patent hub/authority signal surfaced as "top pages" / "top contributors".

Run locally::

    pip install -e ".[service]"
    nightwish-mvp                 # uvicorn nightwish.mvp:app
    # → http://127.0.0.1:8000/

On Railway the start command binds ``0.0.0.0:$PORT`` (see Procfile / nixpacks.toml).
State persists to ``$NIGHTWISH_WIKI_DB`` (default ``data/wiki.json``); mount a
Railway Volume there to survive redeploys.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nightwish.scoring import ScoreEngine
from nightwish.wiki import Wiki, slugify
from nightwish.wiki_economy import InsufficientPoints, WikiEconomy

STATIC_DIR = Path(__file__).parent / "static"
DEFAULT_DB = os.environ.get("NIGHTWISH_WIKI_DB", "data/wiki.json")
HUB_MODE = os.environ.get("NIGHTWISH_HUB_MODE", "harmonic")


# --------------------------------------------------------------------------- #
# pluggable LLM draft assist                                                  #
# --------------------------------------------------------------------------- #
def offline_draft(title: str, prompt: str) -> str:
    """Deterministic offline draft (no API key / network needed).

    Produces a markdown skeleton the user can edit and save. A real backend
    (installed via :func:`set_ai`) would return a genuine model completion.
    """
    ask = prompt.strip() or f"'{title}'에 대해 설명"
    return (
        f"# {title}\n\n"
        f"> (AI 초안) {ask}\n\n"
        "## 개요\n\n여기에 핵심을 적으세요. 사람의 검증·편집으로 정제됩니다.\n\n"
        "## 근거\n\n- \n\n## 관련 문서\n\n"
        "- [[관련 페이지 제목]] 으로 다른 문서에 연결하세요. "
        "먼저 좋은 문서를 알아보고 링크할수록 안목(허브) 점수가 오릅니다.\n"
    )


_ai_fn: Callable[[str, str], str] = offline_draft
#: relation extractor (title, body) -> list[triple]; None until LLM configured
_relations_fn: Optional[Callable[[str, str], list]] = None
#: model id stamped onto frozen answers ("offline-stub" until LLM configured)
_ai_model: str = "offline-stub"


def set_ai(fn: Callable[[str, str], str]) -> None:
    """Install a real LLM draft backend. Signature: ``fn(title, prompt) -> markdown``."""
    global _ai_fn
    _ai_fn = fn


def configure_ai() -> bool:
    """Activate Claude-backed draft + relation extraction if enabled. Returns success."""
    global _relations_fn, _ai_model
    from nightwish.llm import DEFAULT_MODEL, make_draft_fn, make_relation_fn

    draft = make_draft_fn()
    if draft is not None:
        set_ai(draft)
        _ai_model = DEFAULT_MODEL
    _relations_fn = make_relation_fn()
    return draft is not None


# --------------------------------------------------------------------------- #
# state + persistence                                                         #
# --------------------------------------------------------------------------- #
def _load_state(db_path: str, hub_mode: str) -> tuple[Wiki, WikiEconomy]:
    """Load the combined {wiki, economy} snapshot (or legacy wiki-only, or fresh)."""
    if os.path.exists(db_path):
        with open(db_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if "wiki" in data:  # combined format (schema 2)
            return Wiki.from_json(data["wiki"]), WikiEconomy.from_json(
                data.get("economy", {})
            )
        if "pages" in data:  # legacy wiki-only snapshot
            return Wiki.from_json(data), WikiEconomy()
    return Wiki(scoring=ScoreEngine(mode=hub_mode)), WikiEconomy()


def _save_state(db_path: str, wiki: Wiki, econ: WikiEconomy) -> None:
    directory = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(directory, exist_ok=True)
    payload = {"schema": 2, "wiki": wiki.to_json(), "economy": econ.to_json()}
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, db_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class WikiService:
    def __init__(self, db_path: str = DEFAULT_DB, *, hub_mode: str = HUB_MODE):
        self.db_path = db_path
        self._lock = threading.RLock()
        self.wiki, self.econ = _load_state(db_path, hub_mode)
        #: slug -> (updated_at, relations) cache for /api/extract (not persisted)
        self._relcache: dict[str, tuple[int, list]] = {}

    def save(self) -> None:
        _save_state(self.db_path, self.wiki, self.econ)


_service: Optional[WikiService] = None


def get_service() -> WikiService:
    global _service
    if _service is None:
        _service = WikiService()
    return _service


def reset_service(db_path: str, *, hub_mode: str = "harmonic") -> WikiService:
    """(Re)initialise the global service — used by tests for isolation."""
    global _service
    _service = WikiService(db_path, hub_mode=hub_mode)
    return _service


# --------------------------------------------------------------------------- #
# request models                                                              #
# --------------------------------------------------------------------------- #
class SaveBody(BaseModel):
    title: str = Field(min_length=1)
    body: str = ""
    author: str = Field(min_length=1)
    space: str = "public"


class DraftBody(BaseModel):
    title: str = Field(min_length=1)
    prompt: str = ""


class MintBody(BaseModel):
    account: str = Field(min_length=1)
    amount: float = Field(gt=0)


class EndorseBody(BaseModel):
    account: str = Field(min_length=1)
    slug: str = Field(min_length=1)
    amount: float = Field(gt=0)


class AiAnswerBody(BaseModel):
    question: str = Field(min_length=1)
    author: str = Field(min_length=1)
    space: str = "public"


class QueryBody(BaseModel):
    title: str = Field(min_length=1)
    detail: str = ""
    author: str = Field(min_length=1)
    space: str = "public"


class AnswerBody(BaseModel):
    body: str = Field(min_length=1)
    author: str = Field(min_length=1)
    title: str = ""
    space: str = "public"


class ExtractBody(BaseModel):
    slug: str = Field(min_length=1)
    space: str = "public"


class ContribBody(BaseModel):
    kind: str = "comment"  # comment | fork | followup
    author: str = Field(min_length=1)
    body: str = ""
    space: str = "public"


def _page_view(svc: WikiService, slug: str, *, full: bool = False,
               space: str = "public") -> dict:
    p = svc.wiki.get(slug)
    view = {
        "slug": p.slug, "title": p.title, "author": p.author,
        "last_editor": p.last_editor, "updated_at": p.updated_at,
        "is_stub": p.is_stub, "authority": round(svc.wiki.authority_of(p.slug), 4),
        "links": list(p.links), "kind": p.kind, "status": p.status,
        "frozen": p.frozen, "model": p.model, "answered_at": p.answered_at,
        "space": p.space,
    }
    if full:
        view["body"] = p.body
        # contributions are layered too: show public ∪ the viewer's space
        view["contributions"] = [
            c for c in p.contributions
            if c.get("space", "public") in ("public", space)
        ]
        view["backlinks"] = [
            {"slug": b.slug, "title": b.title, "author": b.author}
            for b in svc.wiki.backlinks(slug, space)
        ]
        view["linkers"] = svc.wiki.scoring.link_order(slug)
    return view


# --------------------------------------------------------------------------- #
# app                                                                         #
# --------------------------------------------------------------------------- #
def create_app() -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        configure_ai()  # no-op unless NIGHTWISH_ENABLE_LLM + ANTHROPIC_API_KEY set
        yield

    app = FastAPI(title="Nightwish Wiki — shared LLM wiki", version="0.1.0",
                  lifespan=lifespan)

    @app.get("/api/health")
    def health():
        # Railway/uptime healthcheck — must return 200 quickly.
        return {"status": "ok"}

    @app.get("/api/state")
    def state():
        svc = get_service()
        with svc._lock:
            real = [p for p in svc.wiki.pages.values() if not p.is_stub]
            return {
                "hub_mode": svc.wiki.scoring.mode,
                "page_count": len(real),
                "stub_count": len(svc.wiki.pages) - len(real),
            }

    @app.get("/api/pages")
    def list_pages(space: str = "public"):
        svc = get_service()
        with svc._lock:
            return [_page_view(svc, p.slug, space=space)
                    for p in svc.wiki.list_pages(space)]

    @app.get("/api/search")
    def search(q: str = "", space: str = "public"):
        svc = get_service()
        with svc._lock:
            return [_page_view(svc, p.slug, space=space)
                    for p in svc.wiki.search(q, space)]

    @app.get("/api/pages/{slug}")
    def get_page(slug: str, space: str = "public"):
        svc = get_service()
        with svc._lock:
            p = svc.wiki.get(slug)
            if p is None or not svc.wiki._visible(p, space):
                raise HTTPException(404, f"unknown page {slug!r}")
            return _page_view(svc, slug, full=True, space=space)

    @app.post("/api/pages")
    def save_page(body: SaveBody):
        svc = get_service()
        with svc._lock:
            existing = svc.wiki.get_by_title(body.title)
            if existing is not None and existing.frozen:
                raise HTTPException(
                    409, "동결된 AI 답변은 직접 수정할 수 없습니다 — 기여(의견/정정/후속질문)로 추가하세요"
                )
            try:
                page = svc.wiki.save_page(body.title, body.body, body.author,
                                          space=body.space)
            except ValueError as e:
                raise HTTPException(400, str(e))
            svc.save()
            return _page_view(svc, page.slug, full=True, space=body.space)

    @app.post("/api/pages/{slug}/contribute")
    def contribute(slug: str, body: ContribBody):
        """Append a contribution to a node's thread (instead of editing it).

        The contribution lands in ``body.space`` — a group member commenting on a
        public node keeps that note in the group layer (one-way membrane).
        kind=followup also generates an AI answer entry below the question.
        """
        svc = get_service()
        with svc._lock:
            page = svc.wiki.get(slug)
            if page is None or page.is_stub or not svc.wiki._visible(page, body.space):
                raise HTTPException(404, f"page {slug!r} not found or empty")
            kind = body.kind if body.kind in ("comment", "fork", "followup") else "comment"
            svc.wiki.add_contribution(slug, kind, body.author, body.body, space=body.space)
            if kind == "followup" and body.body.strip():
                try:
                    ans = _ai_fn(body.body, "")
                except Exception:
                    ans = offline_draft(body.body, "")
                svc.wiki.add_contribution(slug, "answer", "AI", ans,
                                          model=_ai_model, space=body.space)
            svc.save()
            return _page_view(svc, slug, full=True, space=body.space)

    @app.post("/api/draft")
    def draft(body: DraftBody):
        # AI assist does not save — returns suggested markdown to edit.
        # Fall back to the offline stub if the real backend errors (network/key).
        try:
            text = _ai_fn(body.title, body.prompt)
        except Exception:
            text = offline_draft(body.title, body.prompt)
        return {"title": body.title, "body": text}

    # -- the cycle: search → AI answer → public query → answer --------------- #
    @app.post("/api/ai-answer")
    def ai_answer(body: AiAnswerBody):
        """Stage ②: search came up short → AI answers → a knowledge page is born."""
        svc = get_service()
        with svc._lock:
            try:
                text = _ai_fn(body.question, "")
            except Exception:
                text = offline_draft(body.question, "")
            page = svc.wiki.save_page(body.question, text, body.author, space=body.space)
            svc.wiki.mark_answered(page.slug, _ai_model)  # 모델·날짜 박제(동결)
            svc.save()
            return _page_view(svc, page.slug, full=True, space=body.space)

    @app.get("/api/queries")
    def list_queries(space: str = "public"):
        """Open public queries awaiting human answers (stage ③ backlog)."""
        svc = get_service()
        with svc._lock:
            return [_page_view(svc, q.slug, space=space)
                    for q in svc.wiki.open_queries(space)]

    @app.post("/api/queries")
    def create_query(body: QueryBody):
        """Stage ③: post a public query — what search/AI couldn't satisfy."""
        svc = get_service()
        with svc._lock:
            try:
                q = svc.wiki.create_query(body.title, body.detail, body.author,
                                          space=body.space)
            except ValueError as e:
                raise HTTPException(400, str(e))
            svc.save()
            return _page_view(svc, q.slug, full=True, space=body.space)

    @app.post("/api/queries/{slug}/answer")
    def answer_query(slug: str, body: AnswerBody):
        """Answer an open query → new knowledge page (linked + searchable)."""
        svc = get_service()
        with svc._lock:
            try:
                page = svc.wiki.answer_query(slug, body.title, body.body,
                                             body.author, space=body.space)
            except ValueError as e:
                raise HTTPException(404, str(e))
            svc.save()
            return _page_view(svc, page.slug, full=True, space=body.space)

    @app.get("/api/scores")
    def scores(space: str = "public"):
        svc = get_service()
        with svc._lock:
            return {
                "mode": svc.wiki.scoring.mode,
                "top_pages": [
                    {"slug": p.slug, "title": p.title, "author": p.author,
                     "authority": round(a, 4)}
                    for p, a in svc.wiki.top_pages(space=space)
                ],
                "top_contributors": [
                    {"user": u, "hub": round(h, 4)}
                    for u, h in svc.wiki.top_contributors()
                ],
            }

    @app.get("/api/resolve/{title}")
    def resolve(title: str, space: str = "public"):
        """Map a [[wikilink]] title to its slug + existence (for the UI)."""
        svc = get_service()
        with svc._lock:
            slug = slugify(title)
            p = svc.wiki.get(slug)
            visible = p is not None and not p.is_stub and svc.wiki._visible(p, space)
            return {"title": title, "slug": slug, "exists": visible}

    @app.post("/api/extract")
    def extract(body: ExtractBody):
        """Extract (subject, predicate, object) relations from a page.

        Uses the LLM when enabled; otherwise falls back to the page's wikilinks
        as ``A —관련→ B`` triples. Cached per page until its body changes.
        """
        svc = get_service()
        with svc._lock:
            page = svc.wiki.get(body.slug)
            if page is None or page.is_stub or not svc.wiki._visible(page, body.space):
                raise HTTPException(404, f"page {body.slug!r} not found or empty")
            cached = svc._relcache.get(page.slug)
            if cached and cached[0] == page.updated_at:
                return {"relations": cached[1], "source": "cache"}
            rels = None
            if _relations_fn is not None:
                try:
                    rels = _relations_fn(page.title, page.body)
                except Exception:
                    rels = None
            source = "ai"
            if rels is None:
                # offline fallback: derive relations from wikilinks
                source = "links"
                rels = [
                    {"subject": page.title, "predicate": "관련",
                     "object": svc.wiki.pages[t].title}
                    for t in page.links
                    if t in svc.wiki.pages and not svc.wiki.pages[t].is_query
                ]
            svc._relcache[page.slug] = (page.updated_at, rels)
            return {"relations": rels, "source": source}

    @app.get("/api/graph")
    def graph(space: str = "public"):
        svc = get_service()
        with svc._lock:
            w = svc.wiki
            vis = {p.slug for p in w.pages.values() if w._visible(p, space)}
            nodes = [
                {
                    "slug": p.slug, "title": p.title,
                    "authority": round(w.authority_of(p.slug), 3),
                    "is_stub": p.is_stub,
                }
                for p in w.pages.values() if p.slug in vis
            ]
            edges = [
                {"source": p.slug, "target": t}
                for p in w.pages.values()
                if p.slug in vis
                for t in p.links
                if t in vis
            ]
            return {"nodes": nodes, "edges": edges}

    @app.post("/api/mint")
    def mint(body: MintBody):
        svc = get_service()
        with svc._lock:
            svc.econ.mint(body.account, body.amount)
            svc.save()
            return {"account": body.account, "balance": svc.econ.balance(body.account)}

    @app.post("/api/endorse")
    def endorse(body: EndorseBody):
        svc = get_service()
        with svc._lock:
            page = svc.wiki.get(body.slug)
            if page is None or page.is_stub:
                raise HTTPException(404, f"page {body.slug!r} not found or empty")
            try:
                payouts = svc.econ.endorse(
                    body.account, body.slug, body.amount,
                    page_author=page.author, hub_of=svc.wiki.hub_of,
                )
            except (InsufficientPoints, ValueError) as e:
                raise HTTPException(400, str(e))
            svc.save()
            return {
                "account": body.account,
                "balance": round(svc.econ.balance(body.account), 4),
                "payouts": {k: round(v, 4) for k, v in payouts.items()},
                "staked_on_page": round(
                    sum(svc.econ.staked_on(body.slug).values()), 4
                ),
            }

    @app.get("/api/ledger")
    def ledger():
        svc = get_service()
        with svc._lock:
            e = svc.econ
            return {
                "available": {k: round(v, 4) for k, v in e.available.items() if v},
                "staked_by_page": {
                    k: {a: round(s, 4) for a, s in v.items()}
                    for k, v in e.staked.items() if v
                },
                "burned": round(e.burned, 4),
            }

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "wiki.html")

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    return app


app = create_app()


def main() -> None:
    """Console entrypoint: ``nightwish-mvp``. Binds 0.0.0.0:$PORT for Railway."""
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("NIGHTWISH_PORT", "8000")))
    uvicorn.run("nightwish.mvp:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
