"""The wiki point economy: mint, endorse, value-chain dividend, burn."""

import pytest

from nightwish.wiki_economy import InsufficientPoints, WikiEconomy


def test_mint_and_balance():
    e = WikiEconomy()
    e.mint("a", 100)
    assert e.balance("a") == 100
    with pytest.raises(ValueError):
        e.mint("a", -5)


def test_endorse_pays_author_burns_and_locks():
    e = WikiEconomy(dividend_rate=0.20, burn_rate=0.02)
    e.mint("backer", 100)
    payouts = e.endorse("backer", "p", 100, page_author="author")
    # 20 dividend pool → all to the sole beneficiary (author)
    assert payouts["author"] == pytest.approx(20.0)
    assert e.balance("author") == pytest.approx(20.0)
    assert e.balance("backer") == 0.0
    assert e.burned == pytest.approx(2.0)
    # remainder locked on the page: 100 - 2 burn - 20 dividend = 78
    assert e.staked_on("p")["backer"] == pytest.approx(78.0)


def test_dividend_favors_author_and_earlier_endorsers():
    e = WikiEconomy()
    for u in ["author", "first", "second", "third"]:
        e.mint(u, 100)
    e.endorse("first", "p", 100, page_author="author")
    e.endorse("second", "p", 100, page_author="author")
    # third endorses; beneficiaries = [author, first, second], earliest weighted most
    payouts = e.endorse("third", "p", 100, page_author="author")
    assert payouts["author"] > payouts["first"] > payouts["second"]


def test_endorse_without_balance_raises():
    e = WikiEconomy()
    with pytest.raises(InsufficientPoints):
        e.endorse("broke", "p", 10, page_author="author")


def test_no_beneficiary_folds_dividend_into_stake():
    # author endorses their own page first; nobody else to pay → all (minus burn) locked
    e = WikiEconomy(burn_rate=0.02)
    e.mint("author", 100)
    payouts = e.endorse("author", "p", 100, page_author="author")
    assert payouts == {}
    assert e.staked_on("p")["author"] == pytest.approx(98.0)


def test_persistence_round_trip():
    e = WikiEconomy()
    e.mint("a", 100)
    e.endorse("a", "p", 40, page_author="b")
    restored = WikiEconomy.from_json(e.to_json())
    assert restored.balance("a") == e.balance("a")
    assert restored.staked_on("p") == e.staked_on("p")
    assert restored.endorsers["p"] == e.endorsers["p"]
    assert restored.burned == e.burned
