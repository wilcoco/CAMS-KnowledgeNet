"""The patent-faithful hub modes reproduce the worked examples in 10-0913256."""

import pytest

from nightwish.scoring import ScoreEngine


def test_count_mode_matches_patent_claim2():
    """청구항 2 / 명세서 <53>: link order 1→3→4 onto the same node.

    Every earlier linker gains +1 per later link, so hub(1)=2, hub(3)=1, hub(4)=0.
    """
    e = ScoreEngine(mode="count")
    for who in ["n1", "n3", "n4"]:
        e.link(who, "n2")
    assert e.hub_of("n1") == 2.0
    assert e.hub_of("n3") == 1.0
    assert e.hub_of("n4") == 0.0


def test_sum_mode_matches_patent_claim3():
    """청구항 3 / 명세서 <55>: with pre-acquired hubs 3.2 / 4.1 / 1.5.

    Earlier linkers inherit later linkers' current hub:
    hub(1)=3.2+4.1+1.5=8.8, hub(3)=4.1+1.5=5.6, hub(4)=1.5.
    """
    e = ScoreEngine(mode="sum")
    e.hub["n1"], e.hub["n3"], e.hub["n4"] = 3.2, 4.1, 1.5
    for who in ["n1", "n3", "n4"]:
        e.link(who, "n2")
    assert e.hub_of("n1") == pytest.approx(8.8)
    assert e.hub_of("n3") == pytest.approx(5.6)
    assert e.hub_of("n4") == pytest.approx(1.5)


def test_all_modes_agree_on_direction_earlier_beats_later():
    for mode in ("harmonic", "count", "sum"):
        e = ScoreEngine(mode=mode)
        # seed nonzero hubs so 'sum' mode is not trivially all-zero
        for u in ["a", "b", "c", "d"]:
            e.hub[u] = 1.0
        for u in ["a", "b", "c", "d"]:
            e.link(u, "node")
        assert e.hub_of("a") > e.hub_of("b") > e.hub_of("c") > e.hub_of("d"), mode


def test_invalid_mode_rejected():
    with pytest.raises(ValueError):
        ScoreEngine(mode="bogus")
