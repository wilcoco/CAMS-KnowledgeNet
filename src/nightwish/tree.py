"""The living ontology tree.

The smallest unit (node) is redefined from the patent's news/comment to a
**human-question + AI-answer pair**:

* the *question* (human prompt) is *foresight / living labour* (산 노동);
* the *answer* (AI-generated) is *material / dead labour* (죽은 노동, the
  crystallisation of humanity's text);
* the *staked points* are the questioner's proof of conviction that the Q&A is
  complete.

Three follow-up actions:

* **FOLLOW (계승)** — agreement that lengthens the same branch. Small stake, no
  contribution required.
* **FORK (분기)** — a *different* answer to the same question: not a downvote but
  a claim that carries the burden of proof. Always allowed; spawns a new branch.
* **CONTRIBUTE (추가 기여)** — context / rebuttal / link / ontology added as a new
  node.

Core rule — **point size == contribution size**: money alone cannot buy a large
weight. A stake above :data:`OntologyTree.large_stake_threshold` requires an
accompanying contribution (``value_add``). This single rule blocks plutocracy,
beauty-contest voting, and noise-forks at once.

Nodes **reference, never copy**: a follow/contribute/fork stores only its *own*
content and points at its parent (``parent_id``). The thread's shared question
(and, for a pure follow, the agreed answer) is reconstructed on demand by walking
the chain — :meth:`OntologyTree.resolved_question` / :meth:`resolved_answer`.

Branches are never deleted: a branch with no follow-ups goes **DORMANT** and can
be **revived** later (the Galileo problem — truth's time-asymmetry is preserved;
the tree refuses to converge to a single frozen answer).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from nightwish.scoring import ScoreEngine


class OntologyError(Exception):
    """Raised when an action violates the tree's rules."""


class Action(str, Enum):
    """How a node came to exist."""

    ROOT = "root"          # the first answer to a brand-new question
    FOLLOW = "follow"      # 계승 — agreement extending the same branch
    FORK = "fork"          # 분기 — a competing answer (burden of proof)
    CONTRIBUTE = "contribute"  # 추가 기여 — context / rebuttal / link / ontology
    POINTER = "pointer"    # a lead, not an answer (e.g. "person X knows this")


class NodeStatus(str, Enum):
    ACTIVE = "active"      # has follow-ups, or recently created
    DORMANT = "dormant"    # no follow-ups yet — sleeping, not deleted


@dataclass
class Node:
    """A single node in the ontology tree."""

    id: str
    question: str
    answer: str
    author: str
    action: Action
    parent_id: str | None = None
    stake: float = 0.0
    value_add: bool = True
    created_at: int = 0
    status: NodeStatus = NodeStatus.ACTIVE
    children: list[str] = field(default_factory=list)

    @property
    def is_answer(self) -> bool:
        """A POINTER is a lead, not an answer; everything else answers."""
        return self.action is not Action.POINTER


