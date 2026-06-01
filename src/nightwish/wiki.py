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

from nightwish.scoring import ScoreEngine

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
STUB_AUTHOR = "(stub)"


def slugify(title: str) -> str:
    """A stable id from a page title (Hangul preserved; spaces/slashes folded)."""
    s = title.strip().lower()
    s = s.replace("/", "-").replace("\\", "-")
    s = re.sub(r"\s+", "-", s)
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

    @property
    def is_stub(self) -> bool:
        """A placeholder created by an incoming link but not yet written."""
        return self.author == STUB_AUTHOR and not self.body.strip()


@dataclass
class Wiki:
    """A shared, multi-user wiki of interlinked markdown pages."""

    scoring: ScoreEngine = field(default_factory=ScoreEngine)
    pages: dict[str, Page] = field(default_factory=dict)
    _clock: int = 0

    def _tick(self) -> int:
        self._clock += 1
        return self._clock

    # -- write ----------------------------------------------------------------
    def save_page(self, title: str, body: str, author: str) -> Page:
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
                self.pages[ts] = Page(
                    slug=ts, title=t, body="", author=STUB_AUTHOR,
                    created_at=now, updated_at=now,
                )

        previous_links = set(existing.links) if existing else set()
        newly_added = [ts for ts in target_slugs if ts not in previous_links]

        if existing is None or existing.is_stub:
            created = existing.created_at if existing else now
            page = Page(
                slug=slug, title=title, body=body, author=author,
                created_at=created, updated_at=now, last_editor=author,
                links=target_slugs,
            )
        else:
            page = existing
            page.title = title
            page.body = body
            page.updated_at = now
            page.last_editor = author
            page.links = target_slugs
        self.pages[slug] = page

        # score the newly-added endorsements, in body order
        for ts in newly_added:
            self.scoring.link(author, ts, weight=1.0)

        return page

    # -- read -----------------------------------------------------------------
    def get(self, slug: str) -> Page | None:
        return self.pages.get(slug)

    def get_by_title(self, title: str) -> Page | None:
        return self.pages.get(slugify(title))

    def backlinks(self, slug: str) -> list[Page]:
        """Pages that link *to* ``slug`` (incoming references)."""
        return [p for p in self.pages.values() if slug in p.links and p.slug != slug]

    def list_pages(self) -> list[Page]:
        return sorted(self.pages.values(), key=lambda p: -p.updated_at)

    def search(self, query: str) -> list[Page]:
        q = query.strip().lower()
        if not q:
            return self.list_pages()
        return [
            p for p in self.list_pages()
            if q in p.title.lower() or q in p.body.lower()
        ]

    # -- scores ---------------------------------------------------------------
    def authority_of(self, slug: str) -> float:
        return self.scoring.authority_of(slug)

    def hub_of(self, user: str) -> float:
        return self.scoring.hub_of(user)

    def top_pages(self, n: int = 10) -> list[tuple[Page, float]]:
        scored = [
            (p, self.scoring.authority_of(p.slug))
            for p in self.pages.values() if not p.is_stub
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
                    "links": list(p.links),
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
