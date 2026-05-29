from nightwish.economy import Economy
from nightwish.verification import Direction, Measurement, VerificationRegistry


def test_higher_better_improvement_passes():
    m = Measurement("yield", baseline=80.0, observed=92.0,
                    direction=Direction.HIGHER_BETTER, min_rel_improvement=0.10)
    assert m.relative_improvement > 0.10
    assert m.passes


def test_lower_better_defect_rate_passes():
    m = Measurement("defect_rate", baseline=8.0, observed=2.0,
                    direction=Direction.LOWER_BETTER, min_rel_improvement=0.20)
    assert m.relative_improvement == 0.75  # 8 -> 2 = 75% reduction
    assert m.passes


def test_no_change_or_worse_fails():
    flat = Measurement("yield", 80.0, 80.0, Direction.HIGHER_BETTER)
    worse = Measurement("yield", 80.0, 70.0, Direction.HIGHER_BETTER)
    assert not flat.passes
    assert not worse.passes


def test_below_threshold_fails():
    m = Measurement("yield", 80.0, 81.0, Direction.HIGHER_BETTER,
                    min_rel_improvement=0.10)  # only ~1.25% improvement
    assert not m.passes


def test_registry_is_verified():
    reg = VerificationRegistry()
    assert not reg.is_verified("n1")
    reg.record("n1", Measurement("yield", 80.0, 95.0, Direction.HIGHER_BETTER))
    assert reg.is_verified("n1")


def test_branch_verified_via_ancestor():
    reg = VerificationRegistry()
    reg.record("root", Measurement("yield", 80.0, 95.0, Direction.HIGHER_BETTER))
    # child has no measurement of its own but sits on a verified branch
    assert reg.branch_verified("child", ["root"])
    assert not reg.branch_verified("orphan", ["unverified"])


def test_dividend_gate_blocks_unverified_branch():
    """검증 닻이 없는 가지는 배당 0 — 폰지 구별불가 상태 차단 (critique §2)."""
    eco = Economy(dividend_rate=0.5)
    reg = VerificationRegistry()
    ancestors = [("root", "founder", True)]
    # not verified -> nothing flows
    payouts = eco.distribute_dividend(
        100.0, staker="x", ancestors=ancestors, is_verified=reg.is_verified
    )
    assert payouts == {}
    # now verify the node -> dividend activates
    reg.record("root", Measurement("yield", 80.0, 95.0, Direction.HIGHER_BETTER))
    payouts = eco.distribute_dividend(
        100.0, staker="x", ancestors=ancestors, is_verified=reg.is_verified
    )
    assert payouts["founder"] == 50.0
