"""Hybrid search index + tree-level search (membrane, rollup, authority edge)."""

from nightwish.search import HybridIndex, tokenize, offline_embed, set_embedder
from nightwish.tree import OntologyTree


# -- engine ----------------------------------------------------------------- #
def test_tokenize_cjk_bigrams_and_words():
    toks = tokenize("벡터 Clock-42")
    assert "벡터" in toks                                      # CJK bigram
    assert "벡" not in toks and "터" not in toks               # no noisy unigrams
    assert "clock" in toks and "42" in toks                   # ascii words, lowered
    assert tokenize("각")[0] == "각"                           # 1-char run keeps unigram


def test_no_single_char_cross_match():
    # "조브플럭스" and "캘리브레이션" share only the char '브' — must NOT match
    idx = HybridIndex()
    idx.upsert("a", "조브플럭스 시스템")
    idx.upsert("b", "캘리브레이션 절차")
    assert [d for d, _ in idx.query("조브플럭스")] == ["a"]


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
    # 노트 25: 그룹 검색은 *들여온 것만* — a는 발자국으로 들어왔고 b는 아직 밖
    assert [n.id for n in t.search("온도", "team-a")] == ["a"]
    assert [n.id for n in t.search("온도", "team-b")] == []           # 새 그룹은 빈 공간


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


# ── 다국어 (2026-07): 한/영 불변 + 비한글 문자권 소생 ────────────────────────

def test_slug_invariance_and_multilingual_revival():
    """기존 한/영 슬러그는 바이트 단위 불변 — DB 주소·링크·재사용 무손상 보증.
    종전에 'node'로 붕괴하던 문자권(한자·가나·키릴)은 고유 슬러그로 살아난다."""
    from nightwish.tree import slugify
    frozen = {                       # 종전 규칙의 출력 스냅샷 (변하면 DB가 깨진다)
        "용접 방법": "용접-방법",
        "Welding method": "welding-method",
        "PP(폴리프로필렌)": "pp-폴리프로필렌",
        "CRDT가 뭐야": "crdt가-뭐야",
        "a_b test": "a-b-test",
    }
    for title, want in frozen.items():
        assert slugify(title) == want
    revived = [slugify(t) for t in ("溶接の方法", "焊接方法", "Способ сварки")]
    assert "node" not in revived and len(set(revived)) == 3


def test_multilingual_content_is_searchable_in_its_language():
    """일본어/중국어/러시아어 콘텐츠가 자기 언어 질의로 검색된다 (종전 토큰 0=불가)."""
    t = OntologyTree()
    t.add_root("ja", "溶接の方法", "アーク溶接の基本手順", "u")
    t.add_root("zh", "焊接方法", "电弧焊的基本步骤", "u")
    t.add_root("ru", "Способ сварки", "Основы дуговой сварки", "u")
    assert [n.id for n in t.search("溶接", "public")][:1] == ["ja"]
    assert [n.id for n in t.search("焊接", "public")][:1] == ["zh"]
    assert [n.id for n in t.search("сварки", "public")][:1] == ["ru"]
    # 한글 검색 동작 불변
    t.add_root("ko", "용접 방법", "아크 용접 기본", "u")
    assert "ko" in [n.id for n in t.search("용접", "public")]
