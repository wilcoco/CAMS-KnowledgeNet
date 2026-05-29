import pytest

from nightwish.economy import Economy, InsufficientPoints, Ledger


def test_ubi_issuance_is_flat():
    eco = Economy()
    eco.issue_ubi(["a", "b", "c"], 10.0)
    assert all(eco.ledger.balance(x) == 10.0 for x in ["a", "b", "c"])


def test_staking_moves_available_to_locked():
    led = Ledger()
    led.mint("a", 100.0)
    led.stake("a", "node-1", 30.0)
    assert led.balance("a") == 70.0
    assert led.staked_by("a") == 30.0
    assert led.total_staked("node-1") == 30.0


def test_cannot_stake_more_than_available():
    led = Ledger()
    led.mint("a", 10.0)
    with pytest.raises(InsufficientPoints):
        led.stake("a", "n", 11.0)


def test_escrow_returned_when_not_adopted():
    led = Ledger()
    led.mint("sponsor", 500.0)
    led.open_escrow("b1", "sponsor", 500.0)
    assert led.balance("sponsor") == 0.0
    led.return_escrow("b1")
    assert led.balance("sponsor") == 500.0


def test_escrow_released_on_adoption():
    led = Ledger()
    led.mint("sponsor", 500.0)
    led.open_escrow("b1", "sponsor", 500.0)
    led.release_escrow("b1", "winner")
    assert led.balance("winner") == 500.0
    assert led.balance("sponsor") == 0.0


def test_burn_reduces_supply():
    led = Ledger()
    led.mint("a", 100.0)
    led.burn("a", 40.0)
    assert led.balance("a") == 60.0
    assert led.burned == 40.0


def test_dividend_bypasses_empty_agree_node():
    """A node with no added value is routed around (anti-Ponzi gate)."""
    eco = Economy(dividend_rate=0.5)
    # nearest-first ancestor chain: empty agree node, then a value-adding root
    ancestors = [
        ("agree-node", "follower", False),  # bypassed
        ("root", "creator", True),          # eligible
    ]
    payouts = eco.distribute_dividend(100.0, staker="newcomer", ancestors=ancestors)
    assert "follower" not in payouts          # the empty node got nothing
    assert payouts["creator"] == pytest.approx(50.0)  # 100 * 0.5 pool


def test_dividend_time_weight_favours_earlier_contributor():
    eco = Economy(dividend_rate=0.5)
    # nearest-first: later contributor first, earlier (root) last
    ancestors = [
        ("mid", "late", True),
        ("root", "early", True),
    ]
    payouts = eco.distribute_dividend(100.0, staker="x", ancestors=ancestors)
    assert payouts["early"] > payouts["late"]


def test_dividend_excludes_self():
    eco = Economy(dividend_rate=0.5)
    ancestors = [("root", "me", True)]
    payouts = eco.distribute_dividend(100.0, staker="me", ancestors=ancestors)
    assert payouts == {}
