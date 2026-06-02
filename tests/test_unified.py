"""End-to-end tests for the unified knowledge-graph HTTP app."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwish import unified


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "app.json")
    unified.reset_service(unified.UnifiedService(db, hub_mode="harmonic"))
    with TestClient(unified.app) as c:
        c.db = db
        yield c
    unified.reset_service(None)


# -- the cycle: search-first ask, then AI mints a frozen node ----------------
def test_ask_misses_then_ai_answers_a_frozen_node(client):
    r = client.post("/api/ask", json={"question": "사출 불량률 줄이기", "author": "Json"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["stage"] == "ai"
    node = data["node"]
    assert node["frozen"] and node["model"] == "offline-stub"

    # asking again now hits the existing answer (no new node)
    again = client.post("/api/ask", json={"question": "사출 불량률 줄이기", "author": "x"}).json()
    assert again["stage"] == "search"
    assert again["node"]["id"] == node["id"]


# -- the SAME module applies to every slot, recursively ----------------------
def test_recursive_thread_followup_answer_is_itself_a_slot(client):
    nid = client.post("/api/ask", json={"question": "Q루트", "author": "a"}).json()["node"]["id"]

    # 보강 / 정정 / 후속질문 all attach to the answer
    client.post(f"/api/nodes/{nid}/contribute",
                json={"kind": "comment", "author": "b", "body": "보강 의견"})
    client.post(f"/api/nodes/{nid}/contribute",
                json={"kind": "fork", "author": "c", "body": "다른 답"})
    view = client.post(f"/api/nodes/{nid}/contribute",
                       json={"kind": "followup", "author": "d", "body": "후속질문?"}).json()

    thread = view["thread"]
    kinds = {t["kind"] for t in thread}
    assert {"contribute", "fork"} <= kinds
    # the follow-up question node has the AI answer nested *below* it...
    followup = next(t for t in thread if t["title"] == "후속질문?")
    assert len(followup["replies"]) == 1
    ai_answer = followup["replies"][0]
    assert ai_answer["author"] == "AI" and ai_answer["frozen"]

    # ...and that AI answer is itself a slot — we can correct it
    r = client.post(f"/api/nodes/{ai_answer['id']}/contribute",
                    json={"kind": "fork", "author": "e", "body": "그 답을 정정"})
    assert r.status_code == 200, r.text
    deep = client.get(f"/api/nodes/{ai_answer['id']}").json()
    assert any(t["body"] == "그 답을 정정" for t in deep["thread"])


def test_frozen_node_rejects_followup_via_contribution_not_edit(client):
    nid = client.post("/api/ask", json={"question": "동결Q", "author": "a"}).json()["node"]["id"]
    # editing a frozen AI node by re-creating its title is refused
    r = client.post("/api/nodes", json={"title": "동결Q", "body": "몰래수정", "author": "z"})
    assert r.status_code == 409


# -- open query answered in place (one slot keeps identity) ------------------
def test_open_query_answered_in_place(client):
    q = client.post("/api/queries", json={"title": "출처는?", "detail": "근거 필요",
                                          "author": "asker"}).json()
    qid = q["id"]
    assert q["is_query"]
    assert any(t["body"] == "근거 필요" for t in q["thread"])  # detail became a child

    answered = client.post(f"/api/queries/{qid}/answer",
                           json={"body": "사내 측정 로그", "author": "expert"}).json()
    assert answered["id"] == qid and answered["action"] == "root"
    assert client.get("/api/queries").json() == []


def test_query_can_be_answered_by_ai(client):
    qid = client.post("/api/queries", json={"title": "AI가 답할 질문",
                                            "author": "asker"}).json()["id"]
    answered = client.post(f"/api/queries/{qid}/answer",
                           json={"author": "asker", "ai": True}).json()
    assert answered["frozen"] and answered["model"] == "offline-stub"


# -- layers: one-way membrane on the thread + search -------------------------
def test_group_contribution_invisible_to_public(client):
    nid = client.post("/api/ask", json={"question": "공용질문", "author": "a"}).json()["node"]["id"]
    client.post(f"/api/nodes/{nid}/contribute",
                json={"kind": "comment", "author": "b", "body": "그룹메모 sshh",
                      "space": "team-a"})

    public = client.get(f"/api/nodes/{nid}", params={"space": "public"}).json()
    assert public["thread"] == []                                  # not visible publicly
    team = client.get(f"/api/nodes/{nid}", params={"space": "team-a"}).json()
    assert any(t["body"] == "그룹메모 sshh" for t in team["thread"])
    # search must not leak the group note to a public searcher
    assert client.get("/api/search", params={"q": "sshh", "space": "public"}).json() == []


# -- wikilinks accrue authority; economy pays dividends up the chain ---------
def test_wikilink_authority_and_endorse_dividend(client):
    # alice links [[핵심개념]] first; bob links it later → alice's foresight (hub)
    # is validated by the later linker (patent: earlier discoverer earns).
    client.post("/api/nodes", json={"title": "문서X", "body": "[[핵심개념]] 참고",
                                    "author": "alice"})
    client.post("/api/nodes", json={"title": "문서Y", "body": "[[핵심개념]] 또 참고",
                                    "author": "bob"})
    scores = client.get("/api/scores").json()
    users = {u["user"]: u["hub"] for u in scores["top_contributors"]}
    assert users.get("alice", 0) > 0               # earliest linker earns hub

    nid = client.post("/api/ask", json={"question": "배당대상", "author": "author1"}).json()["node"]["id"]
    client.post("/api/mint", json={"account": "backer", "amount": 100})
    r = client.post("/api/endorse", json={"account": "backer", "node_id": nid, "amount": 50}).json()
    assert r["payouts"].get("author1", 0) > 0       # author got a dividend
    assert r["staked_on_node"] > 0
    ledger = client.get("/api/ledger").json()
    assert ledger["burned"] > 0


# -- evaluation IS authorship ------------------------------------------------
def test_endorsing_makes_the_evaluator_a_coauthor_with_foresight(client):
    nid = client.post("/api/ask", json={"question": "평가저작Q", "author": "author1"}).json()["node"]["id"]
    client.post("/api/mint", json={"account": "early", "amount": 100})
    client.post("/api/mint", json={"account": "late", "amount": 100})

    # 'early' evaluates first, then 'late' — both become co-authors, in order
    r1 = client.post("/api/endorse", json={"account": "early", "node_id": nid, "amount": 30}).json()
    co_users = [c["user"] for c in r1["coauthors"]]
    assert co_users == ["author1", "early"]
    assert r1["coauthors"][1]["role"] == "evaluator"

    client.post("/api/endorse", json={"account": "late", "node_id": nid, "amount": 30})
    view = client.get(f"/api/nodes/{nid}").json()
    co = {c["user"]: c for c in view["coauthors"]}
    assert set(co) == {"author1", "early", "late"}
    # the earlier evaluator earned more foresight(hub) than the later one
    assert co["early"]["hub"] > co["late"]["hub"]

    # endorsing again does not duplicate a co-author
    again = client.post("/api/endorse", json={"account": "early", "node_id": nid, "amount": 10}).json()
    assert [c["user"] for c in again["coauthors"]].count("early") == 1


def test_endorsement_lifts_a_qa_in_search_adoption(client):
    # two answers that both match the query; one gets evaluated (adopted)
    a = client.post("/api/ask", json={"question": "용접 결함 원인", "author": "a"}).json()["node"]["id"]
    client.post("/api/ask", json={"question": "용접 결함 점검", "author": "b"})
    client.post("/api/mint", json={"account": "crowd", "amount": 100})
    client.post("/api/endorse", json={"account": "crowd", "node_id": a, "amount": 80})

    hits = client.get("/api/search", params={"q": "용접 결함", "space": "public"}).json()
    assert hits[0]["id"] == a            # the endorsed (adopted) Q&A surfaces first


# -- a slow AI generation must not freeze the rest of the app ----------------
def test_slow_ai_ask_does_not_hold_the_lock(client):
    started = threading.Event()
    release = threading.Event()

    def slow_ai(question, prompt=""):
        started.set()
        release.wait(2.0)          # simulate a multi-second network call
        return "느린 AI 답변"

    unified.set_ai(slow_ai, model="slow-test")
    try:
        result = {}
        t = threading.Thread(
            target=lambda: result.update(
                r=client.post("/api/ask", json={"question": "느린질문", "author": "a"})))
        t.start()
        assert started.wait(2.0)   # the AI call is in flight (lock released)

        # the status poll must still respond promptly while AI generates
        t0 = time.monotonic()
        assert client.get("/api/state").status_code == 200
        assert time.monotonic() - t0 < 1.0

        release.set()
        t.join(3.0)
        assert result["r"].status_code == 200
        assert result["r"].json()["node"]["answer"] == "느린 AI 답변"
    finally:
        release.set()
        unified.set_ai(unified.offline_answer, model="offline-stub")


# -- the UI can prove whether storage is durable -----------------------------
def test_state_reports_persistence_backend(client, monkeypatch):
    # default test env has no DATABASE_URL → file mode, flagged non-durable
    p = client.get("/api/state").json()["persistence"]
    assert p["backend"] == "file" and p["durable"] is False

    from nightwish import db
    monkeypatch.setattr(db, "database_url", lambda: "postgres://fake")
    monkeypatch.setattr(db, "load", lambda url: {"tree": {}, "econ": {}})
    p2 = client.get("/api/state").json()["persistence"]
    assert p2["backend"] == "postgres" and p2["durable"] is True and p2["db_ok"]


# -- persistence round-trips the whole unified snapshot ----------------------
def test_state_persists_across_reload(client):
    nid = client.post("/api/ask", json={"question": "영속질문", "author": "a"}).json()["node"]["id"]
    client.post(f"/api/nodes/{nid}/contribute",
                json={"kind": "comment", "author": "b", "body": "메모"})
    # reload a fresh service from the same db file
    unified.reset_service(unified.UnifiedService(client.db))
    reloaded = client.get(f"/api/nodes/{nid}").json()
    assert reloaded["frozen"]
    assert any(t["body"] == "메모" for t in reloaded["thread"])


def test_durable_db_survives_an_ephemeral_disk_restart(monkeypatch, tmp_path):
    """On Railway the local disk is wiped on restart; state must live in the DB.

    Regression: the unified app used to persist only to a local JSON file, so a
    freshly-asked node vanished on restart and endorse/follow-up 404'd against a
    node the browser still showed. With DATABASE_URL set, the snapshot must go
    to (and reload from) the DB even though the file path no longer exists.
    """
    from nightwish import db

    store: dict = {}
    monkeypatch.setattr(db, "database_url", lambda: "postgres://fake")
    monkeypatch.setattr(db, "init", lambda url: None)
    monkeypatch.setattr(db, "load", lambda url: store.get(1))
    monkeypatch.setattr(db, "save", lambda url, data: store.__setitem__(1, data))

    gone = str(tmp_path / "ephemeral" / "app.json")  # never written in DB mode
    unified.reset_service(unified.UnifiedService(gone))
    with TestClient(unified.app) as c:
        nid = c.post("/api/ask", json={"question": "도장 없는 범퍼", "author": "me"}).json()["node"]["id"]
        c.post("/api/mint", json={"account": "me", "amount": 100})

    assert 1 in store                       # persisted to the DB, not the file
    import os
    assert not os.path.exists(gone)         # the ephemeral file was never created

    # simulate a restart: brand-new process, same DB, no file on disk
    unified.reset_service(unified.UnifiedService(gone))
    with TestClient(unified.app) as c2:
        assert c2.get(f"/api/nodes/{nid}").status_code == 200
        endorsed = c2.post("/api/endorse", json={"account": "me", "node_id": nid, "amount": 10})
        assert endorsed.status_code == 200, endorsed.text
        followup = c2.post(f"/api/nodes/{nid}/contribute",
                           json={"kind": "followup", "author": "me", "body": "열처리 온도?"})
        assert followup.status_code == 200
        assert len(followup.json()["thread"]) == 1
    unified.reset_service(None)
