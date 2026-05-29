"""The closed point economy.

All value comes from *consent* (동의): the point is not injected from outside —
it is minted to participants and made real when it can buy intellectual labour
inside the system. This module models the mechanics the design relies on:

* **UBI issuance** — points are minted to every participant over time, lowering
  the capital barrier and easing the "poor genius" problem.
* **Staking** — receiving points is not the same as betting them; staking locks
  points onto an ontology node as "conviction bound to a contribution".
* **Value-add-gated dividends** — when fresh stake lands downstream, a slice
  flows *up* the chain to earlier contributors (the 256 time-weight: reward for
  early discovery). But the flow has an *eligibility gate*: nodes with no added
  value (a bare "agree" node) are **bypassed** — the flow routes around them
  straight to the nearest value-adding ancestor. This is the structural line
  between a legitimate rent and a Ponzi pass-through.
* **Escrow bounties** — a "현상금": points held in escrow for a targeted call,
  released on adoption or *returned* if not adopted.
* **Burn sink** — a deflationary counterweight to UBI minting.

The dividend distribution is intentionally simple and auditable; the goal is to
make the *invariants* testable, not to ship a production tokenomics.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field


class InsufficientPoints(Exception):
    """Raised when an account cannot cover a debit / stake / escrow."""


@dataclass
class Ledger:
    """Tracks available balances, locked stakes, escrow, and burned supply."""

    available: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    #: node_id -> {contributor -> staked points} (locked on the node)
    staked: dict[str, dict[str, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    #: escrow_id -> (sponsor, amount)
    escrow: dict[str, tuple[str, float]] = field(default_factory=dict)
    burned: float = 0.0

    # -- supply ----------------------------------------------------------------
    def mint(self, account: str, amount: float) -> None:
        if amount < 0:
            raise ValueError("cannot mint a negative amount")
        self.available[account] += amount

    def burn(self, account: str, amount: float) -> None:
        self._debit(account, amount)
        self.burned += amount

    def _debit(self, account: str, amount: float) -> None:
        if amount < 0:
            raise ValueError("cannot debit a negative amount")
        if self.available[account] + 1e-9 < amount:
            raise InsufficientPoints(
                f"{account} has {self.available[account]:.2f}, needs {amount:.2f}"
            )
        self.available[account] -= amount

    # -- staking ---------------------------------------------------------------
    def stake(self, account: str, node_id: str, amount: float) -> None:
        if amount <= 0:
            raise ValueError("stake amount must be positive")
        self._debit(account, amount)
        self.staked[node_id][account] += amount

    def stake_on(self, node_id: str) -> dict[str, float]:
        return dict(self.staked[node_id])

    def total_staked(self, node_id: str) -> float:
        return sum(self.staked[node_id].values())

    # -- escrow ----------------------------------------------------------------
    def open_escrow(self, escrow_id: str, sponsor: str, amount: float) -> None:
        if escrow_id in self.escrow:
            raise ValueError(f"escrow {escrow_id} already open")
        self._debit(sponsor, amount)
        self.escrow[escrow_id] = (sponsor, amount)

    def release_escrow(self, escrow_id: str, beneficiary: str) -> float:
        """Pay an open escrow out to ``beneficiary`` (adoption)."""
        sponsor, amount = self.escrow.pop(escrow_id)
        self.available[beneficiary] += amount
        return amount

    def return_escrow(self, escrow_id: str) -> float:
        """Return an unspent escrow to its sponsor (no adoption)."""
        sponsor, amount = self.escrow.pop(escrow_id)
        self.available[sponsor] += amount
        return amount

    # -- views -----------------------------------------------------------------
    def balance(self, account: str) -> float:
        return self.available[account]

    def staked_by(self, account: str) -> float:
        return sum(stakes.get(account, 0.0) for stakes in self.staked.values())

    def accounts(self) -> set[str]:
        seen: set[str] = set(self.available)
        for stakes in self.staked.values():
            seen.update(stakes)
        return seen


@dataclass
class Economy:
    """Policy layer on top of a :class:`Ledger`.

    Holds the tunable monetary parameters and the dividend-routing logic that
    needs to know, per node, whether the node *added value* (the eligibility
    gate) and who its chain ancestors are.
    """

    ledger: Ledger = field(default_factory=Ledger)
    #: fraction of fresh downstream stake that flows up the chain as dividend
    dividend_rate: float = 0.20
    #: fraction of fresh stake burned on each contribution (anti-inflation sink)
    burn_rate: float = 0.02

    def issue_ubi(self, accounts: list[str], amount: float) -> None:
        """Mint a flat UBI grant to every participant (one tick)."""
        for account in accounts:
            self.ledger.mint(account, amount)

    def distribute_dividend(
        self,
        fresh_stake: float,
        staker: str,
        ancestors: list[tuple[str, str, bool]],
        hub_of=lambda contributor: 0.0,
    ) -> dict[str, float]:
        """Route a dividend from ``fresh_stake`` up an ancestor chain.

        ``ancestors`` is ordered nearest-first as ``(node_id, contributor,
        value_add)`` triples. Nodes whose ``value_add`` is ``False`` are
        **bypassed** — the flow routes around them. The eligible ancestors share
        the dividend pool weighted by *earliness* and *hub* (256 time-weight:
        the earliest, highest-foresight contributor gets the largest slice).

        Returns the per-contributor payout actually credited.
        """
        pool = fresh_stake * self.dividend_rate
        if pool <= 0:
            return {}

        eligible = [
            (node_id, contributor)
            for node_id, contributor, value_add in ancestors
            if value_add and contributor != staker
        ]
        if not eligible:
            return {}

        # Earliest ancestor is *last* in a nearest-first list, so a deeper
        # (older) ancestor gets a larger time-weight (256 early-discovery reward).
        weights: dict[str, float] = defaultdict(float)
        for depth, (_node_id, contributor) in enumerate(eligible):
            earliness = depth + 1  # deeper (older) ancestor -> larger
            weights[contributor] += earliness * (1.0 + hub_of(contributor))

        total = sum(weights.values())
        payouts: dict[str, float] = {}
        for contributor, weight in weights.items():
            share = pool * weight / total
            self.ledger.available[contributor] += share
            payouts[contributor] = share
        return payouts
