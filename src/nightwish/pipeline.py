"""The 3-stage query-handling flow (design §6).

::

    question
      ├ ① cheap search of the existing human-ontology first
      │     └ enough  -> [cheap AI + human-verified] answer (competitive edge)
      ├ ② not enough -> ask the AI -> the first Q&A becomes a new node
      └ ③ AI also short -> route a point-laden question to a human on that
            ontology branch -> their tacit knowledge is unlocked -> new node

The self-reinforcing loop: the more it is used, the more stage ① resolves, the
less it leans on the AI, the lower the cost — while the human-knowledge asset
compounds. Stage ③ is the heart: tacit knowledge the AI cannot give (Polanyi:
"we know more than we can tell") is pulled into explicit form by point
incentives (Nonaka's SECI loop, market-driven).

The functions here are deliberately pluggable: ``search_fn``, ``ask_ai_fn`` and
``route_to_human_fn`` are injected so the prototype can run fully offline (the
simulation supplies canned versions) while the routing *logic* stays real.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from nightwish.tree import OntologyTree


class Stage(str, Enum):
    SEARCH = "search"   # ① resolved from existing human ontology
    AI = "ai"           # ② resolved by asking the AI (new node)
    HUMAN = "human"     # ③ routed to a human expert (new node)
    UNRESOLVED = "unresolved"  # even the human had no answer (bottleneck)


@dataclass
class QueryResult:
    question: str
    stage: Stage
    answer: Optional[str]
    node_id: Optional[str] = None


# A search returns an existing node id if the ontology already answers well.
SearchFn = Callable[[str, OntologyTree], Optional[str]]
# The AI either answers (str) or declines (None).
AskAiFn = Callable[[str], Optional[str]]
# A human on the branch either answers (str) or declines (None).
RouteToHumanFn = Callable[[str], Optional[str]]


@dataclass
class QueryPipeline:
    tree: OntologyTree
    search_fn: SearchFn
    ask_ai_fn: AskAiFn
    route_to_human_fn: RouteToHumanFn

    def ask(
        self,
        question: str,
        *,
        asker: str,
        new_node_id: str,
        parent_id: Optional[str] = None,
        ai_stake: float = 0.0,
        human_stake: float = 0.0,
    ) -> QueryResult:
        """Run a question through the three stages, creating nodes as needed."""
        # ① cheap search of the existing human ontology
        hit = self.search_fn(question, self.tree)
        if hit is not None:
            return QueryResult(question, Stage.SEARCH, self.tree.nodes[hit].answer, hit)

        # ② ask the AI; the first Q&A becomes a node
        ai_answer = self.ask_ai_fn(question)
        if ai_answer is not None:
            node = self._materialise(
                new_node_id, question, ai_answer, asker, parent_id, ai_stake
            )
            return QueryResult(question, Stage.AI, ai_answer, node.id)

        # ③ AI fell short -> route the point-laden question to a human
        human_answer = self.route_to_human_fn(question)
        if human_answer is not None:
            node = self._materialise(
                new_node_id, question, human_answer, asker, parent_id, human_stake
            )
            return QueryResult(question, Stage.HUMAN, human_answer, node.id)

        # The bottleneck: scarce tacit knowledge that never got unlocked.
        return QueryResult(question, Stage.UNRESOLVED, None, None)

    def _materialise(self, node_id, question, answer, author, parent_id, stake):
        if parent_id is None:
            return self.tree.add_root(node_id, question, answer, author, stake)
        return self.tree.contribute(node_id, parent_id, author, answer, stake,
                                    question=question)
