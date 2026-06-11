"""두루(diversity) 집계 — 권위는 '많이'가 아니라 '두루'로 선다 (노트 17 §5).

S4 시뮬의 빈칸(시빌≡독립)을 읽기시점 렌즈로 메운다: 같은 무리는 √n 표.
"""
from nightwish.tree import OntologyTree


def _ring_vs_indep():
    t = OntologyTree()
    t.add_root("G", "패거리가 미는 답", "본문", "author1")
    t.add_root("R", "독립이 미는 답", "본문", "author2")
    for aux in ("A1", "A2"):
        t.add_root(aux, aux, "aux", "author3")
    for u in ("u1", "u2", "u3"):
        t.add_root(f"U-{u}", f"개별 {u}", "x", "author4")

    # 패거리 r1~r3: 희소 노드 A1·A2를 *같이* 밟고(겹침 2개) 표적 G로
    for aux in ("A1", "A2"):
        for r in ("r1", "r2", "r3"):
            t.scoring.link(r, aux, weight=1.0)
    for r in ("r1", "r2", "r3"):
        t.scoring.link(r, "G", weight=1.0)
    # 독립 i1~i3: 각자 *자기* 노드만 밟고 표적 R로 (겹침은 R 하나뿐 → 무죄)
    for i, u in enumerate(("i1", "i2", "i3"), 1):
        t.scoring.link(u, f"U-u{i}", weight=1.0)
        t.scoring.link(u, "R", weight=1.0)
    t.bump()
    return t


def test_ring_is_folded_to_sqrt_votes_but_independents_are_not():
    t = _ring_vs_indep()
    raw_g, eff_g = t.effective_walkers("G")
    raw_r, eff_r = t.effective_walkers("R")
    assert raw_g == raw_r == 3
    assert abs(eff_g - 3 ** 0.5) < 1e-9        # 한 무리 3명 = √3 표
    assert eff_r == 3.0                         # 독립 3명 = 3표
    assert t.diversity_factor("G") < 1.0 - 1e-9
    assert t.diversity_factor("R") == 1.0


def test_authority_view_applies_diversity_silently():
    t = _ring_vs_indep()
    # 읽기시점 렌즈: 표시 권위 = 원시 권위 × factor (패거리만 눌림)
    assert t.authority_in("G") < t.scoring.authority_of("G") - 1e-9
    assert t.authority_in("R") == t.scoring.authority_of("R")


def test_single_shared_node_is_innocent_co_interest():
    """겹침이 노드 1개뿐(동일 관심사)이면 무리로 묶지 않는다 — 합의 ≠ 결탁."""
    t = OntologyTree()
    t.add_root("X", "공동 관심", "본문", "a")
    t.scoring.link("p", "X", weight=1.0)
    t.scoring.link("q", "X", weight=1.0)
    t.bump()
    raw, eff = t.effective_walkers("X")
    assert raw == 2 and eff == 2.0              # 2표 그대로
    assert t.diversity_factor("X") == 1.0
