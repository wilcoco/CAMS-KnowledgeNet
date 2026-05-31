"""WikiService — 위키 + 소셜 쉐어링 + 인증 투자를 한데 묶는 서비스 도메인.

기존 코어를 재사용한다:
* :class:`nightwish.economy.Economy` / ``Ledger`` — 포인트 잔액·투자(스테이킹).
* :class:`nightwish.verification.VerificationRegistry` — 외부 측정 인증.

새로 더하는 것: 페이지/사용자 저장, LLM 북키핑 연동, 공유·피드·백링크, 그리고
**인증 투자 보상**(검증된 페이지에 한해 후속 투자의 일부가 선행 투자자에게).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nightwish.economy import Economy, InsufficientPoints
from nightwish.verification import Measurement, VerificationRegistry
from nightwish.wiki.bookkeeper import Bookkeeper, StubBookkeeper, slugify
from nightwish.wiki.models import User, WikiPage


class WikiError(Exception):
    pass


@dataclass
class WikiService:
    bookkeeper: Bookkeeper = field(default_factory=StubBookkeeper)
    #: 신규 사용자에게 주는 초기 포인트 (투자를 시작할 수 있게)
    initial_grant: float = 100.0
    #: 인증된 페이지에서 후속 투자 중 선행 투자자에게 흐르는 비율
    reward_rate: float = 0.20

    pages: dict[str, WikiPage] = field(default_factory=dict)
    users: dict[str, User] = field(default_factory=dict)
    economy: Economy = field(default_factory=Economy)
    verification: VerificationRegistry = field(default_factory=VerificationRegistry)
    #: slug -> 최초 투자 순서대로의 user_id (중복 없음) = "누가 먼저 알아봤나"
    _invest_order: dict[str, list[str]] = field(default_factory=dict)
    _clock: int = 0

    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    # -- 사용자 ----------------------------------------------------------------
    def ensure_user(self, name: str) -> User:
        """이름으로 사용자를 찾거나 새로 만든다(신규는 초기 포인트 지급)."""
        uid = slugify(name)
        if not uid:
            raise WikiError("이름이 비어 있습니다")
        if uid not in self.users:
            self.users[uid] = User(id=uid, display_name=name.strip())
            self.economy.ledger.mint(uid, self.initial_grant)
        return self.users[uid]

    def balance(self, user_id: str) -> float:
        return self.economy.ledger.balance(user_id)

    # -- 페이지 (위키 + 북키핑) -------------------------------------------------
    def create_page(
        self, author_id: str, title: str, body: str, *, shared: bool = False
    ) -> WikiPage:
        if author_id not in self.users:
            raise WikiError(f"알 수 없는 사용자 {author_id!r}")
        slug = slugify(title)
        if slug in self.pages:
            raise WikiError(f"이미 존재하는 페이지: {slug!r}")
        now = self._tick()
        page = WikiPage(
            slug=slug, title=title.strip(), body=body, author_id=author_id,
            created_at=now, updated_at=now, shared=shared,
            summary=self.bookkeeper.summarize(title, body),
            links=self.bookkeeper.extract_links(body),
        )
        self.pages[slug] = page
        return page

    def edit_page(self, slug: str, body: str) -> WikiPage:
        """본문을 고치면 LLM 북키핑이 요약·링크를 다시 갱신한다."""
        page = self._require(slug)
        page.body = body
        page.summary = self.bookkeeper.summarize(page.title, body)
        page.links = self.bookkeeper.extract_links(body)
        page.touch(self._tick())
        return page

    def _require(self, slug: str) -> WikiPage:
        if slug not in self.pages:
            raise WikiError(f"알 수 없는 페이지 {slug!r}")
        return self.pages[slug]

    # -- 소셜 ------------------------------------------------------------------
    def set_shared(self, slug: str, shared: bool) -> WikiPage:
        page = self._require(slug)
        page.shared = shared
        return page

    def feed(self) -> list[WikiPage]:
        """공유된 페이지를 최신순으로 (소셜 피드)."""
        shared = [p for p in self.pages.values() if p.shared]
        return sorted(shared, key=lambda p: p.updated_at, reverse=True)

    def backlinks(self, slug: str) -> list[WikiPage]:
        """이 페이지를 링크한 다른 페이지들 (옵시디안식 백링크)."""
        return [p for p in self.pages.values() if slug in p.links and p.slug != slug]

    def broken_links(self, slug: str) -> list[str]:
        """이 페이지가 링크했지만 아직 존재하지 않는 슬러그들."""
        page = self._require(slug)
        return [s for s in page.links if s not in self.pages]

    # -- 인증 (외부 측정) ------------------------------------------------------
    def verify(self, slug: str, measurement: Measurement) -> bool:
        """페이지에 외부 측정을 기록한다. 통과하면 '인증됨'이 된다."""
        self._require(slug)
        return self.verification.record(slug, measurement)

    def is_verified(self, slug: str) -> bool:
        return self.verification.is_verified(slug)

    # -- 투자 (스테이킹 + 인증 투자 보상) --------------------------------------
    def invest(self, user_id: str, slug: str, amount: float) -> dict[str, float]:
        """페이지에 포인트를 투자한다.

        페이지가 **인증된** 상태라면, 투자액의 ``reward_rate`` 만큼이 *먼저 투자한*
        사람들에게 흐른다(먼저일수록 더 큰 몫). 인증 전이면 전액이 그냥 잠긴다.
        보상은 신규 발행이 아니라 *이번 투자에서 떼어* 분배하므로 총량은 보존된다.

        반환: 이번 투자로 선행 투자자들이 받은 보상 {user_id: amount}.
        """
        if user_id not in self.users:
            raise WikiError(f"알 수 없는 사용자 {user_id!r}")
        self._require(slug)
        if amount <= 0:
            raise WikiError("투자액은 양수여야 합니다")
        if self.balance(user_id) + 1e-9 < amount:
            raise InsufficientPoints(
                f"잔액 부족: {self.balance(user_id):.1f} < {amount:.1f}"
            )

        ledger = self.economy.ledger
        order = self._invest_order.setdefault(slug, [])
        priors = [u for u in order if u != user_id]

        payouts: dict[str, float] = {}
        if self.is_verified(slug) and priors:
            pool = amount * self.reward_rate
            payouts = self._reward_early(priors, pool)
            staked_part = amount - pool
        else:
            staked_part = amount

        # 전액 차감 후, 잠길 부분만 페이지에 스테이킹 / 보상분은 선행자에게
        ledger.stake(user_id, slug, amount)            # 전액 잠금
        for who, reward in payouts.items():
            ledger.staked[slug][user_id] -= reward     # 잠금분에서 보상 풀 회수
            ledger.available[who] += reward            # 선행 투자자에게 지급
        assert abs(ledger.staked[slug][user_id] - staked_part) < 1e-6

        if user_id not in order:
            order.append(user_id)
        return payouts

    def _reward_early(self, priors: list[str], pool: float) -> dict[str, float]:
        """선행 투자자에게 먼저일수록 큰 몫(256 시간가중의 미니 버전)."""
        n = len(priors)
        weights = {u: (n - i) for i, u in enumerate(priors)}  # 먼저일수록 큰 가중
        total = sum(weights.values())
        return {u: pool * w / total for u, w in weights.items()}

    # -- 뷰 --------------------------------------------------------------------
    def investment(self, slug: str) -> dict[str, float]:
        """페이지별 투자 현황 {user_id: 잠긴 포인트}."""
        return self.economy.ledger.stake_on(slug)

    def total_invested(self, slug: str) -> float:
        return self.economy.ledger.total_staked(slug)
