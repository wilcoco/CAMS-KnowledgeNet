"""JSON REST API — `/api/*`.

HTML 폼과 같은 도메인 서비스(:class:`WikiService`) 위에 얹은 프로그램용 인터페이스.
사용자 식별은 MVS답게 단순히 ``X-User`` 헤더(표시 이름)로 한다 — 없거나 새 이름이면
사용자를 만들고 초기 포인트를 지급한다. 인증·토큰은 범위 밖.

엔드포인트:
  GET  /api/health
  GET  /api/feed
  POST /api/pages                  {title, body, shared}        (X-User 필요)
  GET  /api/pages/{slug}
  POST /api/pages/{slug}/invest    {amount}                     (X-User 필요)
  POST /api/pages/{slug}/verify    {metric, baseline, observed, direction, min_rel_improvement}
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from nightwish.verification import Direction, Measurement
from nightwish.wiki import InsufficientPoints, WikiError, WikiService

router = APIRouter(prefix="/api", tags=["api"])


def _svc() -> WikiService:  # app.py에서 dependency_override로 실제 구현 주입
    raise RuntimeError("get_service dependency not wired")


def _require_user(svc: WikiService, x_user: Optional[str]):
    if not x_user:
        raise HTTPException(401, "X-User 헤더가 필요합니다")
    try:
        return svc.ensure_user(x_user)
    except WikiError as exc:
        raise HTTPException(400, str(exc))


def _page_dto(svc: WikiService, slug: str) -> dict:
    page = svc.get_page(slug)
    if page is None:
        raise HTTPException(404, f"없는 페이지: {slug}")
    return {
        "slug": page.slug,
        "title": page.title,
        "summary": page.summary,
        "body": page.body,
        "author_id": page.author_id,
        "shared": page.shared,
        "links": page.links,
        "entities": page.entities,
        "verified": svc.is_verified(slug),
        "total_invested": svc.total_invested(slug),
        "investors": svc.investors(slug),
        "backlinks": [p.slug for p in svc.backlinks(slug)],
        "broken_links": svc.broken_links(slug),
    }


# -- 요청 스키마 --------------------------------------------------------------
class CreatePageBody(BaseModel):
    title: str
    body: str = ""
    shared: bool = False


class InvestBody(BaseModel):
    amount: float = Field(gt=0)


class VerifyBody(BaseModel):
    metric: str
    baseline: float
    observed: float
    direction: str = "higher_better"
    min_rel_improvement: float = 0.0


# -- 엔드포인트 ---------------------------------------------------------------
@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/feed")
def feed(svc: WikiService = Depends(_svc)):
    return [
        {"slug": p.slug, "title": p.title, "summary": p.summary,
         "author_id": p.author_id, "verified": svc.is_verified(p.slug),
         "total_invested": svc.total_invested(p.slug)}
        for p in svc.feed()
    ]


@router.post("/pages", status_code=201)
def create_page(body: CreatePageBody, svc: WikiService = Depends(_svc),
                x_user: Optional[str] = Header(default=None)):
    user = _require_user(svc, x_user)
    try:
        page = svc.create_page(user.id, body.title, body.body, shared=body.shared)
    except WikiError as exc:
        raise HTTPException(409, str(exc))
    return _page_dto(svc, page.slug)


@router.get("/pages/{slug}")
def get_page(slug: str, svc: WikiService = Depends(_svc)):
    return _page_dto(svc, slug)


@router.post("/pages/{slug}/invest")
def invest(slug: str, body: InvestBody, svc: WikiService = Depends(_svc),
           x_user: Optional[str] = Header(default=None)):
    user = _require_user(svc, x_user)
    if svc.get_page(slug) is None:
        raise HTTPException(404, f"없는 페이지: {slug}")
    try:
        payouts = svc.invest(user.id, slug, body.amount)
    except InsufficientPoints as exc:
        raise HTTPException(402, str(exc))
    except WikiError as exc:
        raise HTTPException(400, str(exc))
    return {"rewarded_earlier_investors": payouts,
            "balance": svc.balance(user.id),
            "page": _page_dto(svc, slug)}


@router.post("/pages/{slug}/verify")
def verify(slug: str, body: VerifyBody, svc: WikiService = Depends(_svc)):
    if svc.get_page(slug) is None:
        raise HTTPException(404, f"없는 페이지: {slug}")
    try:
        direction = Direction(body.direction)
    except ValueError:
        raise HTTPException(400, "direction은 higher_better 또는 lower_better")
    passed = svc.verify(slug, Measurement(
        metric=body.metric, baseline=body.baseline, observed=body.observed,
        direction=direction, min_rel_improvement=body.min_rel_improvement,
    ))
    return {"passed": passed, "verified": svc.is_verified(slug)}
