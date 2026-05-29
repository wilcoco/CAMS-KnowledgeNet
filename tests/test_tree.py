import pytest

from nightwish.tree import Action, NodeStatus, OntologyError, OntologyTree


def make_tree():
    t = OntologyTree()
    t.add_root("q1", "Q?", "AI answer", "alice", stake=10.0)
    return t


def test_root_creation():
    t = make_tree()
    assert t.nodes["q1"].action is Action.ROOT
    assert t.nodes["q1"].is_answer
    assert t.roots()[0].id == "q1"


def test_follow_is_not_value_add():
    t = make_tree()
    t.follow("q1-f", "q1", "bob", stake=5.0)
    assert t.nodes["q1-f"].action is Action.FOLLOW
    assert t.nodes["q1-f"].value_add is False


def test_large_stake_without_contribution_is_rejected():
    """Point size == contribution size: money alone cannot buy a large weight."""
    t = make_tree()
    with pytest.raises(OntologyError):
        t.follow("q1-f", "q1", "whale", stake=1000.0)


def test_large_stake_with_contribution_is_allowed():
    t = make_tree()
    node = t.contribute("c1", "q1", "carol", "extra context", stake=1000.0)
    assert node.value_add is True
    assert t.nodes["c1"].stake == 1000.0


def test_fork_creates_competing_branch_without_killing_parent():
    t = make_tree()
    t.fork("f1", "q1", "dave", "a different answer", stake=20.0)
    assert t.nodes["f1"].action is Action.FORK
    assert t.nodes["f1"].value_add is True
    # parent still alive and active
    assert t.nodes["q1"].status is NodeStatus.ACTIVE
    assert "f1" in t.nodes["q1"].children


def test_pointer_is_not_an_answer_and_starts_dormant():
    t = make_tree()
    t.add_pointer("p1", "q1", "eve", "person X knows this")
    assert t.nodes["p1"].is_answer is False
    assert t.nodes["p1"].status is NodeStatus.DORMANT


def test_sweep_and_revive_dormant_branch():
    t = make_tree()
    t.fork("minority", "q1", "galileo", "the earth moves", stake=5.0)
    slept = t.sweep_dormant()
    assert "minority" in slept
    assert t.nodes["minority"].status is NodeStatus.DORMANT
    # a descendant revives it generations later
    t.revive("minority", "vindication", "kepler", "confirmed", stake=5.0)
    assert t.nodes["minority"].status is NodeStatus.ACTIVE
    assert t.nodes["vindication"].parent_id == "minority"


def test_cannot_revive_active_node():
    t = make_tree()
    t.fork("f1", "q1", "x", "ans", stake=1.0)  # active (just created)
    with pytest.raises(OntologyError):
        t.revive("f1", "n", "y", "ans", stake=1.0)


def test_ancestors_chain_nearest_first():
    t = make_tree()
    t.contribute("c1", "q1", "b", "a1", stake=1.0)
    t.contribute("c2", "c1", "c", "a2", stake=1.0)
    chain = [n.id for n in t.ancestors("c2")]
    assert chain == ["c1", "q1"]


def test_duplicate_node_id_rejected():
    t = make_tree()
    with pytest.raises(OntologyError):
        t.add_root("q1", "again", "x", "z")
