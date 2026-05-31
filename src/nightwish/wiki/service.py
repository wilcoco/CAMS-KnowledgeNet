"""WikiService — 위키 + 소셜 쉐어링 + 인증 투자 (영속).

상태는 SQLAlchemy 세션에 저장한다(로컬 SQLite / Railway Postgres). 도메인 규칙:

* **위키 + LLM 북키핑** — 페이지 생성/편집 시 북키퍼가 요약·엔티티·링크 갱신.
* **소셜** — 공유/피드/백링크.
* **인증** — 외부 측정(:class:`nightwish.verification.Measurement`)으로 페이지 검증.
* **인증 투자** — 검증된 페이지에 한해 후속 투자의 일부가 *먼저 투자한* 사람에게
  흐른다(:mod:`nightwish.wiki.rewards`). 보상은 신규 발행이 아니라 이번 투자에서
  떼어내므로 총량 보존.

각 변경 메서드는 자체적으로 커밋한다(요청 단위 세션 가정).
"""

from __future__ import annotations

from sqlalchemy import func, select

from nightwish.verification import Direction, Measurement
from nightwish.wiki.bookkeeper import Bookkeeper, StubBookkeeper, slugify
from nightwish.wiki.db import MeasurementRow, Stake, User, WikiPage
from nightwish.wiki.rewards import early_investor_rewards


class WikiError(Exception):
    pass


class InsufficientPoints(WikiError):
    pass


