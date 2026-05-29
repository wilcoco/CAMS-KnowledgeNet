"""Nightwish — a living-ontology knowledge evaluation & reward system.

This package is an MVP prototype of the design captured in ``docs/design``.
It is intentionally small and dependency-free so the *mechanics* (not the
production engineering) can be read, tested, and reasoned about.

Four cooperating pieces:

* :mod:`nightwish.scoring`  — the patent-10-0913256 incremental hub/authority
  engine ("link-order weighting", no convergence iteration).
* :mod:`nightwish.tree`     — the living ontology tree: nodes are human-Q +
  AI-answer pairs; actions are follow / fork / contribute.
* :mod:`nightwish.economy`  — the closed point economy: UBI issuance, staking,
  value-add-gated dividends, escrow bounties, and a burn sink.
* :mod:`nightwish.pipeline` — the 3-stage query flow (search → AI → human).

:mod:`nightwish.simulation` wires them together to reproduce the "first wheel"
simulation from the design document (§7).
"""

from nightwish.economy import Economy, InsufficientPoints, Ledger
from nightwish.scoring import ScoreEngine
from nightwish.tree import Action, Node, NodeStatus, OntologyError, OntologyTree

__all__ = [
    "Action",
    "Economy",
    "InsufficientPoints",
    "Ledger",
    "Node",
    "NodeStatus",
    "OntologyError",
    "OntologyTree",
    "ScoreEngine",
]

__version__ = "0.1.0"
