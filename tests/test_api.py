import pytest
from fastapi.testclient import TestClient

import nightwish.webapp.app as appmod
from nightwish.webapp.app import app
from nightwish.wiki.db import Base

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(appmod.engine)
    Base.metadata.create_all(appmod.engine)
    yield


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_create_requires_user_header():
    r = client.post("/api/pages", json={"title": "P", "body": "x"})
    assert r.status_code == 401


def test_full_api_flow_invest_reward():
    # A 페이지 생성 (X-User로 사용자 자동 생성 + 초기 포인트)
    r = client.post("/api/pages", headers={"X-User": "A"},
                    json={"title": "P", "body": "공장 불량 [[금형 온도]]", "shared": True})
    assert r.status_code == 201
    body = r.json()
    assert body["slug"] == "p"
    assert body["links"] == ["금형-온도"]
    assert body["verified"] is False

    # 피드 노출
    feed = client.get("/api/feed").json()
    assert any(p["slug"] == "p" for p in feed)

    # A, B 투자 (미인증 -> 보상 없음)
    client.post("/api/pages/p/invest", headers={"X-User": "A"}, json={"amount": 20})
    r = client.post("/api/pages/p/invest", headers={"X-User": "B"}, json={"amount": 20})
    assert r.json()["rewarded_earlier_investors"] == {}

    # 인증
    r = client.post("/api/pages/p/verify", json={
        "metric": "defect", "baseline": 8, "observed": 2,
        "direction": "lower_better", "min_rel_improvement": 0.2})
    assert r.json() == {"passed": True, "verified": True}

    # C 투자 -> 선행 투자자(A,B)에게 보상, A가 더 많이
    r = client.post("/api/pages/p/invest", headers={"X-User": "C"}, json={"amount": 50})
    payouts = r.json()["rewarded_earlier_investors"]
    assert round(sum(payouts.values()), 6) == 10.0
    assert payouts["a"] > payouts["b"]


def test_invest_insufficient_returns_402():
    client.post("/api/pages", headers={"X-User": "A"}, json={"title": "P", "body": "x"})
    r = client.post("/api/pages/p/invest", headers={"X-User": "A"}, json={"amount": 99999})
    assert r.status_code == 402


def test_get_unknown_page_404():
    assert client.get("/api/pages/nope").status_code == 404
