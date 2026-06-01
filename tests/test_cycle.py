"""The question→search→AI→answer→query→answer cycle (design §6) on the wiki."""

import pytest
from fastapi.testclient import TestClient

from nightwish import mvp
from nightwish.wiki import Wiki, slugify


@pytest.fixture()
def client(tmp_path):
    mvp.reset_service(str(tmp_path / "wiki.json"), hub_mode="harmonic")
    with TestClient(mvp.app) as c:
        yield c


# -- domain ---------------------------------------------------------------- #
def test_query_lifecycle_domain():
    w = Wiki()
    q = w.create_query("게이트 미세조정 손끝감각?", "AI가 못 푼 암묵지", "Json")
    assert q.is_query and q.status == "open"
    assert q in w.open_queries()

    ans = w.answer_query(q.slug, "게이트 미세조정 노하우", "이렇게 한다...", "Kato")
    assert ans.kind == "page" and not ans.is_query
    # answering resolves the query and links the answer back to it
    assert w.get(q.slug).status == "resolved"
    assert q.slug in ans.links
    assert q not in w.open_queries()
    # everything is searchable content
    assert any(p.slug == q.slug for p in w.search("손끝감각"))
    assert any(p.slug == ans.slug for p in w.search("노하우"))


# -- service / cycle ------------------------------------------------------- #
def test_ai_answer_creates_searchable_page(client):
    r = client.post("/api/ai-answer",
                    json={"question": "사출 하이그로시 무도장?", "author": "Json"}).json()
    assert r["kind"] == "page" and r["body"]
    # the AI answer is now findable by the next searcher (the cycle closes)
    found = client.get("/api/search", params={"q": "하이그로시"}).json()
    assert any(p["slug"] == r["slug"] for p in found)


def test_public_query_and_answer_flow(client):
    q = client.post("/api/queries",
                    json={"title": "카토의 손끝 감각?", "detail": "AI가 못 풂", "author": "Json"}).json()
    assert q["kind"] == "query" and q["status"] == "open"
    # shows up in the open-queries backlog
    assert any(x["slug"] == q["slug"] for x in client.get("/api/queries").json())

    ans = client.post(f"/api/queries/{q['slug']}/answer",
                      json={"body": "게이트를 0.1mm 열어준다", "author": "Kato"}).json()
    assert ans["kind"] == "page"
    # query resolved → no longer in the open backlog
    assert all(x["slug"] != q["slug"] for x in client.get("/api/queries").json())


def test_answer_unknown_query_404(client):
    assert client.post("/api/queries/ghost/answer",
                       json={"body": "x", "author": "a"}).status_code == 404


def test_query_persists(client):
    client.post("/api/queries", json={"title": "Q?", "detail": "d", "author": "Json"})
    db = mvp.get_service().db_path
    reloaded = mvp.WikiService(db)
    q = reloaded.wiki.get(slugify("Q?"))
    assert q is not None and q.is_query and q.status == "open"
