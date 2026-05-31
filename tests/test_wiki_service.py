import pytest

from nightwish.economy import InsufficientPoints
from nightwish.verification import Direction, Measurement
from nightwish.wiki import StubBookkeeper, WikiError, WikiService, slugify


def make():
    return WikiService(initial_grant=100.0, reward_rate=0.20)


def test_slugify_keeps_hangul():
    assert slugify("무도장 사출 High Gloss!") == "무도장-사출-high-gloss"
    assert slugify("   ") == "untitled"


def test_bookkeeper_summary_and_links():
    bk = StubBookkeeper()
    body = "첫 문장이다. 둘째 문장. 관련: [[금형 온도]] 와 [[소재 선택|소재]]."
    assert bk.summarize("t", body) == "첫 문장이다."
    assert bk.extract_links(body) == ["금형-온도", "소재-선택"]


def test_create_page_runs_bookkeeping():
    s = make()
    s.ensure_user("Json")
    p = s.create_page("json", "하이그로시", "무도장 사출. 참고 [[금형 온도]].")
    assert p.slug == "하이그로시"
    assert p.summary == "무도장 사출."
    assert p.links == ["금형-온도"]


def test_new_user_gets_initial_grant():
    s = make()
    u = s.ensure_user("Alice")
    assert s.balance(u.id) == 100.0
    # 같은 이름은 같은 사용자 (재지급 없음)
    s.ensure_user("Alice")
    assert s.balance(u.id) == 100.0


def test_share_and_feed():
    s = make()
    s.ensure_user("Json")
    s.create_page("json", "A", "본문", shared=False)
    s.create_page("json", "B", "본문", shared=True)
    feed = s.feed()
    assert [p.slug for p in feed] == ["b"]
    s.set_shared("a", True)
    assert {p.slug for p in s.feed()} == {"a", "b"}


def test_backlinks_and_broken_links():
    s = make()
    s.ensure_user("Json")
    s.create_page("json", "금형 온도", "사출 금형 온도 페이지")
    s.create_page("json", "하이그로시", "참고 [[금형 온도]] 와 [[없는 문서]].")
    assert [p.slug for p in s.backlinks("금형-온도")] == ["하이그로시"]
    assert s.broken_links("하이그로시") == ["없는-문서"]


def test_invest_locks_points():
    s = make()
    s.ensure_user("Json")
    s.create_page("json", "P", "본문")
    s.invest("json", "p", 30.0)
    assert s.balance("json") == 70.0
    assert s.total_invested("p") == 30.0


def test_cannot_invest_more_than_balance():
    s = make()
    s.ensure_user("Json")
    s.create_page("json", "P", "본문")
    with pytest.raises(InsufficientPoints):
        s.invest("json", "p", 1000.0)


def test_unverified_page_has_no_reward_flow():
    """인증 안 된 페이지: 투자는 그냥 잠김, 선행자 보상 없음."""
    s = make()
    s.ensure_user("A")
    s.ensure_user("B")
    s.create_page("a", "P", "본문")
    s.invest("a", "p", 20.0)
    payouts = s.invest("b", "p", 50.0)  # 미인증 -> 보상 없음
    assert payouts == {}
    assert s.balance("a") == 80.0  # A는 보상 못 받음


def test_verified_page_rewards_earlier_investors():
    """인증 투자: 검증된 페이지에 후속 투자가 들어오면 선행 투자자가 보상."""
    s = make()
    for name in ["A", "B", "C"]:
        s.ensure_user(name)
    s.create_page("a", "P", "공장 불량 해결책")
    s.invest("a", "p", 20.0)   # A가 먼저
    s.invest("b", "p", 20.0)   # B가 다음 (아직 미인증 -> 보상 없음)
    # 외부 측정으로 인증
    s.verify("p", Measurement("defect_rate", 8.0, 2.0,
                              Direction.LOWER_BETTER, min_rel_improvement=0.2))
    assert s.is_verified("p")
    # C가 인증 후 50 투자 -> 풀 10이 선행자(A,B)에게, A가 더 많이
    payouts = s.invest("c", "p", 50.0)
    assert round(sum(payouts.values()), 6) == 10.0  # 50 * 0.20
    assert payouts["a"] > payouts["b"]               # 먼저 투자한 A가 더
    assert s.balance("a") == 80.0 + payouts["a"]


def test_reward_pool_is_conserved_not_minted():
    """보상은 신규 발행이 아니라 이번 투자에서 떼어낸다 (총량 보존)."""
    s = make()
    for name in ["A", "C"]:
        s.ensure_user(name)
    s.create_page("a", "P", "x")
    s.invest("a", "p", 20.0)
    s.verify("p", Measurement("yield", 80.0, 95.0, Direction.HIGHER_BETTER))
    before = sum(s.balance(u) for u in s.users) + s.total_invested("p")
    s.invest("c", "p", 50.0)
    after = sum(s.balance(u) for u in s.users) + s.total_invested("p")
    assert round(before, 6) == round(after, 6)
