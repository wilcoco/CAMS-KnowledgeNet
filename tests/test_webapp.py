import pytest
from fastapi.testclient import TestClient

import nightwish.webapp.app as appmod
from nightwish.webapp.app import app
from nightwish.webapp.render import render_markdown
from nightwish.wiki import WikiService


@pytest.fixture(autouse=True)
def fresh_service():
    """각 테스트마다 인메모리 서비스 초기화."""
    appmod.service = WikiService()
    yield


def login(name):
    """이름으로 로그인한 클라이언트(쿠키 보유)를 만든다."""
    c = TestClient(app)
    r = c.post("/login", data={"name": name}, follow_redirects=False)
    assert r.status_code == 303
    return c


def test_render_markdown_wikilinks_and_safety():
    html = render_markdown("# 제목\n참고 [[금형 온도]] <script>", {"금형-온도"})
    assert "<h1>제목</h1>" in html
    assert '<a class="wikilink" href="/wiki/금형-온도">금형 온도</a>' in html
    assert "&lt;script&gt;" in html  # 이스케이프됨
    # 없는 링크는 missing 클래스
    assert "missing" in render_markdown("[[없음]]", set())


def test_home_anonymous_ok():
    c = TestClient(app)
    r = c.get("/")
    assert r.status_code == 200
    assert "검증된 소셜 위키" in r.text


def test_login_grants_points_and_create_page():
    c = login("Json")
    r = c.get("/")
    assert "100 P" in r.text
    # 페이지 생성 -> 페이지로 리다이렉트, 요약/본문 노출
    r = c.post("/wiki", data={"title": "하이그로시", "body": "무도장 사출. [[금형 온도]]"},
               follow_redirects=True)
    assert r.status_code == 200
    assert "하이그로시" in r.text
    assert appmod.service.pages["하이그로시"].summary == "무도장 사출."


def test_share_shows_in_feed():
    c = login("Json")
    c.post("/wiki", data={"title": "A", "body": "x", "shared": "1"})
    r = TestClient(app).get("/")  # 익명도 피드에서 공유글을 본다
    assert "A" in r.text


def test_invest_unverified_then_verified_rewards_earlier():
    a = login("A")
    b = login("B")
    cc = login("C")
    a.post("/wiki", data={"title": "P", "body": "공장 불량 해결"})

    a.post("/wiki/p/invest", data={"amount": "20"})
    b.post("/wiki/p/invest", data={"amount": "20"})  # 미인증 -> 보상 없음
    svc = appmod.service
    assert svc.balance("a") == 80.0  # 아직 보상 없음

    # 인증
    a.post("/wiki/p/verify", data={
        "metric": "defect_rate", "baseline": "8", "observed": "2",
        "direction": "lower_better", "min_rel_improvement": "0.2"})
    assert svc.is_verified("p")

    # 인증 후 C가 50 투자 -> 풀 10이 A,B에게 (A가 더 많이)
    cc.post("/wiki/p/invest", data={"amount": "50"})
    assert svc.balance("a") > 80.0
    assert (svc.balance("a") - 80.0) > (svc.balance("b") - 80.0)


def test_invest_over_balance_shows_error():
    a = login("A")
    a.post("/wiki", data={"title": "P", "body": "x"})
    r = a.post("/wiki/p/invest", data={"amount": "9999"}, follow_redirects=True)
    assert "잔액 부족" in r.text


def test_unknown_page_404():
    r = TestClient(app).get("/wiki/없는문서")
    assert r.status_code == 404
    assert "아직 없는 페이지" in r.text
