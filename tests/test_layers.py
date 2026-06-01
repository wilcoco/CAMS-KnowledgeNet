"""Layered visibility: public commons + group overlays, one-way membrane."""

import pytest
from fastapi.testclient import TestClient

from nightwish import mvp
from nightwish.wiki import Wiki, slugify


# -- domain ---------------------------------------------------------------- #
def test_read_composition_public_and_group():
    w = Wiki()
    w.save_page("공용 문서", "x", "a")                     # public
    w.save_page("그룹 비밀", "y", "a", space="acme")        # acme only
    pub = {p.slug for p in w.search("", space="public")}
    acme = {p.slug for p in w.search("", space="acme")}
    other = {p.slug for p in w.search("", space="other")}
    assert slugify("공용 문서") in pub and slugify("그룹 비밀") not in pub
    assert {slugify("공용 문서"), slugify("그룹 비밀")} <= acme   # public ∪ acme
    assert slugify("그룹 비밀") not in other                      # other group can't see acme


def test_group_stub_inherits_group_space():
    w = Wiki()
    w.save_page("그룹 노트", "[[전용개념]] 참고", "a", space="acme")
    stub = w.get_by_title("전용개념")
    assert stub.space == "acme"            # link target stays in the group layer


# -- service --------------------------------------------------------------- #
@pytest.fixture()
def client(tmp_path):
    mvp.reset_service(str(tmp_path / "wiki.json"), hub_mode="harmonic")
    with TestClient(mvp.app) as c:
        yield c


def test_group_page_invisible_to_public(client):
    client.post("/api/pages", json={"title": "공용", "body": "a", "author": "u", "space": "public"})
    g = client.post("/api/pages", json={"title": "비밀", "body": "b", "author": "u", "space": "acme"}).json()

    pub = {p["slug"] for p in client.get("/api/pages", params={"space": "public"}).json()}
    acme = {p["slug"] for p in client.get("/api/pages", params={"space": "acme"}).json()}
    assert g["slug"] not in pub and slugify("공용") in pub
    assert g["slug"] in acme

    # direct fetch of a group page from public must 404
    assert client.get(f"/api/pages/{g['slug']}", params={"space": "public"}).status_code == 404
    assert client.get(f"/api/pages/{g['slug']}", params={"space": "acme"}).status_code == 200


def test_group_contribution_on_public_node_is_one_way(client):
    p = client.post("/api/pages", json={"title": "공유답", "body": "내용", "author": "u", "space": "public"}).json()
    # a group member adds a group-private note on the PUBLIC node
    client.post(f"/api/pages/{p['slug']}/contribute",
                json={"kind": "comment", "author": "acme-user", "body": "사내 전용 메모", "space": "acme"})
    # public viewer: contribution hidden; acme viewer: visible
    pub = client.get(f"/api/pages/{p['slug']}", params={"space": "public"}).json()
    acme = client.get(f"/api/pages/{p['slug']}", params={"space": "acme"}).json()
    assert len(pub["contributions"]) == 0
    assert len(acme["contributions"]) == 1


def test_public_contribution_does_not_follow_into_group(client):
    p = client.post("/api/pages",
                    json={"title": "공유답", "body": "내용", "author": "u", "space": "public"}).json()
    # 같은 공용 노드에 공용 댓글 + 그룹(acme) 댓글이 각각 달린다
    client.post(f"/api/pages/{p['slug']}/contribute",
                json={"kind": "comment", "author": "pub-user", "body": "공개 메모", "space": "public"})
    client.post(f"/api/pages/{p['slug']}/contribute",
                json={"kind": "comment", "author": "acme-user", "body": "사내 메모", "space": "acme"})
    pub = client.get(f"/api/pages/{p['slug']}", params={"space": "public"}).json()
    acme = client.get(f"/api/pages/{p['slug']}", params={"space": "acme"}).json()
    # 공용 뷰: 공용 기여만
    assert [c["body"] for c in pub["contributions"]] == ["공개 메모"]
    # 그룹 뷰: 자기 층 기여만 — 공용(원래) 스레드는 따라오지 않는다
    assert [c["body"] for c in acme["contributions"]] == ["사내 메모"]


def test_ai_answer_into_group_stays_in_group(client):
    a = client.post("/api/ai-answer", json={"question": "사내 공정?", "author": "u", "space": "acme"}).json()
    assert a["space"] == "acme"
    found_pub = client.get("/api/search", params={"q": "공정", "space": "public"}).json()
    found_acme = client.get("/api/search", params={"q": "공정", "space": "acme"}).json()
    assert all(x["slug"] != a["slug"] for x in found_pub)   # not in commons
    assert any(x["slug"] == a["slug"] for x in found_acme)  # in the group
