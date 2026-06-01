"""A minimal point economy layered on the shared wiki.

Closes the design's loop on top of the wiki: points are minted (UBI-style), and
a user *endorses* a page by staking points on it — conviction bound to a
contribution. Each endorsement pays a **dividend** up the page's value chain
(its author + earlier endorsers), weighted by *earliness* and *hub* (the 256
time-weight: the author and the earliest backers get the largest slice — a
royalty that keeps flowing as a page proves out). A small cut is burned
(anti-inflation sink); the remainder stays locked on the page as the endorser's
own stake.

Intentionally simple and auditable — the goal is a testable economic loop, not
production tokenomics. No transferable-currency settlement / Sybil defense yet
(see docs/roadmap.md → P3).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable


class InsufficientPoints(Exception):
    """Raised when an account cannot cover a debit / stake."""


@dataclass
class WikiEconomy:
    #: account -> available balance
    available: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    #: slug -> {account -> locked stake}
    staked: dict[str, dict[str, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    #: slug -> endorsers in the order they endorsed (earliest first)
    endorsers: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    burned: float = 0.0
    dividend_rate: float = 0.20
    burn_rate: float = 0.02

    # -- supply ---------------------------------------------------------------
    def mint(self, account: str, amount: float) -> None:
        if amount <= 0:
            raise ValueError("mint amount must be positive")
        self.available[account] += amount

    def balance(self, account: str) -> float:
        return self.available[account]

    def staked_on(self, slug: str) -> dict[str, float]:
        return dict(self.staked.get(slug, {}))

    # -- the loop -------------------------------------------------------------
    def endorse(
        self,
        account: str,
        slug: str,
        amount: float,
        *,
        page_author: str,
        hub_of: Callable[[str], float] = lambda _u: 0.0,
    ) -> dict[str, float]:
        """Stake ``amount`` on ``slug`` and pay a dividend up its value chain.

        Split: ``burn_rate`` is burned, ``dividend_rate`` is distributed to the
        page author + earlier endorsers (earliness × (1+hub) weighted), and the
        rest is locked as ``account``'s stake on the page. Returns the
        per-beneficiary payout actually credited.
        """
        if amount <= 0:
            raise ValueError("endorse amount must be positive")
        if self.available[account] + 1e-9 < amount:
            raise InsufficientPoints(
                f"{account} has {self.available[account]:.2f}, needs {amount:.2f}"
            )
        self.available[account] -= amount

        burn = amount * self.burn_rate
        self.burned += burn
        pool = amount * self.dividend_rate

        # Value chain, earliest first: author is most upstream, then prior
        # endorsers in order. Exclude the endorser themselves.
        chain = [page_author] + list(self.endorsers[slug])
        beneficiaries = [b for b in chain if b != account]

        payouts: dict[str, float] = {}
        if beneficiaries and pool > 0:
            n = len(beneficiaries)
            weights = {
                b: (n - i) * (1.0 + hub_of(b))  # earlier → larger
                for i, b in enumerate(beneficiaries)
            }
            total = sum(weights.values())
            for b, w in weights.items():
                share = pool * w / total
                self.available[b] += share
                payouts[b] = payouts.get(b, 0.0) + share
        else:
            # no one to pay — fold the dividend back into the locked stake
            pool = 0.0

        remainder = amount - burn - pool
        self.staked[slug][account] += remainder
        self.endorsers[slug].append(account)
        return payouts

    # -- persistence ----------------------------------------------------------
    def to_json(self) -> dict:
        return {
            "available": dict(self.available),
            "staked": {k: dict(v) for k, v in self.staked.items() if v},
            "endorsers": {k: list(v) for k, v in self.endorsers.items() if v},
            "burned": self.burned,
            "dividend_rate": self.dividend_rate,
            "burn_rate": self.burn_rate,
        }

    @classmethod
    def from_json(cls, data: dict) -> "WikiEconomy":
        e = cls(
            burned=data.get("burned", 0.0),
            dividend_rate=data.get("dividend_rate", 0.20),
            burn_rate=data.get("burn_rate", 0.02),
        )
        e.available = defaultdict(float, data.get("available", {}))
        e.staked = defaultdict(
            lambda: defaultdict(float),
            {k: defaultdict(float, v) for k, v in data.get("staked", {}).items()},
        )
        e.endorsers = defaultdict(
            list, {k: list(v) for k, v in data.get("endorsers", {}).items()}
        )
        return e
