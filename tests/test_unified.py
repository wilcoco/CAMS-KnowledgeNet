"""End-to-end tests for the unified knowledge-graph HTTP app."""

import contextlib
import threading
import time

import pytest
from fastapi.testclient import TestClient

from nightwish import unified


def fake_db(monkeypatch, store):
    """Patch persistence to an in-memory snapshot store (no Postgres).

    The service uses :mod:`nightwish.pgstore` (normalized) in DB mode; the
    snapshot↔rows round-trip is tested separately in ``test_pgstore.py``, so here
    we mock at the snapshot level. ``store['snap']`` holds the current snapshot.
    """
    from nightwish import db, pgstore

    @contextlib.contextmanager
    def transaction(url):
        box = {"data": store.get("snap")}
        yield box
        store["snap"] = box["data"]

    def counts(url):
        snap = store.get("snap") or {"tree": {"nodes": [], "scoring": {"mode": "harmonic"}}}
        nodes = snap["tree"]["nodes"]
        stub = lambda n: n.get("action") == "stub" or (
            n.get("author") == "(stub)" and not n.get("answer"))
        real = [n for n in nodes
                if n.get("action") not in ("pointer", "query", "stub") and not stub(n)]
        return {"node_count": len(real),
                "query_count": sum(1 for n in nodes if n.get("action") == "query"),
                "stub_count": sum(1 for n in nodes if stub(n)),
                "hub_mode": snap["tree"]["scoring"].get("mode", "harmonic")}

    # DB-mode is selected by db.database_url(); migration probes db.load (→ none)
    monkeypatch.setattr(db, "database_url", lambda: "postgres://fake")
    monkeypatch.setattr(db, "init", lambda url: None)
    monkeypatch.setattr(db, "load", lambda url: None)
    monkeypatch.setattr(pgstore, "init", lambda url: None)
    monkeypatch.setattr(pgstore, "load", lambda url: store.get("snap"))
    monkeypatch.setattr(pgstore, "save", lambda url, snap: store.__setitem__("snap", snap))
    monkeypatch.setattr(pgstore, "transaction", transaction)
    def node_closure(url, node_id):
        snap = store.get("snap")
        if not snap:
            return None
        tree, econ = snap["tree"], snap["econ"]
        nodes = {n["id"]: n for n in tree["nodes"]}
        if node_id not in nodes:
            return None
        keep, stack = set(), [node_id]
        while stack:                                   # descendants
            i = stack.pop()
            keep.add(i)
            stack += [n["id"] for n in tree["nodes"] if n.get("parent_id") == i and n["id"] not in keep]
        cur = node_id
        while cur:                                     # ancestors
            keep.add(cur)
            cur = nodes.get(cur, {}).get("parent_id")
        slug = nodes[node_id].get("slug")
        for n in tree["nodes"]:                         # backlinks
            if slug and slug in n.get("links", []):
                keep.add(n["id"])
        for fwd in nodes[node_id].get("links", []):     # forward-link targets (outlinks)
            keep.add(fwd)
        sc = tree["scoring"]
        return {"schema": snap.get("schema", "unified-1"), "tree": {
            "schema": tree.get("schema", 1), "clock": tree.get("clock", 0),
            "large_stake_threshold": tree.get("large_stake_threshold", 25.0),
            "scoring": {"mode": sc.get("mode", "harmonic"),
                        "authority": {k: v for k, v in sc.get("authority", {}).items() if k in keep},
                        "hub": dict(sc.get("hub", {})),
                        "linkers": {k: v for k, v in sc.get("linkers", {}).items() if k in keep}},
            "nodes": [n for n in tree["nodes"] if n["id"] in keep]},
            "econ": {"available": dict(econ.get("available", {})),
                     "staked": {k: v for k, v in econ.get("staked", {}).items() if k in keep},
                     "endorsers": {k: v for k, v in econ.get("endorsers", {}).items() if k in keep},
                     "burned": econ.get("burned", 0.0),
                     "dividend_rate": econ.get("dividend_rate", 0.2),
                     "burn_rate": econ.get("burn_rate", 0.02)}}

    monkeypatch.setattr(pgstore, "counts", counts)
    monkeypatch.setattr(pgstore, "node_closure", node_closure)
    monkeypatch.setattr(pgstore, "meta_info",
                        lambda url: {"updated_at": "2026-06-02T00:00:00+00:00"})


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "app.json")
    unified.reset_service(unified.UnifiedService(db, hub_mode="harmonic"))
    with TestClient(unified.app) as c:
        c.db = db
        yield c
    unified.reset_service(None)


