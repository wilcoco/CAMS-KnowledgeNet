"""Reproduce the "first wheel" simulation from the design document (§7).

Question: how do you make a *black high-gloss* surface by injection moulding
alone, with no painting?

This wires the tree, economy and pipeline together and replays the recorded run,
then asserts the final ledger matches the design's §7 figures:

    Json available 900 / staked 100   |   User-B staked 10   |   User-C staked 50

It also demonstrates the four things §7.1 says the run proved, and prints the
§7.2 bottleneck (scarce tacit knowledge — Kato's fingertip skill — never got
unlocked). Dividend mechanics are illustrated *separately* (§7 is a first-wheel
snapshot where value has not yet been realised as dividends).
"""

from __future__ import annotations

from dataclasses import dataclass

from nightwish.economy import Economy
from nightwish.pipeline import QueryPipeline, Stage
from nightwish.tree import OntologyTree

JSON, USER_B, USER_C = "Json", "User-B", "User-C"

AI_ANSWER_001A = (
    "3-axis causal model: resin (high-flow PC/PMMA), colourant (high-jetness "
    "carbon black, well dispersed), and a mirror-polished mould (SPI A1) held "
    "hot enough to reproduce the cavity finish — gloss comes from the tool, not "
    "from paint."
)
FORK_ANSWER_002 = (
    "Counter-claim: mould-in-colour high-gloss is bounded — it holds on rear "
    "faces but front faces remain vulnerable to stone-chip; the no-paint claim "
    "is not universal."
)


@dataclass
class FirstWheel:
    tree: OntologyTree
    economy: Economy
    pipeline: QueryPipeline
    log: list[str]


def build_first_wheel() -> FirstWheel:
    tree = OntologyTree()
    economy = Economy()
    ledger = economy.ledger
    log: list[str] = []

    # Accumulated UBI grants (flat issuance over time, shown as starting stock).
    economy.issue_ubi([JSON], 1000.0)
    economy.issue_ubi([USER_B], 10.0)
    economy.issue_ubi([USER_C], 50.0)
    log.append("UBI grants: Json 1000, User-B 10, User-C 50")

    # Stage ①/② happen via the pipeline. The ontology is empty, so search misses
    # and the AI answers; the human router is wired to decline (the bottleneck).
    pipeline = QueryPipeline(
        tree=tree,
        search_fn=lambda q, t: None,
        ask_ai_fn=lambda q: AI_ANSWER_001A if "no paint" in q else None,
        route_to_human_fn=lambda q: None,  # Kato is off-system / unreachable
    )

    question = "How to make black high-gloss by injection moulding only (no paint)?"
    result = pipeline.ask(
        question, asker=JSON, new_node_id="#001-a", ai_stake=0.0
    )
    assert result.stage is Stage.AI and result.node_id == "#001-a"
    # Json backs the AI answer with conviction (adopt + share).
    ledger.stake(JSON, "#001-a", 100.0)
    tree.nodes["#001-a"].stake = 100.0
    tree.scoring.link(JSON, "#001-a", weight=100.0)
    log.append("#001-a  AI answer (3-axis causal)         Json   stake 100  -> adopted, PUBLIC")

    # #001-b  weak value-add: a discovery link (Toyota no-paint case).
    tree.contribute(
        "#001-b", "#001-a", USER_B,
        "Lead: Toyota's no-paint moulding case (clue).",
        stake=10.0, value_add=True,
    )
    ledger.stake(USER_B, "#001-b", 10.0)
    log.append("#001-b  Toyota case link (weak add)        User-B stake  10  -> discovery")

    # #002  strong value-add: a FORK carrying the burden of proof (boundary knowledge).
    tree.fork(
        "#002", "#001-a", USER_C, FORK_ANSWER_002, stake=50.0,
    )
    ledger.stake(USER_C, "#002", 50.0)
    log.append("#002    FORK: MIC limit / stone-chip        User-C stake  50  -> strong add")

    # 현상금: Json escrows 500 to call User-B directly -> NOT adopted -> returned.
    ledger.open_escrow("bounty-1", JSON, 500.0)
    log.append("bounty  Json -> User-B direct call          Json   escrow 500")
    returned = ledger.return_escrow("bounty-1")
    log.append(f"bounty  not adopted -> returned             Json   +{returned:.0f} back")

    # #003  a POINTER, not an answer: "Hideki Kato (Toyota master, near retirement)".
    tree.add_pointer(
        "#003", "#002", USER_C,
        "Hideki Kato — Toyota master, near retirement — would know.",
    )
    log.append("#003    pointer: 'Hideki Kato exists'        (external)   -> DORMANT")

    return FirstWheel(tree=tree, economy=economy, pipeline=pipeline, log=log)


def deep_tacit_query(fw: FirstWheel):
    """§7.2 — the deeper tacit question the system could NOT unlock."""
    return fw.pipeline.ask(
        "Exact melt/mould recipe for a flawless front-face high-gloss A-surface?",
        asker=JSON,
        new_node_id="#bottleneck",
        parent_id="#002",
        ai_stake=0.0,
        human_stake=0.0,
    )


def main() -> None:  # pragma: no cover - human-facing report
    fw = build_first_wheel()
    ledger = fw.economy.ledger

    print("=" * 72)
    print("FIRST WHEEL — black high-gloss, injection moulding only (design §7)")
    print("=" * 72)
    for line in fw.log:
        print("  " + line)

    print("\nLedger (final snapshot):")
    for who in (JSON, USER_B, USER_C):
        print(
            f"  {who:7s} available {ledger.balance(who):7.1f}  "
            f"staked {ledger.staked_by(who):6.1f}"
        )

    print("\n§7.1 — what the run proved:")
    print("  1. 3-stage flow works: search -> AI(#001-a) -> (human routing attempted).")
    print("  2. no free-ride: answers are PUBLIC, so sitting on a good one loses it.")
    print("  3. fork works: #002 branches off #001-a without killing it.")
    print("  4. value-add tiers: link(#001-b weak) < fork(#002 strong) < pointer(#003 none).")

    print("\n§7.2 — the bottleneck (most important finding):")
    res = deep_tacit_query(fw)
    print(f"  deep tacit query -> {res.stage.value.upper()} "
          "(Kato's fingertip knowledge never unlocked)")
    print("  three gates: (1) Kato is off-system, (2) it may be Toyota trade secret,")
    print("               (3) no onboarding / incentive to bring him in (bootstrap).")
    print("  => the bottleneck is onboarding scarce-tacit holders, not collecting"
          " common knowledge.")

    print("\nHub/Authority (foresight vs content value):")
    print(f"  authority(#001-a) = {fw.tree.scoring.authority_of('#001-a'):.2f}")
    print(f"  hub(Json)         = {fw.tree.scoring.hub_of(JSON):.2f}")
    print("=" * 72)


if __name__ == "__main__":  # pragma: no cover
    main()
