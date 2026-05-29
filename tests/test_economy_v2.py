"""2차 이터레이션: 화폐공학 균열 닫기 (critique §1.2, §1.3)."""

import pytest

from nightwish.economy import Economy, InsufficientPoints


def test_dividend_time_decay_penalises_stale_stake():
    """갱신되지 않은 오래된 지분은 배당 가중이 0으로 수렴 (자본증식 차단)."""
    eco = Economy(dividend_rate=0.5)
    # same depth/earliness would normally tie; age breaks it
    ancestors = [
        ("fresh", "newcomer", True),
        ("stale", "founder", True),
    ]
    ages = {"fresh": 0, "stale": 100}
    payouts = eco.distribute_dividend(
        100.0, staker="x", ancestors=ancestors, ages=ages, half_life=10.0
    )
    # founder is older (more earliness) but heavily decayed -> earns less
    assert payouts["founder"] < payouts["newcomer"]


def test_no_decay_when_half_life_absent():
    eco = Economy(dividend_rate=0.5)
    ancestors = [("a", "late", True), ("b", "early", True)]
    payouts = eco.distribute_dividend(100.0, staker="x", ancestors=ancestors)
    assert payouts["early"] > payouts["late"]  # pure time-weight, no decay


def test_reclaim_dormant_moves_points_to_liquidity_pool_not_burned():
    eco = Economy()
    eco.ledger.mint("alice", 50.0)
    eco.ledger.stake("alice", "minority", 50.0)
    reclaimed = eco.reclaim_dormant("minority")
    assert reclaimed == 50.0
    assert eco.ledger.liquidity_pool == 50.0
    assert eco.ledger.burned == 0.0          # NOT burned
    assert eco.ledger.total_staked("minority") == 0.0


def test_revival_restores_stakers_and_pays_finder_bonus():
    eco = Economy()
    eco.ledger.mint("alice", 50.0)
    eco.ledger.stake("alice", "minority", 50.0)
    eco.reclaim_dormant("minority")          # pool = 50
    # add headroom so the 10% finder bonus comes from the pool, not minted
    eco.ledger.liquidity_pool += 10.0
    result = eco.restore_on_revival("minority", finder="kepler", finder_bonus_rate=0.10)
    assert result["restored"] == 50.0
    assert result["finder_bonus"] == pytest.approx(5.0)
    assert eco.ledger.total_staked("minority") == 50.0   # alice restored
    assert eco.ledger.balance("kepler") == pytest.approx(5.0)


def test_restore_without_reclaim_raises():
    eco = Economy()
    with pytest.raises(ValueError):
        eco.restore_on_revival("never", finder="x")


def test_restore_mints_bonus_when_pool_short():
    eco = Economy()
    eco.ledger.mint("alice", 30.0)
    eco.ledger.stake("alice", "n", 30.0)
    eco.reclaim_dormant("n")  # pool = 30, exactly the restore amount
    result = eco.restore_on_revival("n", finder="f", finder_bonus_rate=0.10)
    # restore consumes the whole pool; bonus must be minted
    assert eco.ledger.total_staked("n") == 30.0
    assert eco.ledger.balance("f") == pytest.approx(3.0)
