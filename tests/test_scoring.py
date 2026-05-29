from nightwish.scoring import ScoreEngine


def test_earlier_linker_earns_more_hub_than_later():
    """Foresight beats popularity: the first discoverer out-earns late joiners."""
    e = ScoreEngine()
    for evaluator in ["first", "second", "third", "fourth", "fifth"]:
        e.link(evaluator, "node")
    assert e.hub_of("first") > e.hub_of("second") > e.hub_of("third")
    # the last joiner discovered nothing early -> zero hub from this node
    assert e.hub_of("fifth") == 0.0


def test_bandwagon_late_pile_on_earns_almost_nothing():
    e = ScoreEngine()
    # one early discoverer, then a big late bandwagon
    e.link("scout", "n")
    before = e.hub_of("scout")
    for i in range(20):
        e.link(f"crowd-{i}", "n")
    # the scout keeps earning on every follower; the crowd barely earns
    assert e.hub_of("scout") > before
    assert e.hub_of("crowd-19") == 0.0
    assert e.hub_of("crowd-0") < e.hub_of("scout")


def test_authority_accumulates_and_high_hub_confers_more():
    e = ScoreEngine()
    # give 'expert' some hub first by being an early scout elsewhere
    e.link("expert", "other")
    e.link("nobody2", "other")  # validates expert -> expert gains hub
    assert e.hub_of("expert") > 0.0

    e.link("expert", "target")
    e.link("stranger", "target2")
    # the expert's endorsement confers more authority than a stranger's
    assert e.authority_of("target") > e.authority_of("target2")


def test_link_order_and_position():
    e = ScoreEngine()
    e.link("a", "n")
    e.link("b", "n")
    assert e.link_order("n") == ["a", "b"]
    assert e.linker_position("a", "n") == 1
    assert e.linker_position("b", "n") == 2
    assert e.linker_position("c", "n") is None


def test_weight_scales_effect():
    light = ScoreEngine()
    heavy = ScoreEngine()
    light.link("x", "n", weight=1.0)
    light.link("y", "n", weight=1.0)
    heavy.link("x", "n", weight=10.0)
    heavy.link("y", "n", weight=10.0)
    assert heavy.authority_of("n") > light.authority_of("n")
    assert heavy.hub_of("x") > light.hub_of("x")
