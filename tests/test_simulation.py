from nightwish.pipeline import Stage
from nightwish.simulation import (
    JSON,
    USER_B,
    USER_C,
    build_first_wheel,
    deep_tacit_query,
)
from nightwish.tree import Action, NodeStatus


def test_first_wheel_final_ledger_matches_design_section_7():
    fw = build_first_wheel()
    led = fw.economy.ledger
    # design §7: "Json 가용 900 / 스테이킹 100. User-B 10. User-C 50."
    assert led.balance(JSON) == 900.0
    assert led.staked_by(JSON) == 100.0
    assert led.staked_by(USER_B) == 10.0
    assert led.staked_by(USER_C) == 50.0


def test_first_wheel_structure():
    fw = build_first_wheel()
    t = fw.tree
    assert t.nodes["#001-a"].action is Action.ROOT
    assert t.nodes["#001-b"].action is Action.CONTRIBUTE
    assert t.nodes["#002"].action is Action.FORK          # competing branch
    assert t.nodes["#003"].action is Action.POINTER       # a lead, not an answer
    assert t.nodes["#003"].status is NodeStatus.DORMANT
    # the fork did not kill the original answer
    assert t.nodes["#001-a"].status is NodeStatus.ACTIVE


def test_value_add_tiers():
    fw = build_first_wheel()
    t = fw.tree
    assert t.nodes["#001-b"].value_add is True   # weak but a contribution
    assert t.nodes["#002"].value_add is True      # strong
    assert t.nodes["#003"].value_add is False     # pointer, not an answer


def test_bottleneck_deep_tacit_query_is_unresolved():
    fw = build_first_wheel()
    res = deep_tacit_query(fw)
    assert res.stage is Stage.UNRESOLVED
    assert res.answer is None
