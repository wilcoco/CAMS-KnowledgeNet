"""End-to-end tests for the HTTP service, incl. JSON-snapshot persistence."""

import pytest
from fastapi.testclient import TestClient

from nightwish import service, store


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "state.json")
    service.reset_service(db, hub_mode="count")
    with TestClient(service.app) as c:
        c.db = db  # stash for persistence assertions
        yield c


def test_ask_creates_node_and_three_stages(client):
    # ② AI answers -> a node is materialised
    r = client.post("/api/ask", json={"question": "사출 하이그로시?", "asker": "Json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stage"] == "ai" and body["node"] is not None
    nid = body["node"]["id"]

    # ① same question now resolves from the existing ontology (search hit)
    r2 = client.post("/api/ask", json={"question": "사출 하이그로시?", "asker": "B"})
    assert r2.json()["stage"] == "search"

    # ③ a [tacit] question makes the stub AI decline -> unresolved bottleneck
    r3 = client.post("/api/ask", json={"question": "[tacit] 카토의 손끝", "asker": "C"})
    assert r3.json()["stage"] == "unresolved"


def test_fork_follow_contribute_and_scores(client):
    root = client.post("/api/ask", json={"question": "Q1", "asker": "Json"}).json()["node"]["id"]
    # fork: a competing answer
    fk = client.post(f"/api/nodes/{root}/fork",
                     json={"author": "C", "answer": "다른 답", "stake": 50}).json()
    assert fk["action"] == "fork"
    # follow: agreement piles onto the root -> earlier linkers earn hub
    client.post(f"/api/nodes/{root}/follow", json={"follower": "B", "stake": 10})
    client.post(f"/api/nodes/{root}/follow", json={"follower": "D", "stake": 10})

    # large stake without value-add must be rejected by the stake rule
    bad = client.post(f"/api/nodes/{root}/contribute",
                      json={"author": "E", "answer": "x", "stake": 999, "value_add": False})
    assert bad.status_code == 400

    scores = client.get("/api/scores").json()
    assert scores["mode"] == "count"
    # someone earned hub from the pile-on
    assert any(r["hub"] > 0 for r in scores["hub_ranking"])


def test_verify_gate(client):
    nid = client.post("/api/ask", json={"question": "불량 원인?", "asker": "Json"}).json()["node"]["id"]
    r = client.post(f"/api/nodes/{nid}/verify", json={
        "metric": "불량률", "baseline": 8.0, "observed": 2.0,
        "direction": "lower_better", "min_rel_improvement": 0.2}).json()
    assert r["passed"] is True and r["verified"] is True


def test_mint_and_ledger(client):
    client.post("/api/mint", json={"account": "Json", "amount": 1000})
    led = client.get("/api/ledger").json()
    assert led["available"]["Json"] == 1000.0


def test_persistence_survives_reload(client):
    client.post("/api/mint", json={"account": "Json", "amount": 100})
    client.post("/api/ask", json={"question": "지속?", "asker": "Json"})
    before = client.get("/api/state").json()["node_count"]

    # reload a brand-new state from the same snapshot file
    reloaded = store.load(client.db)
    assert reloaded is not None
    assert len(reloaded.tree.nodes) == before
    assert reloaded.economy.ledger.balance("Json") == 100.0
    assert reloaded.hub_mode == "count"
