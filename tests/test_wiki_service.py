import pytest

from nightwish.verification import Direction, Measurement
from nightwish.wiki import (
    InsufficientPoints,
    StubBookkeeper,
    WikiError,
    WikiService,
    init_db,
    make_engine,
    make_session_factory,
    slugify,
)


@pytest.fixture
def svc():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    session = make_session_factory(engine)()
    return WikiService(session, StubBookkeeper(), initial_grant=100.0, reward_rate=0.20)


def test_slugify_keeps_hangul():
    assert slugify("무도장 사출 High Gloss!") == "무도장-사출-high-gloss"
    assert slugify("   ") == "untitled"


def test_stub_bookkeeper_analyze():
    bk = StubBookkeeper()
    r = bk.analyze("t", "첫 문장이다. 둘째. 관련 [[금형 온도]] 와 [[소재 선택|소재]].")
    assert r.summary == "첫 문장이다."
    assert r.links == ["금형-온도", "소재-선택"]


def test_create_page_runs_bookkeeping(svc):
    svc.ensure_user("Json")
    p = svc.create_page("json", "하이그로시", "무도장 사출. 참고 [[금형 온도]].")
    assert p.slug == "하이그로시"
    assert svc.get_page("하이그로시").summary == "무도장 사출."
    assert svc.get_page("하이그로시").links == ["금형-온도"]


def test_new_user_gets_initial_grant_once(svc):
    u = svc.ensure_user("Alice")
    assert svc.balance(u.id) == 100.0
    svc.ensure_user("Alice")  # 동일 이름 = 동일 사용자, 재지급 없음
    assert svc.balance("alice") == 100.0


def test_share_and_feed(svc):
    svc.ensure_user("Json")
    svc.create_page("json", "A", "본문", shared=False)
    svc.create_page("json", "B", "본문", shared=True)
    assert [p.slug for p in svc.feed()] == ["b"]
    svc.set_shared("a", True)
    assert {p.slug for p in svc.feed()} == {"a", "b"}


def test_backlinks_and_broken_links(svc):
    svc.ensure_user("Json")
    svc.create_page("json", "금형 온도", "사출 금형 온도 페이지")
    svc.create_page("json", "하이그로시", "참고 [[금형 온도]] 와 [[없는 문서]].")
    assert [p.slug for p in svc.backlinks("금형-온도")] == ["하이그로시"]
    assert svc.broken_links("하이그로시") == ["없는-문서"]


def test_invest_locks_points(svc):
    svc.ensure_user("Json")
    svc.create_page("json", "P", "본문")
    svc.invest("json", "p", 30.0)
    assert svc.balance("json") == 70.0
    assert svc.total_invested("p") == 30.0


def test_cannot_invest_more_than_balance(svc):
    svc.ensure_user("Json")
    svc.create_page("json", "P", "본문")
    with pytest.raises(InsufficientPoints):
        svc.invest("json", "p", 1000.0)


def test_unverified_page_has_no_reward_flow(svc):
    svc.ensure_user("A")
    svc.ensure_user("B")
    svc.create_page("a", "P", "본문")
    svc.invest("a", "p", 20.0)
    payouts = svc.invest("b", "p", 50.0)  # 미인증 -> 보상 없음
    assert payouts == {}
    assert svc.balance("a") == 80.0


def test_verified_page_rewards_earlier_investors(svc):
    for n in ["A", "B", "C"]:
        svc.ensure_user(n)
    svc.create_page("a", "P", "공장 불량 해결책")
    svc.invest("a", "p", 20.0)   # A 먼저
    svc.invest("b", "p", 20.0)   # B 다음 (아직 미인증)
    svc.verify("p", Measurement("defect_rate", 8.0, 2.0,
                                Direction.LOWER_BETTER, min_rel_improvement=0.2))
    assert svc.is_verified("p")
    payouts = svc.invest("c", "p", 50.0)   # 인증 후: 풀 10 -> A,B (A 더 많이)
    assert round(sum(payouts.values()), 6) == 10.0
    assert payouts["a"] > payouts["b"]
    assert svc.balance("a") == 80.0 + payouts["a"]
    # 수익이 투자 현황에 누적 기록됨
    earned = {row["user_id"]: row["earned"] for row in svc.investors("p")}
    assert earned["a"] == pytest.approx(payouts["a"])


def test_reward_pool_conserved_not_minted(svc):
    for n in ["A", "C"]:
        svc.ensure_user(n)
    svc.create_page("a", "P", "x")
    svc.invest("a", "p", 20.0)
    svc.verify("p", Measurement("yield", 80.0, 95.0, Direction.HIGHER_BETTER))
    before = svc.balance("a") + svc.balance("c") + svc.total_invested("p")
    svc.invest("c", "p", 50.0)
    after = svc.balance("a") + svc.balance("c") + svc.total_invested("p")
    assert round(before, 6) == round(after, 6)


def test_persistence_survives_new_service_on_same_engine():
    """같은 엔진에 새 세션/서비스를 열어도 데이터가 남아 있다 (영속성)."""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    Session = make_session_factory(engine)
    s1 = WikiService(Session(), StubBookkeeper())
    s1.ensure_user("Json")
    s1.create_page("json", "P", "본문", shared=True)
    s2 = WikiService(Session(), StubBookkeeper())  # 새 세션
    assert s2.get_page("p") is not None
    assert [p.slug for p in s2.feed()] == ["p"]


def test_unknown_user_or_page_errors(svc):
    with pytest.raises(WikiError):
        svc.create_page("ghost", "P", "x")
    svc.ensure_user("A")
    with pytest.raises(WikiError):
        svc.invest("a", "nope", 5.0)
