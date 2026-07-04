"""Incremental hub / authority scoring (patent 10-0913256).

The classic HITS (Kleinberg) and PageRank algorithms need accumulated data and
repeated, converging matrix iteration — so they cannot score brand-new content
in real time. The 2005 patent's contribution is to **replace the converging
iteration with link *order*** ("링크 순서 가중"):

* Whoever links to a sub-node *earlier* — and keeps being validated as later
  links pile onto the same sub-node — earns a rising **hub** index. Hub is the
  evaluator's *foresight* (안목): the ability to recognise something good early.
* A sub-node recommended by good hubs earns a rising **authority** index.
  Authority is the *content's value* (권위).

Hub and authority reinforce each other, and every update is **incremental** —
no global re-computation, so a freshly created node is scored the instant the
first link arrives. Crucially, the currency of evaluation is *foresight*, not
*popularity*, which structurally resists bandwagon ("밴드왜건") abuse: piling on
late earns almost nothing.

This module is deliberately storage-agnostic: it keeps its own small maps keyed
by opaque string ids so it can be unit-tested in isolation from the tree.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

#: Hub-update rules. All three are order-sensitive and fully incremental
#: (no convergence iteration), per patent 10-0913256.
#:
#: * ``"count"``    — **patent claim 2 (청구항 2).** Every earlier linker's hub
#:   rises by ``weight`` each time a later linker piles onto the same node
#:   ("이후 다른 상위 노드가 추가로 링크될 때마다 1씩 증가"). With unit weights the
#:   first discoverer of a node that later gets N linkers ends at hub N-1.
#: * ``"sum"``      — **patent claim 3 (청구항 3).** Each earlier linker inherits
#:   the *current hub* of every later linker ("먼저 링크한 상위 노드의 허브 지수는
#:   추가로 링크되는 상위 노드들의 허브 지수를 계속하여 더한다").
#: * ``"harmonic"`` — a design variant (the original MVP behaviour): the j-th
#:   earlier linker receives ``weight / j``, so foresight decays smoothly with
#:   how late you were. Not in the patent, but bandwagon-resistant and the
#:   gentlest to bootstrap; kept as the default so existing behaviour is stable.
HUB_MODES = ("harmonic", "count", "sum")


@dataclass
class ScoreEngine:
    """Order-sensitive, incremental hub/authority scorer.

    A "link" is the event *evaluator E recognised content node N* (in this
    system: someone follows, forks from, or contributes to N). Links are fed in
    the order they happen; the engine never iterates to convergence.

    ``mode`` selects the hub-update rule — see :data:`HUB_MODES`. The faithful
    patent rules (``"count"`` / ``"sum"``) and the MVP variant (``"harmonic"``)
    all agree on the *direction* (earlier beats later); they differ only in how
    steeply foresight is rewarded.
    """

    #: node_id -> authority (value of the content)
    authority: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    #: contributor_id -> hub (foresight of the evaluator)
    hub: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    #: node_id -> evaluators in the order they linked (the "link order")
    _linkers: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    #: hub-update rule; one of :data:`HUB_MODES`
    mode: str = "harmonic"

    def __post_init__(self) -> None:
        if self.mode not in HUB_MODES:
            raise ValueError(f"mode must be one of {HUB_MODES}, got {self.mode!r}")

    def link(self, evaluator: str, node_id: str, *, weight: float = 1.0,
             kin: frozenset[str] | set[str] | None = None) -> None:
        """Record that ``evaluator`` linked to ``node_id`` (the next in order).

        Two incremental effects, both order-sensitive:

        1. **Reward foresight.** Every *earlier* linker is validated by this new
           follower, so the first discoverer keeps earning on every later
           follower while late joiners earn almost nothing — turning
           "popularity" into "who saw it first". *How much* each earlier linker
           gains is set by :data:`mode <HUB_MODES>`.
        2. **Confer authority.** ``node_id`` gains authority equal to a base
           amount plus the *current hub* of the linker — a high-hub evaluator's
           endorsement is worth more than a stranger's (수학식 10).

        ``kin`` — 무리 내부 상속 감액(노트 13 §7 3단계, 노트 21 §3): 새 링커와
        *같은 무리*로 판정된(두루 군집) 이전 링커에게 가는 안목 상속은
        ``1/|무리|``로 줄인다. 패거리가 서로 밟아 서로의 안목을 키우는 폐회로만
        누르고, 무리 밖 독립 검증의 상속은 그대로다. 판정은 호출자(트리)가 준다
        — 엔진은 저장-무관 원칙 유지.
        """
        if weight <= 0:
            raise ValueError("link weight must be positive")

        damp = (1.0 / max(1, len(kin))) if kin else 1.0

        def _gain(earlier: str, base: float) -> None:
            self.hub[earlier] += base * (damp if kin and earlier in kin else 1.0)

        earlier_linkers = self._linkers[node_id]
        if self.mode == "harmonic":
            for j, earlier in enumerate(earlier_linkers, start=1):
                _gain(earlier, weight / j)
        elif self.mode == "count":
            # 청구항 2: every earlier linker +weight per later link.
            for earlier in earlier_linkers:
                _gain(earlier, weight)
        else:  # "sum" — 청구항 3
            # Every earlier linker inherits this new linker's current hub.
            incoming_hub = self.hub[evaluator]
            for earlier in earlier_linkers:
                _gain(earlier, weight * incoming_hub)

        self._linkers[node_id].append(evaluator)
        self.authority[node_id] += weight * (1.0 + self.hub[evaluator])

    def link_order(self, node_id: str) -> list[str]:
        """Return the evaluators of ``node_id`` in the order they linked."""
        return list(self._linkers[node_id])

    def linker_position(self, evaluator: str, node_id: str) -> int | None:
        """1-based position of ``evaluator`` among ``node_id``'s linkers, or None."""
        order = self._linkers[node_id]
        return order.index(evaluator) + 1 if evaluator in order else None

    def authority_of(self, node_id: str) -> float:
        return self.authority[node_id]

    def hub_of(self, evaluator: str) -> float:
        return self.hub[evaluator]
