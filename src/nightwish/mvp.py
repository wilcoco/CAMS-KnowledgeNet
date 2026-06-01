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

import os
import threading
from pathlib import Path
from typing import Callable, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nightwish.scoring import ScoreEngine
from nightwish.wiki import Wiki, slugify

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


def set_ai(fn: Callable[[str, str], str]) -> None:
    """Install a real LLM draft backend. Signature: ``fn(title, prompt) -> markdown``."""
    global _ai_fn
    _ai_fn = fn


# --------------------------------------------------------------------------- #
# state + persistence                                                         #
# --------------------------------------------------------------------------- #
class WikiService:
    def __init__(self, db_path: str = DEFAULT_DB, *, hub_mode: str = HUB_MODE):
        self.db_path = db_path
        self._lock = threading.RLock()
        loaded = Wiki.load(db_path)
        self.wiki: Wiki = loaded or Wiki(scoring=ScoreEngine(mode=hub_mode))

    def save(self) -> None:
        self.wiki.save(self.db_path)


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


class DraftBody(BaseModel):
    title: str = Field(min_length=1)
    prompt: str = ""


def _page_view(svc: WikiService, slug: str, *, full: bool = False) -> dict:
    p = svc.wiki.get(slug)
    view = {
        "slug": p.slug, "title": p.title, "author": p.author,
        "last_editor": p.last_editor, "updated_at": p.updated_at,
        "is_stub": p.is_stub, "authority": round(svc.wiki.authority_of(p.slug), 4),
        "links": list(p.links),
    }
    if full:
        view["body"] = p.body
        view["backlinks"] = [
            {"slug": b.slug, "title": b.title, "author": b.author}
            for b in svc.wiki.backlinks(slug)
        ]
        view["linkers"] = svc.wiki.scoring.link_order(slug)
    return view


# --------------------------------------------------------------------------- #
# app                                                                         #
# --------------------------------------------------------------------------- #
def create_app() -> FastAPI:
    app = FastAPI(title="Nightwish Wiki — shared LLM wiki", version="0.1.0")

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
    def list_pages():
        svc = get_service()
        with svc._lock:
            return [_page_view(svc, p.slug) for p in svc.wiki.list_pages()]

    @app.get("/api/search")
    def search(q: str = ""):
        svc = get_service()
        with svc._lock:
            return [_page_view(svc, p.slug) for p in svc.wiki.search(q)]

    @app.get("/api/pages/{slug}")
    def get_page(slug: str):
        svc = get_service()
        with svc._lock:
            if svc.wiki.get(slug) is None:
                raise HTTPException(404, f"unknown page {slug!r}")
            return _page_view(svc, slug, full=True)

    @app.post("/api/pages")
    def save_page(body: SaveBody):
        svc = get_service()
        with svc._lock:
            try:
                page = svc.wiki.save_page(body.title, body.body, body.author)
            except ValueError as e:
                raise HTTPException(400, str(e))
            svc.save()
            return _page_view(svc, page.slug, full=True)

    @app.post("/api/draft")
    def draft(body: DraftBody):
        # AI assist does not save — returns suggested markdown to edit.
        return {"title": body.title, "body": _ai_fn(body.title, body.prompt)}

    @app.get("/api/scores")
    def scores():
        svc = get_service()
        with svc._lock:
            return {
                "mode": svc.wiki.scoring.mode,
                "top_pages": [
                    {"slug": p.slug, "title": p.title, "author": p.author,
                     "authority": round(a, 4)}
                    for p, a in svc.wiki.top_pages()
                ],
                "top_contributors": [
                    {"user": u, "hub": round(h, 4)}
                    for u, h in svc.wiki.top_contributors()
                ],
            }

    @app.get("/api/resolve/{title}")
    def resolve(title: str):
        """Map a [[wikilink]] title to its slug + existence (for the UI)."""
        svc = get_service()
        with svc._lock:
            slug = slugify(title)
            p = svc.wiki.get(slug)
            return {"title": title, "slug": slug,
                    "exists": p is not None and not p.is_stub}

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
