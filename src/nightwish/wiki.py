"""The shared LLM-Wiki — the MVP product (Obsidian + LLM, shared between users).

This is the lean version of the design's *third pole*: Obsidian has **ownership
without connection** (an isolated dead vault); Naver has **connection without
ownership** (locked & cheapened). The wiki adds the missing axis — pages are
written and owned by people, *and* connected to each other (and across users) by
``[[wikilinks]]``.

The differentiator that keeps this from being "just a shared wiki" is the
patent-10-0913256 hub/authority signal, reused verbatim from
:class:`~nightwish.scoring.ScoreEngine`:

* every ``[[wikilink]]`` from page A to page B is a *link in order* — A's author
  endorsing B. Whoever links to a page **early**, before it accumulates many
  links, earns **hub** (foresight / 안목). A page that good hubs link to earns
  **authority** (value). So the wiki surfaces *who saw a good page first*, not
  *what is merely popular*.

Deliberately storage-light: the whole wiki serialises to one JSON snapshot.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from nightwish.scoring import ScoreEngine


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
STUB_AUTHOR = "(stub)"


def slugify(title: str) -> str:
    """A stable, URL-safe id from a page title (Hangul preserved).

    Strips characters that would break a path segment or query string (``?``,
    ``#``, ``/``, ``%``, ``&``, ``+`` …) and folds whitespace to hyphens.
    """
    s = title.strip().lower()
    s = re.sub(r"[\\/?#%&+]+", " ", s)  # URL-breaking chars → space
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def extract_links(body: str) -> list[str]:
    """Ordered, de-duplicated target *titles* referenced by ``[[...]]`` in body."""
    seen: dict[str, None] = {}
    for m in WIKILINK_RE.finditer(body):
        title = m.group(1).strip()
        if title:
            seen.setdefault(title, None)
    return list(seen)


@dataclass
class Page:
    slug: str
    title: str
    body: str
    author: str
    created_at: int
    updated_at: int
    last_editor: str = ""
    #: slugs this page links to (derived from its body's wikilinks)
    links: list[str] = field(default_factory=list)
    #: "page" = knowledge/answer node; "query" = an open public question (질의)
    kind: str = "page"
    #: for a query: "open" (awaiting answers) or "resolved"
    status: str = "open"
    #: a frozen AI answer is immutable (provenance-stamped) — edit via contributions
    frozen: bool = False
    #: model that produced a frozen answer (e.g. "claude-opus-4-8" / "offline-stub")
    model: str = ""
    #: ISO timestamp the answer was produced
    answered_at: str = ""
    #: thread of human (and follow-up AI) contributions layered on this node
    contributions: list = field(default_factory=list)
    #: layer this node lives in: "public" (commons) or a group id. One-way
    #: membrane — group nodes may reference public, but never the reverse.
    space: str = "public"

    @property
    def is_stub(self) -> bool:
        """A placeholder created by an incoming link but not yet written."""
        return self.author == STUB_AUTHOR and not self.body.strip()

    @property
    def is_query(self) -> bool:
        return self.kind == "query"


@dataclass
class Wiki:
    """A shared, multi-user wiki of interlinked markdown pages."""

    scoring: ScoreEngine = field(default_factory=ScoreEngine)
    pages: dict[str, Page] = field(default_factory=dict)
    _clock: int = 0

    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    # -- visibility (layered: public commons + group overlays) ---------------
    @staticmethod
    def _visible(p: "Page", space: str | None) -> bool:
        """Read composition: a viewer in ``space`` sees public ∪ that space.

        ``space=None`` disables filtering (admin/tests).
        """
        return space is None or p.space == "public" or p.space == space

    # -- write ----------------------------------------------------------------
    def save_page(
        self, title: str, body: str, author: str, *, kind: str = "page",
        space: str = "public",
    ) -> Page:
        """Create or edit a page. Wikilinks drive hub/authority scoring.

        A link to a not-yet-existing page auto-creates a **stub** (like Obsidian),
        so the graph stays connected and the target can already accrue authority.
        Only *newly added* links score, so re-saving an unchanged page does not
        double-count — order (who linked first) stays meaningful.
        """
        if not title.strip():
            raise ValueError("page title must not be empty")
        slug = slugify(title)
        now = self._tick()
        existing = self.pages.get(slug)

        target_titles = extract_links(body)
        target_slugs: list[str] = []
        for t in target_titles:
            ts = slugify(t)
            if ts == slug:
                continue  # ignore self-links
            target_slugs.append(ts)
            if ts not in self.pages:
                # a new link target becomes a stub in the *linking* page's layer
                self.pages[ts] = Page(
                    slug=ts, title=t, body="", author=STUB_AUTHOR,
                    created_at=now, updated_at=now, space=space,
                )

        previous_links = set(existing.links) if existing else set()
        newly_added = [ts for ts in target_slugs if ts not in previous_links]

        if existing is None or existing.is_stub:
            created = existing.created_at if existing else now
            sp = existing.space if (existing and not existing.is_stub) else space
            page = Page(
                slug=slug, title=title, body=body, author=author,
                created_at=created, updated_at=now, last_editor=author,
                links=target_slugs, kind=kind, space=sp,
            )
        else:
            page = existing
            page.title = title
            page.body = body
            page.updated_at = now
            page.last_editor = author
            page.links = target_slugs
            # editing keeps the existing kind; an explicit non-default upgrades it
            if kind != "page":
                page.kind = kind
        self.pages[slug] = page

        # score the newly-added endorsements, in body order
        for ts in newly_added:
            self.scoring.link(author, ts, weight=1.0)

        return page

    # -- public queries (사람에게 묻기) --------------------------------------
    def create_query(
        self, title: str, detail: str, author: str, *, space: str = "public"
    ) -> Page:
        """Post an **open public query** — a question search/AI couldn't satisfy.

        It is a first-class node: searchable, structurable, and answerable by
        others. This is design §6 stage ③ (route to humans).
        """
        page = self.save_page(title, detail, author, kind="query", space=space)
        page.status = "open"
        return page

    def answer_query(
        self, query_slug: str, title: str, body: str, author: str,
        *, space: str = "public",
    ) -> Page:
        """Answer an open query: create a knowledge page linked to the query,
        then mark the query resolved. The answer becomes searchable content."""
        query = self.pages.get(query_slug)
        if query is None or not query.is_query:
            raise ValueError(f"{query_slug!r} is not a query")
        # ensure the answer links back to the query (structuring)
        link = f"[[{query.title}]]"
        if link not in body:
            body = f"{body}\n\n관련 질의: {link}"
        answer_title = title.strip() or f"{query.title} — 답변"
        page = self.save_page(answer_title, body, author, space=space)
        query.status = "resolved"
        return page

    def open_queries(self, space: str | None = None) -> list[Page]:
        return [
            p for p in self.list_pages(space)
            if p.is_query and p.status == "open"
        ]

    # -- frozen answers + contribution thread --------------------------------
    def mark_answered(self, slug: str, model: str) -> Page:
        """Freeze a page as a provenance-stamped AI answer (immutable body)."""
        page = self.pages[slug]
        page.frozen = True
        page.model = model
        page.answered_at = _now_iso()
        return page

    def add_contribution(
        self, slug: str, kind: str, author: str, body: str, *, model: str = "",
        space: str = "public",
    ) -> dict:
        """Append a contribution to a node's thread (no edit of the frozen body).

        ``kind`` ∈ comment(의견/보강) · fork(정정/다른 답) · followup(후속질문) ·
        answer(후속질문에 대한 AI 답). Each entry is attributed (who/when/model).
        The contribution carries its own ``space`` — a group member commenting on
        a *public* node keeps that comment in the group layer (one-way membrane).
        """
        page = self.pages.get(slug)
        if page is None:
            raise ValueError(f"unknown page {slug!r}")
        entry = {
            "id": f"c{self._tick()}",
            "kind": kind,
            "author": author,
            "body": body,
            "model": model,
            "space": space,
            "created_at": _now_iso(),
        }
        page.contributions.append(entry)
        page.updated_at = self._tick()
        return entry

    # -- read -----------------------------------------------------------------
    def get(self, slug: str) -> Page | None:
        return self.pages.get(slug)

    def get_by_title(self, title: str) -> Page | None:
        return self.pages.get(slugify(title))

    def backlinks(self, slug: str, space: str | None = None) -> list[Page]:
        """Pages that link *to* ``slug`` (incoming references), visible to ``space``."""
        return [
            p for p in self.pages.values()
            if slug in p.links and p.slug != slug and self._visible(p, space)
        ]

    def list_pages(self, space: str | None = None) -> list[Page]:
        return sorted(
            (p for p in self.pages.values() if self._visible(p, space)),
            key=lambda p: -p.updated_at,
        )

    def _haystack(self, p: "Page") -> tuple[str, str]:
        """(title, full text) lowercased — full text includes the contribution
        thread so follow-up answers/comments are searchable too."""
        body = " ".join([p.body] + [c.get("body", "") for c in p.contributions])
        return p.title.lower(), body.lower()

    def search(self, query: str, space: str | None = None, limit: int = 50) -> list[Page]:
        """Forgiving keyword search: per-token substring frequency + phrase boost.

        - **Substring per token** → CJK-morphology tolerant ("불량" matches "불량률",
          "사출" matches "사출은") and order-free.
        - Searches **title + body + contribution thread**.
        - Exact-phrase match gets an extra boost. Filtered to the viewer's layer.
        Synonyms/paraphrase ("유광"≈"하이그로시") still need vector search — roadmap.
        """
        q = query.strip()
        if not q:
            return self.list_pages(space)
        ql = q.lower()
        qtokens = [t for t in re.split(r"\s+", ql) if t]
        scored: list[tuple[float, Page]] = []
        for p in self.pages.values():
            if not self._visible(p, space):
                continue
            title, text = self._haystack(p)
            score = 0.0
            for t in qtokens:
                score += 3.0 * title.count(t) + 1.0 * text.count(t)
            if ql in title:
                score += 5.0
            elif ql in text:
                score += 2.0
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda sp: (-sp[0], -sp[1].updated_at))
        return [p for _s, p in scored[:limit]]

    # -- scores ---------------------------------------------------------------
    def authority_of(self, slug: str) -> float:
        return self.scoring.authority_of(slug)

    def hub_of(self, user: str) -> float:
        return self.scoring.hub_of(user)

    def top_pages(self, n: int = 10, space: str | None = None) -> list[tuple[Page, float]]:
        scored = [
            (p, self.scoring.authority_of(p.slug))
            for p in self.pages.values()
            if not p.is_stub and self._visible(p, space)
        ]
        scored.sort(key=lambda pa: -pa[1])
        return [(p, a) for p, a in scored if a > 0][:n]

    def top_contributors(self, n: int = 10) -> list[tuple[str, float]]:
        hubs = [(u, h) for u, h in self.scoring.hub.items() if h > 0]
        hubs.sort(key=lambda uh: -uh[1])
        return hubs[:n]

    # -- persistence ----------------------------------------------------------
    def to_json(self) -> dict:
        return {
            "schema": 1,
            "clock": self._clock,
            "scoring": {
                "mode": self.scoring.mode,
                "authority": dict(self.scoring.authority),
                "hub": dict(self.scoring.hub),
                "linkers": {k: list(v) for k, v in self.scoring._linkers.items()},
            },
            "pages": [
                {
                    "slug": p.slug, "title": p.title, "body": p.body,
                    "author": p.author, "created_at": p.created_at,
                    "updated_at": p.updated_at, "last_editor": p.last_editor,
                    "links": list(p.links), "kind": p.kind, "status": p.status,
                    "frozen": p.frozen, "model": p.model,
                    "answered_at": p.answered_at, "contributions": list(p.contributions),
                    "space": p.space,
                }
                for p in self.pages.values()
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "Wiki":
        sc_data = data.get("scoring", {})
        scoring = ScoreEngine(mode=sc_data.get("mode", "harmonic"))
        scoring.authority = defaultdict(float, sc_data.get("authority", {}))
        scoring.hub = defaultdict(float, sc_data.get("hub", {}))
        scoring._linkers = defaultdict(
            list, {k: list(v) for k, v in sc_data.get("linkers", {}).items()}
        )
        wiki = cls(scoring=scoring)
        wiki._clock = data.get("clock", 0)
        for d in data.get("pages", []):
            wiki.pages[d["slug"]] = Page(
                slug=d["slug"], title=d["title"], body=d["body"],
                author=d["author"], created_at=d["created_at"],
                updated_at=d["updated_at"], last_editor=d.get("last_editor", ""),
                links=list(d.get("links", [])),
                kind=d.get("kind", "page"), status=d.get("status", "open"),
                frozen=d.get("frozen", False), model=d.get("model", ""),
                answered_at=d.get("answered_at", ""),
                contributions=list(d.get("contributions", [])),
                space=d.get("space", "public"),
            )
        return wiki

    def save(self, path: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_json(), fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path: str) -> "Wiki | None":
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            return cls.from_json(json.load(fh))
