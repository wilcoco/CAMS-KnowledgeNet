"""Hybrid search index — the service's edge.

The expensive work (tokenising, building an inverted index, computing embedding
vectors) happens **once, at write time** (``upsert``), so a query is cheap —
like any real search service — instead of re-scanning every node.

Two retrieval signals, fused:

* **Lexical (BM25)** over an inverted index. CJK-friendly tokenisation (word
  tokens + character bigrams) gives forgiving Korean partial-match recall with no
  morphological-analyser dependency. A query only touches the postings of its own
  terms, so cost is ``O(matching docs)`` — not ``O(all nodes)``.
* **Semantic (cosine)** over embedding vectors. The embedder is **pluggable**
  (:func:`set_embedder`), exactly like the LLM: production plugs a real model/API;
  dev/tests use a dependency-free deterministic embedding so the whole pipeline
  (and its tests) run offline. Quality scales with the model; the architecture
  does not change.

The engine is deliberately storage-agnostic and keyed by opaque string doc ids,
so it can be unit-tested in isolation from the tree. The tree fuses in its own
**authority / group-overlay** signal on top (see ``docs/design/06-search.md``).
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# Embedding dimensionality for the offline default. Small but enough to separate
# documents; a real embedder may return any (consistent) dimensionality.
_EMBED_DIM = 256

_WORD_RE = re.compile(r"[0-9a-z]+|[가-힣]+", re.UNICODE)
_CJK_RE = re.compile(r"[가-힣]")


def tokenize(text: str) -> list[str]:
    """Lowercased word tokens + CJK character bigrams (order-free recall).

    ``"벡터 시계"`` → ``["벡터", "시계", "벡", "벡터", "터", ...]``-ish: each CJK run
    yields its unigrams and bigrams so partial Korean matches still hit, without a
    morphological analyser.
    """
    text = (text or "").lower()
    out: list[str] = []
    for m in _WORD_RE.finditer(text):
        tok = m.group(0)
        if _CJK_RE.match(tok):
            # CJK run → unigrams + bigrams
            out.extend(tok)
            out.extend(tok[i:i + 2] for i in range(len(tok) - 1))
        else:
            out.append(tok)
    return out


# --------------------------------------------------------------------------- #
# Pluggable embedder (offline-deterministic by default)                        #
# --------------------------------------------------------------------------- #
def offline_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """A dependency-free, deterministic bag-of-n-grams embedding.

    Each token is hashed into a bucket with a signed weight; the vector is L2-
    normalised. Not a learned semantic space — but it makes the *pipeline* real
    and testable offline, and a production embedder drops in via
    :func:`set_embedder` with no other change.
    """
    vec = [0.0] * dim
    toks = tokenize(text)
    if not toks:
        return vec
    for tok in toks:
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        bucket = h % dim
        sign = 1.0 if (h >> 1) & 1 else -1.0
        vec[bucket] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm:
        vec = [v / norm for v in vec]
    return vec


_embed_fn: Callable[[str], list[float]] = offline_embed


def set_embedder(fn: Callable[[str], list[float]]) -> None:
    """Swap the embedding function (e.g. a real model/API in production)."""
    global _embed_fn
    _embed_fn = fn


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))  # both L2-normalised → dot = cosine


@dataclass
class _Doc:
    tf: dict[str, int]
    length: int
    vec: list[float]


@dataclass
class HybridIndex:
    """Incremental hybrid (BM25 ⊕ vector) index over opaque string docs."""

    k1: float = 1.5
    b: float = 0.75
    #: weight of the lexical signal in fusion (rest goes to semantic)
    alpha: float = 0.6

    docs: dict[str, _Doc] = field(default_factory=dict)
    #: term -> set of doc ids containing it (postings; tf lives on the doc)
    postings: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    _total_len: int = 0

    # -- maintenance (write time) --------------------------------------------
    def upsert(self, doc_id: str, text: str) -> None:
        self.remove(doc_id)
        toks = tokenize(text)
        tf: dict[str, int] = defaultdict(int)
        for t in toks:
            tf[t] += 1
        doc = _Doc(tf=dict(tf), length=len(toks), vec=_embed_fn(text))
        self.docs[doc_id] = doc
        for term in tf:
            self.postings[term].add(doc_id)
        self._total_len += doc.length

    def remove(self, doc_id: str) -> None:
        old = self.docs.pop(doc_id, None)
        if old is None:
            return
        self._total_len -= old.length
        for term in old.tf:
            p = self.postings.get(term)
            if p:
                p.discard(doc_id)
                if not p:
                    del self.postings[term]

    # -- query (read time) ----------------------------------------------------
    @property
    def _avgdl(self) -> float:
        return (self._total_len / len(self.docs)) if self.docs else 0.0

    def _bm25(
        self, query_terms: list[str], is_allowed: Optional[Callable[[str], bool]]
    ) -> dict[str, float]:
        """BM25 over only the docs that contain a query term (cheap recall).

        ``is_allowed`` is checked **per posting hit** (so the membrane filter costs
        ``O(matching docs)``, never ``O(all nodes)``).
        """
        N = len(self.docs)
        if not N:
            return {}
        avgdl = self._avgdl or 1.0
        scores: dict[str, float] = defaultdict(float)
        seen_terms: set[str] = set()
        for term in query_terms:
            if term in seen_terms:
                continue
            seen_terms.add(term)
            posting = self.postings.get(term)
            if not posting:
                continue
            df = len(posting)
            idf = math.log(1.0 + (N - df + 0.5) / (df + 0.5))
            for doc_id in posting:
                if is_allowed is not None and not is_allowed(doc_id):
                    continue
                doc = self.docs[doc_id]
                tf = doc.tf.get(term, 0)
                denom = tf + self.k1 * (1.0 - self.b + self.b * doc.length / avgdl)
                scores[doc_id] += idf * (tf * (self.k1 + 1.0)) / (denom or 1.0)
        return scores

    def query(
        self,
        text: str,
        *,
        is_allowed: Optional[Callable[[str], bool]] = None,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        """Return ``(doc_id, fused_score)`` best-first.

        ``is_allowed(doc_id)`` enforces the membrane on each candidate (applied
        only to docs a query term actually hit). Fusion: lexical recalls the
        candidate pool (BM25), then the semantic signal re-ranks that pool.
        """
        terms = tokenize(text)
        if not terms:
            return []
        lex = self._bm25(terms, is_allowed)
        if not lex:
            return []
        qvec = _embed_fn(text)
        lex_max = max(lex.values()) or 1.0
        fused: list[tuple[str, float]] = []
        for doc_id, lscore in lex.items():
            sem = _cosine(qvec, self.docs[doc_id].vec)        # in [-1, 1]
            sem = (sem + 1.0) / 2.0                            # → [0, 1]
            score = self.alpha * (lscore / lex_max) + (1.0 - self.alpha) * sem
            fused.append((doc_id, score))
        fused.sort(key=lambda ds: -ds[1])
        return fused[:limit]
