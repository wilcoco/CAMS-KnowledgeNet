"""FastAPI 앱 — 검증된 소셜 위키 (MVS), 영속 + API 서버.

실행(로컬):   uvicorn nightwish.webapp.app:app --reload   → http://127.0.0.1:8000
실행(배포):   uvicorn nightwish.webapp.app:app --host 0.0.0.0 --port $PORT

상태는 `DATABASE_URL`(미설정 시 SQLite 파일)에 영속한다. 로그인은 이름만 입력하는
최소 형태(쿠키에 user id) — 인증·보안은 MVS 범위 밖. JSON API는 `/api/*`.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from nightwish.verification import Direction, Measurement
from nightwish.webapp.render import render_markdown
from nightwish.wiki import (
    InsufficientPoints,
    WikiError,
    WikiService,
    init_db,
    make_bookkeeper,
    make_engine,
    make_session_factory,
)

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

COOKIE = "nw_user"

# 엔진/세션/북키퍼는 프로세스 단위로 1회 구성
engine = make_engine()
SessionLocal = make_session_factory(engine)
bookkeeper = make_bookkeeper()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(engine)
    yield


app = FastAPI(title="Nightwish — 검증된 소셜 위키 (MVS)", lifespan=lifespan)


# -- 의존성 -------------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_service(db=Depends(get_db)) -> WikiService:
    return WikiService(db, bookkeeper)


def current_user(request: Request, svc: WikiService):
    return svc.get_user(request.cookies.get(COOKIE))


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


# API 라우터 (정의는 api.py) — 그 `_svc` 의존성을 실제 get_service로 연결
from nightwish.webapp import api as api_module  # noqa: E402

app.include_router(api_module.router)
app.dependency_overrides[api_module._svc] = get_service


# -- HTML 페이지 뷰 -----------------------------------------------------------
def _page_view(request, svc, slug, user, error=None):
    page = svc.get_page(slug)
    # 존재하는 슬러그 집합 (위키링크가 깨졌는지 표시용)
    from sqlalchemy import select

    from nightwish.wiki.db import WikiPage
    existing = set(svc.db.scalars(select(WikiPage.slug)))
    measurements = svc.measurements(slug)
    chart = [
        {"metric": m.metric,
         "pct": svc._row_to_measurement(m).relative_improvement * 100,
         "passes": svc._row_to_measurement(m).passes}
        for m in measurements
    ]
    return templates.TemplateResponse(
        request, "page.html",
        {
            "user": user,
            "balance": user.balance if user else 0.0,
            "page": page,
            "body_html": render_markdown(page.body, existing),
            "author": (svc.get_user(page.author_id).display_name
                       if svc.get_user(page.author_id) else page.author_id),
            "verified": svc.is_verified(slug),
            "chart": chart,
            "backlinks": svc.backlinks(slug),
            "broken": svc.broken_links(slug),
            "investors": svc.investors(slug),
            "total_invested": svc.total_invested(slug),
            "error": error,
        },
    )


@app.get("/", response_class=HTMLResponse)
def home(request: Request, svc: WikiService = Depends(get_service)):
    user = current_user(request, svc)
    mine = svc.list_user_pages(user.id) if user else []
    return templates.TemplateResponse(
        request, "home.html",
        {
            "user": user,
            "balance": user.balance if user else 0.0,
            "feed": svc.feed(),
            "mine": mine,
            "verified_set": svc.verified_slugs(),
            "svc": svc,
        },
    )


@app.post("/login")
def login(name: str = Form(...), svc: WikiService = Depends(get_service)):
    try:
        user = svc.ensure_user(name)
    except WikiError:
        return _redirect("/")
    resp = _redirect("/")
    resp.set_cookie(COOKIE, user.id, httponly=True, samesite="lax")
    return resp


@app.post("/logout")
def logout():
    resp = _redirect("/")
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/wiki/new", response_class=HTMLResponse)
def new_page_form(request: Request, svc: WikiService = Depends(get_service)):
    user = current_user(request, svc)
    if not user:
        return _redirect("/")
    return templates.TemplateResponse(
        request, "new.html", {"user": user, "balance": user.balance}
    )


@app.post("/wiki")
def create_page(
    request: Request,
    title: str = Form(...),
    body: str = Form(""),
    shared: str = Form(None),
    svc: WikiService = Depends(get_service),
):
    user = current_user(request, svc)
    if not user:
        return _redirect("/")
    try:
        page = svc.create_page(user.id, title, body, shared=bool(shared))
    except WikiError:
        return _redirect("/wiki/new")
    return _redirect(f"/wiki/{page.slug}")


@app.get("/wiki/{slug}", response_class=HTMLResponse)
def view_page(request: Request, slug: str, svc: WikiService = Depends(get_service)):
    user = current_user(request, svc)
    if svc.get_page(slug) is None:
        return templates.TemplateResponse(
            request, "missing.html", {"user": user, "slug": slug}, status_code=404
        )
    return _page_view(request, svc, slug, user)


@app.post("/wiki/{slug}/share")
def toggle_share(request: Request, slug: str, svc: WikiService = Depends(get_service)):
    page = svc.get_page(slug)
    if page is not None:
        svc.set_shared(slug, not page.shared)
    return _redirect(f"/wiki/{slug}")


@app.post("/wiki/{slug}/edit")
def edit_page(request: Request, slug: str, body: str = Form(""),
              svc: WikiService = Depends(get_service)):
    if svc.get_page(slug) is not None:
        svc.edit_page(slug, body)
    return _redirect(f"/wiki/{slug}")


@app.post("/wiki/{slug}/invest")
def invest(request: Request, slug: str, amount: float = Form(...),
           svc: WikiService = Depends(get_service)):
    user = current_user(request, svc)
    if not user or svc.get_page(slug) is None:
        return _redirect(f"/wiki/{slug}")
    try:
        svc.invest(user.id, slug, amount)
    except (WikiError, InsufficientPoints) as exc:
        return _page_view(request, svc, slug, user, error=str(exc))
    return _redirect(f"/wiki/{slug}")


@app.post("/wiki/{slug}/verify")
def verify(
    request: Request,
    slug: str,
    metric: str = Form(...),
    baseline: float = Form(...),
    observed: float = Form(...),
    direction: str = Form("higher_better"),
    min_rel_improvement: float = Form(0.0),
    svc: WikiService = Depends(get_service),
):
    if svc.get_page(slug) is not None:
        svc.verify(slug, Measurement(
            metric=metric, baseline=baseline, observed=observed,
            direction=Direction(direction), min_rel_improvement=min_rel_improvement,
        ))
    return _redirect(f"/wiki/{slug}")
