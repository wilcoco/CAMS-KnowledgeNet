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

Unified knowledge core
----------------------
This module is the **single source of truth** for the whole system: every unit
of knowledge — a wiki page, an open public query, a link-stub, an AI answer, and
every follow/fork/contribution on a thread — is *one* :class:`Node`. The same
recursive Q→A→contribution module therefore applies to **every** slot that needs
filling, not just a top-level question. Nodes additionally carry wiki concerns:

* ``slug`` / ``links`` — wikilinks (``[[Title]]``) that auto-create **stub** nodes,
* ``space`` — the layer the node lives in (``public`` commons or a group id;
  one-way membrane: group nodes may reference public, never the reverse),
* ``frozen`` / ``model`` / ``answered_at`` — provenance stamp on an AI answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from nightwish.scoring import ScoreEngine
from nightwish.search import HybridIndex

#: author marker for an auto-created, not-yet-written stub node
STUB_AUTHOR = "(stub)"

#: How strongly endorsement (authority) lifts a textually-relevant search hit.
#: Gentle on purpose — relevance still gates inclusion; this only re-orders.
ADOPTION_BOOST = 0.05

_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9가-힣]+")


def slugify(title: str) -> str:
    """A stable, URL-safe id derived from a human title (CJK preserved)."""
    s = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return s or "node"


def extract_links(text: str) -> list[str]:
    """Wikilink targets (``[[Title]]``) in order, de-duplicated."""
    seen: dict[str, None] = {}
    for m in _LINK_RE.finditer(text or ""):
        seen.setdefault(m.group(1).strip(), None)
    return list(seen)


class OntologyError(Exception):
    """Raised when an action violates the tree's rules."""


class Action(str, Enum):
    """How a node came to exist."""

    ROOT = "root"          # the first answer to a brand-new question
    FOLLOW = "follow"      # 계승 — agreement extending the same branch
    FORK = "fork"          # 분기 — a competing answer (burden of proof)
    CONTRIBUTE = "contribute"  # 추가 기여 — context / rebuttal / link / ontology
    POINTER = "pointer"    # a lead, not an answer (e.g. "person X knows this")
    QUERY = "query"        # 질의 — an open question awaiting an answer (no answer yet)
    STUB = "stub"          # a placeholder created by an incoming wikilink


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
    # -- wiki concerns (all optional; default-safe for tree/sim/service flows) --
    #: stable url id; falls back to ``id`` when empty
    slug: str = ""
    #: wikilink target slugs found in this node's answer/body
    links: list[str] = field(default_factory=list)
    #: an AI answer frozen with provenance is immutable — edit via contributions
    frozen: bool = False
    #: model that produced a frozen answer (e.g. "claude-opus-4-8")
    model: str = ""
    #: ISO timestamp the answer was frozen
    answered_at: str = ""
    #: layer this node lives in ("public" commons or a group id)
    space: str = "public"
    #: last mutation tick / last editor (wiki provenance)
    updated_at: int = 0
    last_editor: str = ""
    #: contextual unfold (노트 07): the parent text span this node elaborates.
    #: ``""`` = a normal commons/thread node; non-empty = an in-context unfold,
    #: rendered inline at its quoted span rather than in the flat thread.
    anchor: str = ""

    @property
    def is_unfold(self) -> bool:
        """A contextual unfold — elaborates a span of its parent, shown inline."""
        return bool(self.anchor)

    @property
    def is_answer(self) -> bool:
        """A POINTER/QUERY/STUB carries no answer; everything else does."""
        return self.action not in (Action.POINTER, Action.QUERY, Action.STUB)

    @property
    def is_stub(self) -> bool:
        """A placeholder created by an incoming link but not yet written."""
        return self.action is Action.STUB or (
            self.author == STUB_AUTHOR and not self.answer.strip()
        )

    @property
    def is_query(self) -> bool:
        return self.action is Action.QUERY


