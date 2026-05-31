"""FastAPI 앱 — 검증된 소셜 위키 (MVS).

실행: ``uvicorn nightwish.webapp.app:app --reload`` → http://127.0.0.1:8000

상태는 인메모리(:class:`WikiService` 단일 인스턴스)라 서버 재시작 시 초기화된다.
로그인은 이름만 입력하는 최소 형태(쿠키에 user id 저장) — 인증·보안은 MVS 범위 밖.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from nightwish.economy import InsufficientPoints
from nightwish.verification import Direction, Measurement
from nightwish.webapp.render import render_markdown
from nightwish.wiki import WikiError, WikiService

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="Nightwish — 검증된 소셜 위키 (MVS)")
service = WikiService()

COOKIE = "nw_user"


# -- helpers ------------------------------------------------------------------
def current_user(request: Request):
    uid = request.cookies.get(COOKIE)
    return service.users.get(uid) if uid else None


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def _page_view(request: Request, slug: str, error: str | None = None):
    page = service.pages[slug]
    user = current_user(request)
    existing = set(service.pages)
    investors = [
        {"user": service.users[uid].display_name, "amount": amt}
        for uid, amt in sorted(
            service.investment(slug).items(), key=lambda kv: -kv[1]
        )
        if amt > 1e-9
    ]
    return templates.TemplateResponse(
        request,
        "page.html",
        {
            "user": user,
            "balance": service.balance(user.id) if user else 0.0,
            "page": page,
            "body_html": render_markdown(page.body, existing),
            "author": service.users[page.author_id].display_name,
            "verified": service.is_verified(slug),
            "measurements": service.verification.results.get(slug, []),
            "backlinks": service.backlinks(slug),
            "broken": service.broken_links(slug),
            "investors": investors,
            "total_invested": service.total_invested(slug),
            "error": error,
            "Direction": Direction,
        },
    )


# -- routes -------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = current_user(request)
    mine = (
        sorted(
            [p for p in service.pages.values() if p.author_id == user.id],
            key=lambda p: p.updated_at, reverse=True,
        )
        if user else []
    )
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "balance": service.balance(user.id) if user else 0.0,
            "feed": service.feed(),
            "mine": mine,
            "verified_set": {s for s in service.pages if service.is_verified(s)},
            "service": service,
        },
    )


@app.post("/login")
def login(name: str = Form(...)):
    try:
        user = service.ensure_user(name)
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
def new_page_form(request: Request):
    user = current_user(request)
    if not user:
        return _redirect("/")
    return templates.TemplateResponse(
        request, "new.html",
        {"user": user, "balance": service.balance(user.id)},
    )


@app.post("/wiki")
def create_page(
    request: Request,
    title: str = Form(...),
    body: str = Form(""),
    shared: str = Form(None),
):
    user = current_user(request)
    if not user:
        return _redirect("/")
    try:
        page = service.create_page(
            user.id, title, body, shared=bool(shared)
        )
    except WikiError:
        return _redirect("/wiki/new")
    return _redirect(f"/wiki/{page.slug}")


@app.get("/wiki/{slug}", response_class=HTMLResponse)
def view_page(request: Request, slug: str):
    if slug not in service.pages:
        return templates.TemplateResponse(
            request, "missing.html",
            {"user": current_user(request), "slug": slug},
            status_code=404,
        )
    return _page_view(request, slug)


@app.post("/wiki/{slug}/share")
def toggle_share(request: Request, slug: str):
    if slug in service.pages:
        service.set_shared(slug, not service.pages[slug].shared)
    return _redirect(f"/wiki/{slug}")


@app.post("/wiki/{slug}/edit")
def edit_page(request: Request, slug: str, body: str = Form("")):
    if slug in service.pages:
        service.edit_page(slug, body)
    return _redirect(f"/wiki/{slug}")


@app.post("/wiki/{slug}/invest")
def invest(request: Request, slug: str, amount: float = Form(...)):
    user = current_user(request)
    if not user or slug not in service.pages:
        return _redirect(f"/wiki/{slug}")
    try:
        service.invest(user.id, slug, amount)
    except (WikiError, InsufficientPoints) as exc:
        return _page_view(request, slug, error=str(exc))
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
):
    if slug not in service.pages:
        return _redirect(f"/wiki/{slug}")
    m = Measurement(
        metric=metric, baseline=baseline, observed=observed,
        direction=Direction(direction), min_rel_improvement=min_rel_improvement,
    )
    service.verify(slug, m)
    return _redirect(f"/wiki/{slug}")