@dataclass
class OntologyTree:
    """The whole forest of question threads plus the scoring engine."""

    scoring: ScoreEngine = field(default_factory=ScoreEngine)
    nodes: dict[str, Node] = field(default_factory=dict)
    #: stake at/above this requires an accompanying contribution (value_add)
    large_stake_threshold: float = 25.0
    _clock: int = 0

    # -- internals -------------------------------------------------------------
    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    def _require(self, node_id: str) -> Node:
        if node_id not in self.nodes:
            raise OntologyError(f"unknown node {node_id!r}")
        return self.nodes[node_id]

    def _check_stake_rule(self, stake: float, value_add: bool) -> None:
        # Point size == contribution size: a large stake without a contribution
        # is rejected — money cannot buy a large weight on its own.
        if stake >= self.large_stake_threshold and not value_add:
            raise OntologyError(
                f"a stake of {stake:.0f} (>= {self.large_stake_threshold:.0f}) "
                "requires an accompanying contribution (value_add=True)"
            )

    def _wake_parent(self, parent_id: str | None) -> None:
        if parent_id is not None:
            self.nodes[parent_id].status = NodeStatus.ACTIVE

    # -- creation --------------------------------------------------------------
    def add_root(
        self, node_id: str, question: str, answer: str, author: str, stake: float = 0.0
    ) -> Node:
        """Open a brand-new question thread with its first answer."""
        if node_id in self.nodes:
            raise OntologyError(f"node {node_id!r} already exists")
        node = Node(
            id=node_id,
            question=question,
            answer=answer,
            author=author,
            action=Action.ROOT,
            stake=stake,
            value_add=True,
            created_at=self._tick(),
        )
        self.nodes[node_id] = node
        if stake > 0:
            self.scoring.link(author, node_id, weight=stake)
        return node

    def follow(
        self, node_id: str, parent_id: str, follower: str, stake: float
    ) -> Node:
        """계승 — agree with and extend an existing branch (no contribution).

        Pure follows are *not* value-adding: downstream dividend flow will route
        around them. They are therefore capped to small stakes by the stake
        rule.
        """
        parent = self._require(parent_id)
        self._check_stake_rule(stake, value_add=False)
        # A follow adds no new content — it only references the branch it extends
        # (parent_id) and stakes on it. The question/answer are *not* copied;
        # display resolves them up the chain via :meth:`resolved_answer`.
        node = Node(
            id=node_id,
            question="",
            answer="",
            author=follower,
            action=Action.FOLLOW,
            parent_id=parent_id,
            stake=stake,
            value_add=False,
            created_at=self._tick(),
        )
        self._attach(parent, node)
        # The follower links to the parent content — earlier discoverers of the
        # parent gain hub as this follow piles on.
        if stake > 0:
            self.scoring.link(follower, parent_id, weight=stake)
        return node

    def contribute(
        self,
        node_id: str,
        parent_id: str,
        author: str,
        answer: str,
        stake: float,
        *,
        question: str | None = None,
        value_add: bool = True,
    ) -> Node:
        """추가 기여 — add context / rebuttal / link / ontology as a new node."""
        parent = self._require(parent_id)
        self._check_stake_rule(stake, value_add)
        # The contribution stores only its *own* content. The thread's question
        # is referenced, not copied — :meth:`resolved_question` walks the chain.
        node = Node(
            id=node_id,
            question=question or "",
            answer=answer,
            author=author,
            action=Action.CONTRIBUTE,
            parent_id=parent_id,
            stake=stake,
            value_add=value_add,
            created_at=self._tick(),
        )
        self._attach(parent, node)
        if stake > 0:
            self.scoring.link(author, parent_id, weight=stake)
        return node

    def fork(
        self,
        node_id: str,
        parent_id: str,
        author: str,
        answer: str,
        stake: float,
        *,
        question: str | None = None,
    ) -> Node:
        """분기 — a competing answer to the same question (burden of proof).

        A fork is always value-adding (it is a new claim) and is always allowed,
        but the claimant must grow their own branch with follow-up contributions
        for it to win — there is no judge.
        """
        parent = self._require(parent_id)
        # A fork answers the *same* (shared) question with its own answer; that
        # question is referenced via the chain, not copied onto the fork.
        node = Node(
            id=node_id,
            question=question or "",
            answer=answer,
            author=author,
            action=Action.FORK,
            parent_id=parent_id,
            stake=stake,
            value_add=True,
            created_at=self._tick(),
        )
        self._attach(parent, node)
        # A fork links to the *grandparent* context (the shared question), not as
        # an endorsement of the parent answer it competes with.
        if stake > 0:
            self.scoring.link(author, node_id, weight=stake)
        return node

    def add_pointer(
        self, node_id: str, parent_id: str, author: str, lead: str
    ) -> Node:
        """A lead toward an off-system expert — not an answer; starts dormant."""
        parent = self._require(parent_id)
        node = Node(
            id=node_id,
            question="",
            answer=lead,
            author=author,
            action=Action.POINTER,
            parent_id=parent_id,
            stake=0.0,
            value_add=False,
            created_at=self._tick(),
            status=NodeStatus.DORMANT,
        )
        self._attach(parent, node, wake_parent=False)
        return node

    def _attach(self, parent: Node, node: Node, *, wake_parent: bool = True) -> None:
        if node.id in self.nodes:
            raise OntologyError(f"node {node.id!r} already exists")
        self.nodes[node.id] = node
        parent.children.append(node.id)
        if wake_parent:
            self._wake_parent(parent.id)
        self._mark_dormant_if_leaf(node)

    def _mark_dormant_if_leaf(self, node: Node) -> None:
        if node.action is Action.POINTER:
            node.status = NodeStatus.DORMANT

    # -- dormancy / revival ----------------------------------------------------
    def sweep_dormant(self) -> list[str]:
        """Mark every childless non-root answer node DORMANT; return their ids.

        Dormant != deleted. A minority view that no one followed simply sleeps,
        and can be revived later by a descendant.
        """
        slept: list[str] = []
        for node in self.nodes.values():
            if node.action is Action.ROOT:
                continue
            if not node.children and node.status is NodeStatus.ACTIVE:
                node.status = NodeStatus.DORMANT
                slept.append(node.id)
        return slept

    def revive(
        self, dormant_id: str, node_id: str, author: str, answer: str, stake: float
    ) -> Node:
        """Bring a dormant branch back to life by attaching a new contribution."""
        dormant = self._require(dormant_id)
        if dormant.status is not NodeStatus.DORMANT:
            raise OntologyError(f"node {dormant_id!r} is not dormant")
        dormant.status = NodeStatus.ACTIVE
        return self.contribute(node_id, dormant_id, author, answer, stake)

    # -- views -----------------------------------------------------------------
    def ancestors(self, node_id: str) -> list[Node]:
        """Chain from ``node_id``'s parent up to its root, nearest-first."""
        chain: list[Node] = []
        cur = self._require(node_id).parent_id
        while cur is not None:
            parent = self.nodes[cur]
            chain.append(parent)
            cur = parent.parent_id
        return chain

    def resolved_question(self, node_id: str) -> str:
        """The thread question for ``node_id`` — its own, else inherited by chain.

        Nodes reference rather than copy the question, so a follow/contribute/
        fork without its own question resolves to the nearest ancestor that has
        one (ultimately the root).
        """
        node = self._require(node_id)
        if node.question:
            return node.question
        for ancestor in self.ancestors(node_id):
            if ancestor.question:
                return ancestor.question
        return ""

    def resolved_answer(self, node_id: str) -> str:
        """The answer to show for ``node_id`` — its own, else referenced by chain.

        A pure FOLLOW carries no new answer; it agrees with the branch it
        extends, so its answer resolves to the nearest ancestor that has one.
        Other node kinds always carry their own answer.
        """
        node = self._require(node_id)
        if node.answer:
            return node.answer
        if node.action is Action.FOLLOW:
            for ancestor in self.ancestors(node_id):
                if ancestor.answer:
                    return ancestor.answer
        return node.answer

    def children_of(self, node_id: str) -> list[Node]:
        return [self.nodes[c] for c in self._require(node_id).children]

    def roots(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.action is Action.ROOT]