@dataclass
class OntologyTree:
    """The whole forest of question threads plus the scoring engine."""

    #: the **public commons** scorer — the one global authority everyone shares.
    scoring: ScoreEngine = field(default_factory=ScoreEngine)
    nodes: dict[str, Node] = field(default_factory=dict)
    #: per-group **private** scorers (space → engine). A group's endorsements feed
    #: only its own engine (free-issue, non-convertible "group coin"), so its
    #: authority overlay is visible *only inside the group* and can never move the
    #: public commons. See ``docs/design/05-private-public-endorse.md``.
    group_scoring: dict[str, ScoreEngine] = field(default_factory=dict)
    #: stake at/above this requires an accompanying contribution (value_add)
    large_stake_threshold: float = 25.0
    _clock: int = 0
    #: hybrid search index — built lazily on first search, kept incrementally
    #: fresh via ``_finalize``. Not serialised (rebuilt from nodes on load).
    _search: HybridIndex | None = field(default=None, compare=False, repr=False)
    #: monotonic write revision — bumped on any change that affects rankings, so
    #: read-side caches (e.g. the scoreboard) can memoise until the next write.
    _rev: int = field(default=0, compare=False, repr=False)
    #: space -> (rev, ranked[(node, authority)]) memo of the authority scoreboard
    _board_cache: dict = field(default_factory=dict, compare=False, repr=False)

    # -- internals -------------------------------------------------------------
    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    def bump(self) -> None:
        """Mark rankings dirty so read-side caches recompute on next read."""
        self._rev += 1

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

    def _finalize(self, node: Node) -> None:
        """Post-creation: assign a slug, stamp provenance, wire wikilinks → stubs.

        Any ``[[Title]]`` in the node's answer auto-creates a **stub** node (in the
        same layer) so the graph stays connected and the target can already accrue
        authority — exactly like the wiki, but on the unified node model.
        """
        if not node.slug:
            node.slug = slugify(node.question or node.id)
        node.updated_at = self._clock
        if not node.last_editor:
            node.last_editor = node.author
        previous = set(node.links)
        link_slugs: list[str] = []
        for title in extract_links(node.answer):
            ts = slugify(title)
            if ts == node.slug or ts in link_slugs:
                continue
            link_slugs.append(ts)
            if ts not in self.nodes:
                # A wikilink target is a *concept* (an empty slug awaiting an AI
                # summary), so its stub is born into the public commons — never
                # the mentioning node's group space. Otherwise a group that
                # merely *referenced* a universal concept would squat its global
                # address. (docs/design/05-private-public-endorse.md)
                self.nodes[ts] = Node(
                    id=ts, question=title, answer="", author=STUB_AUTHOR,
                    action=Action.STUB, created_at=self._tick(),
                    slug=ts, space="public", updated_at=self._clock,
                    last_editor=STUB_AUTHOR,
                )
            # Only *newly added* links score, so re-editing a body does not
            # double-count — order (who linked first) stays meaningful.
            if ts not in previous and node.author != STUB_AUTHOR:
                self.scoring.link(node.author, ts, weight=1.0)
        node.links = link_slugs
        # Keep the search index fresh at write time (cheap, incremental). Stubs
        # are empty concept placeholders — excluded, like in search itself.
        if self._search is not None and not node.is_stub:
            self._search.upsert(node.id, self._doc_text(node))
        self.bump()

    # -- search index ----------------------------------------------------------
    @staticmethod
    def _doc_text(node: Node) -> str:
        return f"{node.question}\n{node.answer}"

    def _ensure_index(self) -> HybridIndex:
        if self._search is None:
            idx = HybridIndex()
            for n in self.nodes.values():
                if not n.is_stub:
                    idx.upsert(n.id, self._doc_text(n))
            self._search = idx
        return self._search

    def _top_ancestor(self, node_id: str) -> str:
        """The shareable unit a hit rolls up to (the thread's root)."""
        seen: set[str] = set()
        cur = self.nodes.get(node_id)
        while cur is not None and cur.parent_id and cur.parent_id not in seen:
            seen.add(cur.id)
            cur = self.nodes.get(cur.parent_id)
        return cur.id if cur is not None else node_id

    # -- creation --------------------------------------------------------------
    def add_root(
        self, node_id: str, question: str, answer: str, author: str,
        stake: float = 0.0,
    ) -> Node:
        """Open a brand-new question thread with its first answer.

        A ROOT is a **concept**: it owns the global ``slug`` address and is the
        shared commons coordinate everyone resolves ``[[Title]]`` to. Concept
        identity is therefore always **public** — privacy lives in the *overlays*
        (group contributions/endorsements), never in the concept itself. See
        ``docs/design/05-private-public-endorse.md``.
        """
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
            space="public",
        )
        self.nodes[node_id] = node
        self._finalize(node)
        if stake > 0:
            self.scoring.link(author, node_id, weight=stake)
        return node

    def follow(
        self, node_id: str, parent_id: str, follower: str, stake: float,
        *, space: str | None = None,
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
            space=space if space is not None else parent.space,
        )
        self._attach(parent, node)
        self._finalize(node)
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
        space: str | None = None,
        anchor: str = "",
    ) -> Node:
        """추가 기여 — add context / rebuttal / link / ontology as a new node.

        ``anchor`` (노트 07): a quoted span of the parent answer this node
        elaborates. Non-empty makes it a **contextual unfold** — shown inline at
        the span instead of in the flat thread.
        """
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
            space=space if space is not None else parent.space,
            anchor=anchor,
        )
        self._attach(parent, node)
        self._finalize(node)
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
        space: str | None = None,
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
            space=space if space is not None else parent.space,
        )
        self._attach(parent, node)
        self._finalize(node)
        # A fork links to the *grandparent* context (the shared question), not as
        # an endorsement of the parent answer it competes with.
        if stake > 0:
            self.scoring.link(author, node_id, weight=stake)
        return node

    def add_pointer(
        self, node_id: str, parent_id: str, author: str, lead: str,
        *, space: str | None = None,
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
            space=space if space is not None else parent.space,
        )
        self._attach(parent, node, wake_parent=False)
        self._finalize(node)
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

    # -- open queries (a slot whose answer is not filled yet) -----------------
    def open_query(
        self, node_id: str, question: str, author: str,
        *, space: str = "public", stake: float = 0.0,
    ) -> Node:
        """Post an **open question** — a first-class slot with no answer yet.

        It is searchable and answerable (by AI or a human). Answering it fills the
        *same* node in place, so one slot == one node throughout its lifecycle.
        """
        if node_id in self.nodes:
            raise OntologyError(f"node {node_id!r} already exists")
        node = Node(
            id=node_id, question=question, answer="", author=author,
            action=Action.QUERY, stake=stake, value_add=True,
            created_at=self._tick(), space=space,
        )
        self.nodes[node_id] = node
        self._finalize(node)
        if stake > 0:
            self.scoring.link(author, node_id, weight=stake)
        return node

    def answer_query(
        self, node_id: str, answer: str, author: str, *, model: str = "",
    ) -> Node:
        """Fill an open query's answer in place — the slot becomes an answer node.

        The same module that answers a brand-new question answers any open slot:
        the node turns into a (freeze-able, provenance-stamped) answer and keeps
        its identity, so contributions already attached to it stay attached.
        """
        node = self._require(node_id)
        if node.action is not Action.QUERY:
            raise OntologyError(f"node {node_id!r} is not an open query")
        node.answer = answer
        node.author = node.author or author
        node.last_editor = author
        node.action = Action.ROOT
        node.status = NodeStatus.ACTIVE
        node.updated_at = self._tick()
        if model:
            self.mark_answered(node_id, model)
        self._finalize(node)
        return node

    def open_queries(self, space: str | None = None) -> list[Node]:
        return [
            n for n in self.nodes.values()
            if n.action is Action.QUERY and self._visible(n, space)
        ]

    # -- frozen answers + edits -----------------------------------------------
    def mark_answered(self, node_id: str, model: str) -> Node:
        """Freeze a node as a provenance-stamped AI answer (immutable body).

        Edits afterwards must come as contributions/forks, never as a body edit —
        this preserves the answer's provenance.
        """
        from datetime import datetime, timezone

        node = self._require(node_id)
        node.frozen = True
        node.model = model
        node.answered_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return node

    def fill_stub(self, node_id: str, answer: str, author: str, model: str) -> Node:
        """Fill an empty concept (stub) with an answer **in place**.

        The slug/address is preserved, so every ``[[Title]]`` that pointed here
        keeps resolving to the same concept — the stub simply graduates from an
        empty placeholder to a real ROOT answer. (docs/design/05: a concept is
        always public commons, so it stays in its public space.)
        """
        node = self._require(node_id)
        if not node.is_stub:
            raise OntologyError(f"node {node_id!r} is already filled")
        node.action = Action.ROOT
        node.answer = answer
        node.author = author
        node.last_editor = author
        self._finalize(node)          # wire wikilinks, index, bump
        self.mark_answered(node_id, model)
        return node

    def edit(self, node_id: str, answer: str, editor: str) -> Node:
        """Edit a node's answer in place (rejected once frozen)."""
        node = self._require(node_id)
        if node.frozen:
            raise OntologyError(
                f"node {node_id!r} is a frozen answer — edit via contributions"
            )
        node.answer = answer
        node.last_editor = editor
        node.updated_at = self._tick()
        self._finalize(node)
        return node

    # -- layers (public commons + group overlays) -----------------------------
    @staticmethod
    def _visible(node: Node, space: str | None) -> bool:
        """A viewer in ``space`` sees the public commons ∪ that space.

        ``space=None`` disables filtering (admin/tests). One-way membrane: a group
        node may reference public, but a public viewer never sees a group node.
        """
        return space is None or node.space == "public" or node.space == space

    # -- multi-currency endorse (public commons coin + per-group coin) ---------
    @staticmethod
    def _is_group(space: str | None) -> bool:
        return space is not None and space != "public"

    def _group_engine(self, space: str) -> ScoreEngine:
        """Get/create the private scorer for ``space`` (shares the hub mode)."""
        eng = self.group_scoring.get(space)
        if eng is None:
            eng = self.group_scoring[space] = ScoreEngine(mode=self.scoring.mode)
        return eng

    def authority_in(self, node_id: str, space: str | None = None) -> float:
        """Authority a viewer in ``space`` sees: public commons **prior** plus,
        for a group viewer, that group's own private endorse **overlay**.

        One-way: the public commons authority never includes any group's coin, so
        a public viewer (``space`` public/None) sees only the shared value, while a
        group re-ranks the same commons locally without ever leaking outward.
        """
        base = self.scoring.authority_of(node_id)
        if self._is_group(space) and space in self.group_scoring:
            base += self.group_scoring[space].authority_of(node_id)
        return base

    def group_endorse(
        self, space: str, evaluator: str, node_id: str, *, weight: float = 1.0
    ) -> None:
        """Record a **group-private** endorsement (free-issue group coin).

        Feeds only the group's own engine — never the public commons and never
        another group — so it is non-convertible and visible only inside ``space``.
        """
        if not self._is_group(space):
            raise OntologyError("group_endorse requires a group space")
        self._group_engine(space).link(evaluator, node_id, weight=weight)
        self.bump()

    def group_linker_position(
        self, space: str, evaluator: str, node_id: str
    ) -> int | None:
        eng = self.group_scoring.get(space)
        return eng.linker_position(evaluator, node_id) if eng else None

    def scoreboard(self, space: str | None = None) -> list[tuple[Node, float]]:
        """Visible non-stub nodes ranked by ``authority_in``, memoised per write.

        The O(N log N) ranking is recomputed only when the write revision changes,
        so a burst of scoreboard reads between writes is O(1) after the first.
        """
        cached = self._board_cache.get(space)
        if cached is not None and cached[0] == self._rev:
            return cached[1]
        ranked = sorted(
            ((n, self.authority_in(n.id, space))
             for n in self.nodes.values()
             if not n.is_stub and self._visible(n, space)),
            key=lambda na: -na[1],
        )
        self._board_cache[space] = (self._rev, ranked)
        return ranked

    def visible_nodes(self, space: str | None = None) -> list[Node]:
        return [n for n in self.nodes.values() if self._visible(n, space)]

    def backlinks(self, slug: str, space: str | None = None) -> list[Node]:
        return [
            n for n in self.nodes.values()
            if slug in n.links and self._visible(n, space)
        ]

    # -- search ----------------------------------------------------------------
    def search(
        self, query: str, space: str | None = None, limit: int = 50
    ) -> list[Node]:
        """Hybrid (BM25 ⊕ semantic) search, re-ranked by authority (our edge).

        The index does relevance at ``O(matching docs)``; the tree then fuses in
        its **authority / group-overlay** signal (``authority_in``), so a query is
        re-ranked by *who endorsed it* — and, inside a group, by that group's own
        private endorsements. A hit on a contribution rolls up to its thread root
        (the shareable unit). Empty query = browse by authority. (docs/design/06.)
        """
        q = (query or "").strip()
        if not q:
            vis = [n for n in self.visible_nodes(space) if not n.is_stub]
            vis.sort(key=lambda n: (-self.authority_in(n.id, space), -n.updated_at))
            return vis[:limit]

        index = self._ensure_index()

        # Membrane: checked per posting hit (O(matches)), so a group-private
        # contribution never surfaces to public via search — without an O(N) scan.
        def visible(doc_id: str) -> bool:
            n = self.nodes.get(doc_id)
            return n is not None and not n.is_stub and self._visible(n, space)

        hits = index.query(q, is_allowed=visible, limit=limit * 4)
        if not hits:
            return []

        # Roll each hit up to its shareable root and accumulate relevance, then
        # lift by adoption (authority the viewer can see in this space).
        rolled: dict[str, float] = {}
        for doc_id, score in hits:
            root = self._top_ancestor(doc_id)
            root_node = self.nodes.get(root)
            if root_node is None or root_node.is_stub or not self._visible(root_node, space):
                continue
            rolled[root] = rolled.get(root, 0.0) + score
        ranked = sorted(
            rolled.items(),
            key=lambda rs: -(rs[1] * (1.0 + ADOPTION_BOOST * self.authority_in(rs[0], space))),
        )
        return [self.nodes[r] for r, _s in ranked[:limit]]

    # -- persistence (the single unified snapshot) ----------------------------
    def to_json(self) -> dict:
        return {
            "schema": 1,
            "clock": self._clock,
            "large_stake_threshold": self.large_stake_threshold,
            "scoring": {
                "mode": self.scoring.mode,
                "authority": dict(self.scoring.authority),
                "hub": dict(self.scoring.hub),
                "linkers": {k: list(v) for k, v in self.scoring._linkers.items()},
            },
            "group_scoring": {
                space: {
                    "authority": dict(eng.authority),
                    "hub": dict(eng.hub),
                    "linkers": {k: list(v) for k, v in eng._linkers.items()},
                }
                for space, eng in self.group_scoring.items()
            },
            "nodes": [self._node_to_json(n) for n in self.nodes.values()],
        }

    @staticmethod
    def _node_to_json(n: Node) -> dict:
        return {
            "id": n.id, "question": n.question, "answer": n.answer,
            "author": n.author, "action": n.action.value,
            "parent_id": n.parent_id, "stake": n.stake, "value_add": n.value_add,
            "created_at": n.created_at, "status": n.status.value,
            "children": list(n.children), "slug": n.slug, "links": list(n.links),
            "frozen": n.frozen, "model": n.model, "answered_at": n.answered_at,
            "space": n.space, "updated_at": n.updated_at,
            "last_editor": n.last_editor, "anchor": n.anchor,
        }

    @staticmethod
    def _node_from_json(d: dict) -> Node:
        return Node(
            id=d["id"], question=d.get("question", ""), answer=d.get("answer", ""),
            author=d.get("author", ""), action=Action(d.get("action", "root")),
            parent_id=d.get("parent_id"), stake=d.get("stake", 0.0),
            value_add=d.get("value_add", True), created_at=d.get("created_at", 0),
            status=NodeStatus(d.get("status", "active")),
            children=list(d.get("children", [])), slug=d.get("slug", ""),
            links=list(d.get("links", [])), frozen=d.get("frozen", False),
            model=d.get("model", ""), answered_at=d.get("answered_at", ""),
            space=d.get("space", "public"), updated_at=d.get("updated_at", 0),
            last_editor=d.get("last_editor", ""), anchor=d.get("anchor", ""),
        )

    @classmethod
    def from_json(cls, data: dict) -> "OntologyTree":
        from collections import defaultdict

        sc = data.get("scoring", {})
        scoring = ScoreEngine(mode=sc.get("mode", "harmonic"))
        scoring.authority = defaultdict(float, sc.get("authority", {}))
        scoring.hub = defaultdict(float, sc.get("hub", {}))
        scoring._linkers = defaultdict(
            list, {k: list(v) for k, v in sc.get("linkers", {}).items()}
        )
        tree = cls(scoring=scoring)
        for space, gs in data.get("group_scoring", {}).items():
            eng = ScoreEngine(mode=scoring.mode)
            eng.authority = defaultdict(float, gs.get("authority", {}))
            eng.hub = defaultdict(float, gs.get("hub", {}))
            eng._linkers = defaultdict(
                list, {k: list(v) for k, v in gs.get("linkers", {}).items()}
            )
            tree.group_scoring[space] = eng
        tree._clock = data.get("clock", 0)
        tree.large_stake_threshold = data.get("large_stake_threshold", 25.0)
        for d in data.get("nodes", []):
            tree.nodes[d["id"]] = cls._node_from_json(d)
        return tree

    # -- migrations from the two legacy app formats ---------------------------
    @classmethod
    def from_wiki_json(cls, data: dict) -> "OntologyTree":
        """Import a legacy ``wiki.json`` snapshot (flat pages + contributions).

        Each page becomes a node (ROOT/QUERY); its flat ``contributions`` thread
        becomes child nodes (comment→CONTRIBUTE, fork→FORK, followup/answer→
        CONTRIBUTE) so the thread is now recursive on the unified model.
        """
        from collections import defaultdict

        sc = data.get("scoring", {})
        scoring = ScoreEngine(mode=sc.get("mode", "harmonic"))
        scoring.authority = defaultdict(float, sc.get("authority", {}))
        scoring.hub = defaultdict(float, sc.get("hub", {}))
        scoring._linkers = defaultdict(
            list, {k: list(v) for k, v in sc.get("linkers", {}).items()}
        )
        tree = cls(scoring=scoring)
        clock = data.get("clock", 0)
        kind_map = {"fork": Action.FORK}
        for p in data.get("pages", []):
            is_query = p.get("kind") == "query"
            node = Node(
                id=p["slug"], question=p["title"], answer=p.get("body", ""),
                author=p["author"],
                action=Action.QUERY if is_query else Action.ROOT,
                created_at=p.get("created_at", 0),
                slug=p["slug"], links=list(p.get("links", [])),
                frozen=p.get("frozen", False), model=p.get("model", ""),
                answered_at=p.get("answered_at", ""),
                space=p.get("space", "public"),
                updated_at=p.get("updated_at", 0),
                last_editor=p.get("last_editor", ""),
            )
            if node.author == STUB_AUTHOR and not node.answer.strip():
                node.action = Action.STUB
            tree.nodes[node.id] = node
            for c in p.get("contributions", []):
                cid = f"{p['slug']}::{c['id']}"
                child = Node(
                    id=cid, question="", answer=c.get("body", ""),
                    author=c.get("author", ""),
                    action=kind_map.get(c.get("kind"), Action.CONTRIBUTE),
                    parent_id=node.id, created_at=node.created_at,
                    slug=cid, space=c.get("space", node.space),
                    model=c.get("model", ""), last_editor=c.get("author", ""),
                )
                tree.nodes[cid] = child
                node.children.append(cid)
        tree._clock = clock
        return tree
