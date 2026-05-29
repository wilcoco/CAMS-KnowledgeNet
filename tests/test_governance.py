import pytest

from nightwish.governance import Governance, GovernanceError, Phase


def make_gov(threshold=3):
    return Governance(admin="Json", decentralize_at=threshold)


def test_starts_in_bootstrap_admin_can_set():
    g = make_gov()
    assert g.phase is Phase.BOOTSTRAP
    g.set_rule("dividend_rate", 0.2, by="Json")
    assert g.get_rule("dividend_rate") == 0.2


def test_non_admin_cannot_set_in_bootstrap():
    g = make_gov()
    with pytest.raises(GovernanceError):
        g.set_rule("dividend_rate", 0.2, by="someone")


def test_auto_decentralizes_at_threshold():
    g = make_gov(threshold=3)
    g.register("a")
    g.register("b")
    assert g.phase is Phase.BOOTSTRAP
    g.register("c")  # third participant trips the pre-commitment
    assert g.phase is Phase.DECENTRALIZED
    assert any("AUTO-DECENTRALIZE" in line for line in g.log)


def test_admin_cannot_set_unilaterally_after_decentralize():
    g = make_gov(threshold=2)
    g.register("a")
    g.register("b")
    with pytest.raises(GovernanceError):
        g.set_rule("dividend_rate", 0.9, by="Json")


def test_council_consensus_required_after_decentralize():
    g = make_gov(threshold=3)
    for p in ["a", "b", "c", "d"]:
        g.register(p)
    g.seat_council({"a", "b", "c", "d"})
    # one approval is not a quorum
    with pytest.raises(GovernanceError):
        g.change_rule_by_consensus("dividend_rate", 0.3, approvals={"a"})
    # majority approves
    g.change_rule_by_consensus("dividend_rate", 0.3, approvals={"a", "b", "c"})
    assert g.get_rule("dividend_rate") == 0.3


def test_council_members_must_be_registered():
    g = make_gov(threshold=2)
    g.register("a")
    g.register("b")
    with pytest.raises(GovernanceError):
        g.seat_council({"a", "ghost"})