# -- the cycle: search-first ask, then AI mints a frozen node ----------------
def test_ask_always_asks_the_ai_and_mints_a_fresh_node(client):
    r = client.post("/api/ask", json={"question": "사출 불량률 줄이기", "author": "Json"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["stage"] == "ai"
    node = data["node"]
    assert node["frozen"] and node["model"] == "offline-stub"

    # "AI에게 묻기"는 항상 묻는다 — 같은 질문이어도 새 답을 만든다(옛 답 재사용 X).
    again = client.post("/api/ask", json={"question": "사출 불량률 줄이기", "author": "x"}).json()
    assert again["stage"] == "ai"
    assert again["node"]["id"] != node["id"]
    # 다만 관련 기존 답은 밑에 보여줄 수 있게 함께 돌려준다
    assert any(rel["id"] == node["id"] for rel in again["related"])


def test_a_different_question_gets_its_own_fresh_answer(client):
    """A new question must get its own AI answer, never an unrelated old one."""
    first = client.post("/api/ask",
                        json={"question": "도장 없는 컬러 범퍼 생산 방법", "author": "a"}).json()
    other = client.post("/api/ask",
                        json={"question": "사출 불량률 줄이는 방법", "author": "b"}).json()
    assert other["stage"] == "ai"
    assert other["node"]["id"] != first["node"]["id"]


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
def test_get_node_point_read_equals_full_render(monkeypatch, tmp_path):
    """Opening a node via the closure point-read must render identically to the
    full-graph render — same answer, thread, coauthors, backlinks."""
    store: dict = {}
    fake_db(monkeypatch, store)
    unified.reset_service(unified.UnifiedService(str(tmp_path / "x.json")))
    with TestClient(unified.app) as c:
        a = c.post("/api/ask", json={"question": "지붕 단열 [[소재]]", "author": "J"}).json()["node"]["id"]
        c.post(f"/api/nodes/{a}/contribute", json={"kind": "comment", "author": "K", "body": "보강"})
        c.post(f"/api/nodes/{a}/contribute", json={"kind": "followup", "author": "P", "body": "두께는?"})
        c.post("/api/nodes", json={"title": "딴 문서", "body": "[[지붕 단열]] 역링크", "author": "B"})
        c.post("/api/mint", json={"account": "K", "amount": 50})
        c.post("/api/endorse", json={"account": "K", "node_id": a, "amount": 10})
        point = c.get(f"/api/nodes/{a}").json()                # point read via closure
    unified.reset_service(None)

    # render the same node from the WHOLE snapshot via the engine
    tree, econ = unified.UnifiedService._from_data(store["snap"])
    full = unified._node_view(unified._ReadView(tree, econ), a, "public", full=True)

    assert point == full                               # identical render (incl. backlinks)
    assert point["coauthors"][1]["user"] == "K"        # evaluation=authorship intact
    assert any(t["title"] == "두께는?" for t in point["thread"])   # follow-up thread intact


def test_followup_ai_is_anchored_to_parent_chain(client):
    """A follow-up's AI answer must be fed the parent chain's Q&A as context —
    otherwise it answers the follow-up in isolation (no anchoring)."""
    captured = {}

    def capturing_ai(question, prompt=""):
        captured["q"], captured["prompt"] = question, prompt
        return f"답: {question}"

    unified.set_ai(capturing_ai, model="test")
    try:
        nid = client.post("/api/ask",
                          json={"question": "원질문 ABC", "author": "u"}).json()["node"]["id"]
        captured.clear()                              # ignore the ask's own AI call
        client.post(f"/api/nodes/{nid}/contribute",
                    json={"kind": "followup", "author": "u", "body": "후속 XYZ"})
        assert captured["q"] == "후속 XYZ"
        assert "원질문 ABC" in captured["prompt"]      # parent question anchored
        assert "답: 원질문 ABC" in captured["prompt"]   # parent answer anchored
    finally:
        unified.set_ai(unified.offline_answer, model="offline-stub")


def test_expand_creates_linked_concept_with_ai_answer(client):
    """드래그한 내용을 AI에게 물어 연결된 개념 노드로 만든다."""
    src = client.post("/api/ask", json={"question": "범퍼 생산 공정", "author": "u"}).json()["node"]["id"]
    r = client.post(f"/api/nodes/{src}/expand",
                    json={"question": "도장 공정", "author": "u"}).json()
    # 새 개념 노드가 AI 답과 함께 생김
    assert r["target"]["title"] == "도장 공정"
    assert r["target"]["frozen"] and r["target"]["answer"]
    # 원본 → 개념 으로 연결(outlinks)이 생김
    assert any(o["id"] == r["target"]["id"] for o in r["source"]["outlinks"])
    # 거는 사람의 안목(hub)이 적립됨
    hubs = {u["user"]: u["hub"] for u in client.get("/api/scores").json()["top_contributors"]}
    assert hubs.get("u", 0) > 0


def test_expand_links_to_existing_node_without_reanswering(client):
    client.post("/api/ask", json={"question": "열처리", "author": "a"})   # 이미 존재
    src = client.post("/api/ask", json={"question": "표면 처리 개요", "author": "b"}).json()["node"]["id"]
    r = client.post(f"/api/nodes/{src}/expand", json={"question": "열처리", "author": "b"}).json()
    # 기존 노드에 연결만 — 새로 만들지 않음
    assert r["target"]["title"] == "열처리"
    assert any(o["title"] == "열처리" for o in r["source"]["outlinks"])


def test_admin_reset_wipes_everything(client):
    client.post("/api/ask", json={"question": "지울 질문", "author": "a"})
    assert client.get("/api/state").json()["node_count"] >= 1
    # needs the confirm token
    assert client.post("/api/admin/reset").status_code == 400
    r = client.post("/api/admin/reset", params={"confirm": "DELETE-ALL"})
    assert r.status_code == 200 and r.json()["reset"] is True
    assert client.get("/api/state").json()["node_count"] == 0
    assert client.get("/api/search", params={"q": "지울"}).json() == []


def test_dbcheck_reports_file_mode_without_db(client):
    r = client.get("/api/dbcheck").json()
    assert r["backend"] == "file" and r["durable"] is False


def test_state_reports_persistence_backend(client, monkeypatch):
    # default test env has no DATABASE_URL → file mode, flagged non-durable
    p = client.get("/api/state").json()["persistence"]
    assert p["backend"] == "file" and p["durable"] is False

    fake_db(monkeypatch, {})
    p2 = client.get("/api/state").json()["persistence"]
    assert p2["backend"].startswith("postgres") and p2["durable"] is True and p2["db_ok"]


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
    store: dict = {}
    fake_db(monkeypatch, store)

    gone = str(tmp_path / "ephemeral" / "app.json")  # never written in DB mode
    unified.reset_service(unified.UnifiedService(gone))
    with TestClient(unified.app) as c:
        nid = c.post("/api/ask", json={"question": "도장 없는 범퍼", "author": "me"}).json()["node"]["id"]
        c.post("/api/mint", json={"account": "me", "amount": 100})

    assert "snap" in store                  # persisted to the DB, not the file
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


def test_two_instances_sharing_a_db_do_not_clobber(monkeypatch):
    """Two replicas (or a redeploy race) share one snapshot row. A stale instance
    must NOT erase the other's writes — the "DB에 안 박힌다" bug.

    Both services load the (empty) DB at startup, so each holds a stale in-memory
    copy. With the fix, every write reloads-mutates-saves atomically, so the
    second writer builds on the first instead of overwriting it.
    """
    store: dict = {}
    fake_db(monkeypatch, store)
    a = unified.UnifiedService("ignored-a.json")
    b = unified.UnifiedService("ignored-b.json")  # both snapshot the empty DB now

    with TestClient(unified.app) as client:
        # pure-write path (no preceding read) → isolates the read-modify-write
        unified.reset_service(a)
        nid_a = client.post("/api/nodes",
                            json={"title": "문서 A", "body": "본문", "author": "a"}).json()["id"]
        # B, still holding its empty startup memory, writes next
        unified.reset_service(b)
        nid_b = client.post("/api/nodes",
                            json={"title": "문서 B", "body": "본문", "author": "b"}).json()["id"]

        # neither write clobbered the other — both nodes survive in the shared DB
        assert client.get(f"/api/nodes/{nid_a}").status_code == 200
        assert client.get(f"/api/nodes/{nid_b}").status_code == 200
        unified.reset_service(a)
        assert client.get(f"/api/nodes/{nid_b}").status_code == 200   # A sees B's too
    unified.reset_service(None)
