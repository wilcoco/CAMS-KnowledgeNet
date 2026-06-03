"""Hybrid search index + tree-level search (membrane, rollup, authority edge)."""

from nightwish.search import HybridIndex, tokenize, offline_embed, set_embedder
from nightwish.tree import OntologyTree


# -- engine ----------------------------------------------------------------- #
def test_tokenize_cjk_bigrams_and_words():
    toks = tokenize("벡터 Clock-42")
    assert "벡터" in toks and "벡" in toks and "터" in toks   # CJK unigram+bigram
    assert "clock" in toks and "42" in toks                   # ascii words, lowered


def test_bm25_ranks_term_overlap_and_is_incremental():
    idx = HybridIndex()
    idx.upsert("a", "벡터 시계로 인과관계를 추적")
    idx.upsert("b", "사출 성형 수율과 냉각 온도")
    idx.upsert("d", "벡터 클럭 비교")
    got = [d for d, _ in idx.query("벡터 시계")]
    assert got[0] == "a" and "b" not in got                  # a has both terms
    # incremental: editing b away from 냉각 drops it from that query
    assert [d for d, _ in idx.query("냉각")] == ["b"]
    idx.upsert("b", "완전히 다른 내용")
    assert idx.query("냉각") == []
    idx.remove("a")
    assert [d for d, _ in idx.query("벡터")] == ["d"]


def test_membrane_predicate_filters_candidates():
    idx = HybridIndex()
    idx.upsert("pub", "공유 개념 벡터")
    idx.upsert("grp", "그룹 전용 벡터")
    got = [d for d, _ in idx.query("벡터", is_allowed=lambda x: x == "pub")]
    assert got == ["pub"]


def test_pluggable_embedder_restores():
    try:
        set_embedder(lambda t: [1.0, 0.0])
        idx = HybridIndex()
        idx.upsert("x", "hello")
        assert idx.docs["x"].vec == [1.0, 0.0]
    finally:
        set_embedder(offline_embed)


# -- tree integration ------------------------------------------------------- #
def _tree():
    t = OntologyTree()
    t.add_root("a", "분산 시스템 벡터 시계", "인과관계 추적", "u")
    t.add_root("b", "사출 성형 수율", "냉각 온도 설정", "u")
    return t


def test_tree_search_partial_match_and_rollup():
    t = _tree()
    # a group-private contribution carries a keyword found nowhere else
    t.contribute("a~1", "a", "g", "사내 전용 쿼럼 합의", stake=0.0, space="team-a")
    assert [n.id for n in t.search("냉각", "public")] == ["b"]      # partial CJK
    # rollup + membrane: the keyword surfaces the ROOT in the group, not in public
    assert t.search("쿼럼", "public") == []
    assert [n.id for n in t.search("쿼럼", "team-a")] == ["a"]


def test_group_endorse_reranks_search_only_inside_group():
    t = OntologyTree()
    t.add_root("a", "온도 측정 센서", "보정", "u")
    t.add_root("b", "온도 제어 온도 보상 온도", "모델", "u")   # lexically stronger for 온도
    assert [n.id for n in t.search("온도", "public")] == ["b", "a"]
    # team-a privately endorses the weaker hit hard → flips order *only* for team-a
    for i in range(6):
        t.group_endorse("team-a", f"g{i}", "a", weight=9.0)
    assert [n.id for n in t.search("온도", "public")] == ["b", "a"]   # commons unmoved
    assert [n.id for n in t.search("온도", "team-a")] == ["a", "b"]   # group re-ranked
    assert [n.id for n in t.search("온도", "team-b")] == ["b", "a"]   # other group unaffected


def test_empty_query_browses_by_authority():
    t = _tree()
    t.scoring.link("e", "b", weight=5.0)          # b earns public authority
    assert [n.id for n in t.search("", "public")][0] == "b"


def test_index_rebuilds_lazily_after_load():
    t = _tree()
    rebuilt = OntologyTree.from_json(t.to_json())  # fresh tree, no index yet
    assert rebuilt._search is None
    assert [n.id for n in rebuilt.search("냉각", "public")] == ["b"]
    assert rebuilt._search is not None             # built on first search