class WikiService:
    def __init__(
        self,
        session,
        bookkeeper: Bookkeeper | None = None,
        *,
        initial_grant: float = 100.0,
        reward_rate: float = 0.20,
    ) -> None:
        self.db = session
        self.bookkeeper = bookkeeper or StubBookkeeper()
        self.initial_grant = initial_grant
        self.reward_rate = reward_rate

    # -- 사용자 ----------------------------------------------------------------
    def ensure_user(self, name: str) -> User:
        uid = slugify(name)
        if not uid or uid == "untitled":
            raise WikiError("이름이 비어 있습니다")
        user = self.db.get(User, uid)
        if user is None:
            user = User(id=uid, display_name=name.strip(), balance=self.initial_grant)
            self.db.add(user)
            self.db.commit()
        return user

    def get_user(self, uid: str | None) -> User | None:
        return self.db.get(User, uid) if uid else None

    def balance(self, uid: str) -> float:
        user = self.db.get(User, uid)
        return user.balance if user else 0.0

    # -- 페이지 (위키 + 북키핑) -------------------------------------------------
    def create_page(
        self, author_id: str, title: str, body: str, *, shared: bool = False
    ) -> WikiPage:
        if self.db.get(User, author_id) is None:
            raise WikiError(f"알 수 없는 사용자 {author_id!r}")
        slug = slugify(title)
        if self.db.get(WikiPage, slug) is not None:
            raise WikiError(f"이미 존재하는 페이지: {slug!r}")
        result = self.bookkeeper.analyze(title, body)
        page = WikiPage(
            slug=slug, title=title.strip(), body=body, author_id=author_id,
            shared=shared, summary=result.summary,
        )
        page.links = result.links
        page.entities = result.entities
        self.db.add(page)
        self.db.commit()
        return page

    def edit_page(self, slug: str, body: str) -> WikiPage:
        page = self._require_page(slug)
        result = self.bookkeeper.analyze(page.title, body)
        page.body = body
        page.summary = result.summary
        page.links = result.links
        page.entities = result.entities
        from datetime import datetime
        page.updated_at = datetime.utcnow()
        self.db.commit()
        return page

    def get_page(self, slug: str) -> WikiPage | None:
        return self.db.get(WikiPage, slug)

    def _require_page(self, slug: str) -> WikiPage:
        page = self.db.get(WikiPage, slug)
        if page is None:
            raise WikiError(f"알 수 없는 페이지 {slug!r}")
        return page

    def list_user_pages(self, author_id: str) -> list[WikiPage]:
        return list(self.db.scalars(
            select(WikiPage).where(WikiPage.author_id == author_id)
            .order_by(WikiPage.updated_at.desc())
        ))

    # -- 소셜 ------------------------------------------------------------------
    def set_shared(self, slug: str, shared: bool) -> WikiPage:
        page = self._require_page(slug)
        page.shared = shared
        self.db.commit()
        return page

    def feed(self) -> list[WikiPage]:
        return list(self.db.scalars(
            select(WikiPage).where(WikiPage.shared.is_(True))
            .order_by(WikiPage.updated_at.desc())
        ))

    def backlinks(self, slug: str) -> list[WikiPage]:
        return [p for p in self.db.scalars(select(WikiPage))
                if slug in p.links and p.slug != slug]

    def broken_links(self, slug: str) -> list[str]:
        page = self._require_page(slug)
        return [s for s in page.links if self.db.get(WikiPage, s) is None]

    # -- 인증 (외부 측정) ------------------------------------------------------
    def verify(self, slug: str, measurement: Measurement) -> bool:
        self._require_page(slug)
        row = MeasurementRow(
            page_slug=slug, metric=measurement.metric, baseline=measurement.baseline,
            observed=measurement.observed, direction=measurement.direction.value,
            min_rel_improvement=measurement.min_rel_improvement,
        )
        self.db.add(row)
        self.db.commit()
        return measurement.passes

    def measurements(self, slug: str) -> list[MeasurementRow]:
        return list(self.db.scalars(
            select(MeasurementRow).where(MeasurementRow.page_slug == slug)
            .order_by(MeasurementRow.created_at)
        ))

    @staticmethod
    def _row_to_measurement(row: MeasurementRow) -> Measurement:
        return Measurement(
            metric=row.metric, baseline=row.baseline, observed=row.observed,
            direction=Direction(row.direction), min_rel_improvement=row.min_rel_improvement,
        )

    def is_verified(self, slug: str) -> bool:
        return any(self._row_to_measurement(r).passes for r in self.measurements(slug))

    def verified_slugs(self) -> set[str]:
        return {p.slug for p in self.db.scalars(select(WikiPage)) if self.is_verified(p.slug)}

    # -- 투자 (스테이킹 + 인증 투자 보상) --------------------------------------
    def _stakes(self, slug: str) -> list[Stake]:
        return list(self.db.scalars(
            select(Stake).where(Stake.page_slug == slug).order_by(Stake.order_idx)
        ))

    def invest(self, user_id: str, slug: str, amount: float) -> dict[str, float]:
        user = self.db.get(User, user_id)
        if user is None:
            raise WikiError(f"알 수 없는 사용자 {user_id!r}")
        self._require_page(slug)
        if amount <= 0:
            raise WikiError("투자액은 양수여야 합니다")
        if user.balance + 1e-9 < amount:
            raise InsufficientPoints(f"잔액 부족: {user.balance:.1f} < {amount:.1f}")

        stakes = self._stakes(slug)
        by_user = {s.user_id: s for s in stakes}
        prior_ids = [s.user_id for s in stakes if s.user_id != user_id]

        payouts: dict[str, float] = {}
        if self.is_verified(slug) and prior_ids:
            pool = amount * self.reward_rate
            payouts = early_investor_rewards(prior_ids, pool)
            staked_part = amount - pool
        else:
            staked_part = amount

        user.balance -= amount

        # 현재 사용자의 스테이크 (없으면 새로 — 최초 투자 순서 부여)
        mine = by_user.get(user_id)
        if mine is None:
            next_idx = (max((s.order_idx for s in stakes), default=-1) + 1)
            mine = Stake(user_id=user_id, page_slug=slug, amount=0.0,
                         earned=0.0, order_idx=next_idx)
            self.db.add(mine)
        mine.amount += staked_part

        # 선행 투자자에게 보상 지급
        for prior_id, payout in payouts.items():
            prior = by_user[prior_id]
            prior_user = self.db.get(User, prior_id)
            prior_user.balance += payout
            prior.earned += payout

        self.db.commit()
        return payouts

    def investment(self, slug: str) -> dict[str, float]:
        return {s.user_id: s.amount for s in self._stakes(slug) if s.amount > 1e-9}

    def investors(self, slug: str) -> list[dict]:
        """투자 현황 + 수익. [{user, user_id, amount, earned}] (투자액 내림차순)."""
        rows = []
        for s in self._stakes(slug):
            if s.amount <= 1e-9 and s.earned <= 1e-9:
                continue
            u = self.db.get(User, s.user_id)
            rows.append({"user": u.display_name if u else s.user_id,
                         "user_id": s.user_id, "amount": s.amount, "earned": s.earned})
        return sorted(rows, key=lambda r: -r["amount"])

    def total_invested(self, slug: str) -> float:
        total = self.db.scalar(
            select(func.coalesce(func.sum(Stake.amount), 0.0))
            .where(Stake.page_slug == slug)
        )
        return float(total or 0.0)
