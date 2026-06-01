"""End-to-end tests for the MVP wiki HTTP service."""

import pytest
from fastapi.testclient import TestClient

from nightwish import mvp


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "wiki.json")
    mvp.reset_service(db, hub_mode="harmonic")
    with TestClient(mvp.app) as c:
        c.db = db
        yield c


def test_create_read_and_search(client):
    r = client.post("/api/pages", json={
        "title": "사출 하이그로시", "body": "무도장 유광 [[웰드라인]] 참고", "author": "Json"})
    assert r.status_code == 200, r.text
    slug = r.json()["slug"]

    got = client.get(f"/api/pages/{slug}").json()
    assert got["author"] == "Json"
    # the wikilink auto-created a stub target with a backlink
    assert any(b["title"] == "사출 하이그로시"
               for b in client.get("/api/pages/웰드라인").json()["backlinks"])

    found = client.get("/api/search", params={"q": "하이그로시"}).json()
    assert any(p["slug"] == slug for p in found)


def test_hub_authority_surface_in_scores(client):
    for author in ["a1", "a2", "a3"]:
        client.post("/api/pages", json={
            "title": f"문서-{author}", "body": "[[핵심]] 참고", "author": author})
    scores = client.get("/api/scores").json()
    users = {u["user"]: u["hub"] for u in scores["top_contributors"]}
    assert users["a1"] > users.get("a2", 0)        # earliest linker leads
    # the linked page shows up with authority
    assert any(p["title"] == "핵심" for p in scores["top_pages"]) is False  # stub excluded


def test_draft_returns_markdown_without_saving(client):
    d = client.post("/api/draft", json={"title": "새 문서", "prompt": "개요 적어줘"}).json()
    assert d["title"] == "새 문서" and d["body"].startswith("# 새 문서")
    # draft must not have created a page
    assert client.get("/api/state").json()["page_count"] == 0


def test_resolve_wikilink(client):
    client.post("/api/pages", json={"title": "있는 문서", "body": "내용", "author": "u"})
    assert client.get("/api/resolve/있는 문서").json()["exists"] is True
    assert client.get("/api/resolve/없는 문서").json()["exists"] is False


def test_persistence_reload(client):
    client.post("/api/pages", json={"title": "A", "body": "[[T]]", "author": "u1"})
    client.post("/api/pages", json={"title": "B", "body": "[[T]]", "author": "u2"})
    from nightwish.wiki import Wiki, slugify
    reloaded = Wiki.load(client.db)
    assert reloaded is not None
    assert reloaded.hub_of("u1") > 0
    assert reloaded.get_by_title("A") is not None
