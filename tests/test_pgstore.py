"""The normalized store must round-trip the full app state losslessly."""

import json

from fastapi.testclient import TestClient

from nightwish import pgstore, unified
from nightwish.tree import OntologyTree
from nightwish.wiki_economy import WikiEconomy


def _canonical(snap: dict) -> dict:
    """Re-serialise a snapshot through the domain objects → canonical form.

    Empty ``linkers`` lists carry no information (a missing key and an empty list
    both mean "no evaluators"), so drop them before comparing — otherwise the
    engine's habit of materialising empty defaultdict entries shows up as a
    spurious diff.
    """
    tree = OntologyTree.from_json(snap["tree"]).to_json()
    econ = WikiEconomy.from_json(snap["econ"]).to_json()
    tree["scoring"]["linkers"] = {
        k: v for k, v in tree["scoring"]["linkers"].items() if v
    }
    return {"tree": tree, "econ": econ}


def _busy_snapshot(tmp_path) -> dict:
    """Drive the app into a rich state touching every table, return its snapshot."""
    db = str(tmp_path / "app.json")
    svc = unified.UnifiedService(db)
    unified.reset_service(svc)
    with TestClient(unified.app) as c:
        a = c.post("/api/ask", json={"question": "도장 없는 범퍼 [[컬러 소재]]",
                                     "author": "Json"}).json()["node"]["id"]
        c.post("/api/ask", json={"question": "사출 온도 설정", "author": "Lee"})
        c.post(f"/api/nodes/{a}/contribute",
               json={"kind": "comment", "author": "Kim", "body": "보강 [[수율]]"})
        c.post(f"/api/nodes/{a}/contribute",
               json={"kind": "followup", "author": "Park", "body": "열처리 온도는?"})
        c.post("/api/queries", json={"title": "공개 질문", "detail": "근거", "author": "Q"})
        c.post("/api/mint", json={"account": "Kim", "amount": 100})
        c.post("/api/mint", json={"account": "Lee", "amount": 100})
        c.post("/api/endorse", json={"account": "Kim", "node_id": a, "amount": 30})
        c.post("/api/endorse", json={"account": "Lee", "node_id": a, "amount": 20})
        # group-private endorse (free-issue group coin) must also round-trip
        c.post("/api/endorse", json={"account": "Acme", "node_id": a,
                                     "amount": 7, "space": "acme"})
        # a contextual unfold (anchored child) must round-trip its anchor
        c.post(f"/api/nodes/{a}/contribute",
               json={"kind": "unfold", "author": "Kim", "anchor": "범퍼", "body": "소재?"})
        snap = svc._snapshot()
    unified.reset_service(None)
    return snap


def test_snapshot_rows_roundtrip_is_lossless(tmp_path):
    snap = _busy_snapshot(tmp_path)
    rebuilt = pgstore.rows_to_snapshot(pgstore.snapshot_to_rows(snap))
    assert _canonical(rebuilt) == _canonical(snap)


def test_roundtrip_preserves_authorship_and_economy(tmp_path):
    snap = _busy_snapshot(tmp_path)
    rows = pgstore.snapshot_to_rows(snap)

    # each entity really is its own row (not one blob)
    assert len(rows["node"]) >= 4
    assert any(r["author"] == "Json" for r in rows["node"])
    # evaluation = authorship: endorsers became linkers, earned hub, hold stakes
    assert {r["evaluator"] for r in rows["linker"]} >= {"Kim", "Lee"}
    assert {r["account"] for r in rows["stake"]} >= {"Kim", "Lee"}
    assert {r["account"] for r in rows["endorser"]} >= {"Kim", "Lee"}
    assert any(r["account"] == "Kim" and r["value"] > 0 for r in rows["user_hub"])

    # and it all comes back identically
    back = pgstore.rows_to_snapshot(rows)
    assert _canonical(back) == _canonical(snap)


def test_rows_to_snapshot_handles_empty():
    snap = pgstore.rows_to_snapshot({})
    assert snap["tree"]["nodes"] == []
    # builds a valid (empty) engine
    OntologyTree.from_json(snap["tree"])
    WikiEconomy.from_json(snap["econ"])


def test_snapshot_is_json_serialisable_as_rows(tmp_path):
    rows = pgstore.snapshot_to_rows(_busy_snapshot(tmp_path))
    json.dumps(rows)  # every row value is a DB-friendly scalar
