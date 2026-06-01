import pytest
from fastapi.testclient import TestClient

import nightwish.webapp.app as appmod
from nightwish.webapp.app import app
from nightwish.webapp.render import render_markdown
from nightwish.wiki.db import Base


@pytest.fixture(autouse=True)
def fresh_db():
    """각 테스트마다 인메모리 스키마 초기화."""
    Base.metadata.drop_all(appmod.engine)
    Base.metadata.create_all(appmod.engine)
    yield


def login(name):
    c = TestClient(app)
    r = c.post("/login", data={"name": name}, follow_redirects=False)
    assert r.status_code == 303
    return c


def test_render_markdown_wikilinks_and_safety():
    html = render_markdown("# 제목\n참고 [[금형 온도]] <script>", {"금형-온도"})
    assert "<h1>제목</h1>" in html
    assert '<a class="wikilink" href="/wiki/금형-온도">금형 온도</a>' in html
    assert "&lt;script&gt;" in html
    assert "missing" in render_markdown("[[없음]]", set())


def test_home_anonymous_ok():
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "검증된 소셜 위키" in r.text


def test_login_grants_points_and_create_page():
    c = login("Json")
    assert "100 P" in c.get("/").text
    r = c.post("/wiki", data={"title": "하이그로시", "body": "무도장 사출. [[금형 온도]]"},
               follow_redirects=True)
    assert r.status_code == 200 and "하이그로시" in r.text


def test_share_shows_in_feed():
    c = login("Json")
    c.post("/wiki", data={"title": "A", "body": "x", "shared": "1"})
    assert "A" in TestClient(app).get("/").text  # 익명도 공유글 노출


def test_invest_unverified_then_verified_rewards_earlier():
    a, b, cc = login("A"), login("B"), login("C")
    a.post("/wiki", data={"title": "P", "body": "공장 불량 해결"})
    a.post("/wiki/p/invest", data={"amount": "20"})
    b.post("/wiki/p/invest", data={"amount": "20"})  # 미인증 -> 보상 없음

    # 인증 후 페이지에 배지/차트 노출
    a.post("/wiki/p/verify", data={
        "metric": "defect", "baseline": "8", "observed": "2",
        "direction": "lower_better", "min_rel_improvement": "0.2"})
    page = a.get("/wiki/p").text
    assert "인증됨" in page

    cc.post("/wiki/p/invest", data={"amount": "50"})
    # 수익이 페이지에 표시됨
    assert "수익" in a.get("/wiki/p").text


def test_invest_over_balance_shows_error():
    a = login("A")
    a.post("/wiki", data={"title": "P", "body": "x"})
    r = a.post("/wiki/p/invest", data={"amount": "9999"}, follow_redirects=True)
    assert "잔액 부족" in r.text


def test_unknown_page_404():
    r = TestClient(app).get("/wiki/없는문서")
    assert r.status_code == 404 and "아직 없는 페이지" in r.text


def test_missing_link_prefills_ai_draft_for_logged_in_user():
    c = login("Json")
    # 빈 위키링크를 가진 문서를 만든 뒤, 그 링크를 누르면(=없는 페이지 방문)
    # AI 초안이 textarea에 채워져 나온다.
    c.post("/wiki", data={"title": "하이그로시", "body": "무도장 사출 [[금형 온도]]"})
    r = c.get("/wiki/금형-온도")
    assert r.status_code == 404
    assert "AI" in r.text and "초안" in r.text
    assert "## 질문" in r.text          # stub 초안 골격이 textarea에 들어감
    assert "하이그로시" in r.text        # 백링크가 문맥으로 따라옴


def test_missing_link_anonymous_no_draft():
    # 비로그인 사용자에겐 초안을 생성하지 않는다(만들 수 없으므로).
    r = TestClient(app).get("/wiki/금형-온도")
    assert r.status_code == 404
    assert "## 질문" not in r.text
