"""Unified knowledge core (tree.py as the single source of truth).

These pin the features merged in from the wiki onto the recursive node model:
recursive threads on *any* slot, open queries answered in place, wikilink stubs,
layers, frozen answers, search, persistence round-trip, and legacy migration.
"""

import pytest

from nightwish.tree import (
    Action,
    OntologyError,
    OntologyTree,
    extract_links,
    slugify,
)


def make_tree():
    t = OntologyTree()
    t.add_root("q1", "사출 불량률을 어떻게 줄이나?", "AI 답변 [[금형 온도]]", "alice", stake=10.0)
    return t


# -- the same Q→A→contribution module applies to any slot, recursively -------
def test_contribution_thread_is_recursive():
    t = make_tree()
    c = t.contribute("c1", "q1", "bob", "보강 의견", stake=1.0)
    # a contribution is itself a slot that can be augmented/forked/followed
    t.contribute("c2", "c1", "carol", "보강에 대한 후속", stake=1.0)
    t.fork("c3", "c1", "dave", "보강을 정정", stake=1.0)
    assert {n.id for n in t.children_of("c1")} == {"c2", "c3"}
    assert c.action is Action.CONTRIBUTE


# -- open query answered in place (one slot keeps its identity) --------------
def test_open_query_answered_in_place_keeps_children():
    t = OntologyTree()
    q = t.open_query("open1", "이 값의 출처는?", "asker")
    assert q.is_query and q.is_answer is False
    # a contribution can attach to the *open* slot before it is answered
    t.contribute("q-c1", "open1", "helper", "관련 자료", stake=1.0)
    node = t.answer_query("open1", "출처는 사내 측정 로그입니다.", "expert", model="claude-opus-4-8")
    assert node.id == "open1"                    # same node, identity preserved
    assert node.action is Action.ROOT
    assert node.frozen and node.model == "claude-opus-4-8"
    assert "q-c1" in node.children               # pre-answer contribution stays
    assert t.open_queries() == []                # no longer open


def test_answer_query_rejects_non_query():
    t = make_tree()
    with pytest.raises(OntologyError):
        t.answer_query("q1", "x", "bob")


# -- wikilinks auto-create stubs (Obsidian-style) ----------------------------
def test_wikilink_creates_stub_and_backlink():
    t = make_tree()  # q1's answer links to [[금형 온도]]
    stub_slug = slugify("금형 온도")
    assert stub_slug in t.nodes
    stub = t.nodes[stub_slug]
    assert stub.is_stub and stub.action is Action.STUB
    assert t.nodes["q1"].links == [stub_slug]
    assert [n.id for n in t.backlinks(stub_slug)] == ["q1"]


def test_extract_links_and_slugify():
    assert extract_links("see [[A]] and [[B]] and [[A]]") == ["A", "B"]
    assert slugify("Hello World!") == "hello-world"
    assert slugify("금형 온도") == "금형-온도"


# -- layers (public commons + one-way group membrane) ------------------------
def test_layers_one_way_visibility():
    t = make_tree()  # q1 public
    t.contribute("g1", "q1", "bob", "그룹 전용 메모", stake=1.0, space="team-a")
    # a public viewer never sees the group contribution
    public_ids = {n.id for n in t.visible_nodes("public")}
    assert "g1" not in public_ids and "q1" in public_ids
    # a team-a viewer sees public ∪ team-a
    team_ids = {n.id for n in t.visible_nodes("team-a")}
    assert "g1" in team_ids and "q1" in team_ids


def test_contribution_inherits_parent_layer_by_default():
    t = make_tree()
    c = t.contribute("c1", "q1", "bob", "메모", stake=1.0)
    assert c.space == "public"


# -- frozen answers --------------------------------------------------------- -
def test_frozen_answer_cannot_be_edited():
    t = make_tree()
    t.mark_answered("q1", "claude-opus-4-8")
    with pytest.raises(OntologyError):
        t.edit("q1", "몰래 수정", "vandal")


def test_unfrozen_node_can_be_edited():
    t = OntologyTree()
    t.open_query("o1", "질문?", "a")
    t.answer_query("o1", "초안 답", "a")  # no model → not frozen
    edited = t.edit("o1", "다듬은 답", "b")
    assert edited.answer == "다듬은 답" and edited.last_editor == "b"


# -- search across the subtree thread ----------------------------------------
def test_search_includes_descendant_thread_and_respects_layer():
    t = make_tree()
    t.contribute("c1", "q1", "bob", "핵심은 보압 시간이다", stake=1.0)
    hits = [n.id for n in t.search("보압")]
    assert "q1" in hits                          # matched via its contribution
    # group text is invisible to the public searcher
    t.contribute("g1", "q1", "bob", "비밀 키워드 zzz", stake=1.0, space="team-a")
    assert [n.id for n in t.search("zzz", space="public")] == []
    assert "q1" in [n.id for n in t.search("zzz", space="team-a")]


# -- persistence round-trip --------------------------------------------------
def test_to_json_from_json_round_trip():
    t = make_tree()
    t.contribute("c1", "q1", "bob", "보강", stake=2.0)
    t.mark_answered("q1", "claude-opus-4-8")
    again = OntologyTree.from_json(t.to_json())
    assert set(again.nodes) == set(t.nodes)
    assert again.nodes["q1"].frozen and again.nodes["q1"].model == "claude-opus-4-8"
    assert again.nodes["c1"].parent_id == "q1"
    assert again.nodes["q1"].children == t.nodes["q1"].children
    assert again.scoring.authority_of("q1") == t.scoring.authority_of("q1")


# -- migration from the legacy flat-wiki snapshot ----------------------------
def test_from_wiki_json_flattens_contributions_into_child_nodes():
    wiki_snapshot = {
        "schema": 1, "clock": 5,
        "scoring": {"mode": "harmonic", "authority": {"q-a": 3.0}, "hub": {},
                    "linkers": {}},
        "pages": [
            {
                "slug": "q-a", "title": "질문 A", "body": "답 본문",
                "author": "alice", "created_at": 1, "updated_at": 4,
                "last_editor": "alice", "links": [], "kind": "page",
                "status": "resolved", "frozen": True, "model": "m1",
                "answered_at": "2026-01-01T00:00:00", "space": "public",
                "contributions": [
                    {"id": "c1", "kind": "comment", "author": "bob",
                     "body": "보강", "model": "", "space": "public",
                     "created_at": "2026-01-02T00:00:00"},
                    {"id": "c2", "kind": "fork", "author": "carol",
                     "body": "다른 답", "model": "", "space": "public",
                     "created_at": "2026-01-03T00:00:00"},
                ],
            }
        ],
    }
    t = OntologyTree.from_wiki_json(wiki_snapshot)
    root = t.nodes["q-a"]
    assert root.action is Action.ROOT and root.frozen and root.model == "m1"
    children = {t.nodes[c].action for c in root.children}
    assert children == {Action.CONTRIBUTE, Action.FORK}
    assert t.scoring.authority_of("q-a") == 3.0
