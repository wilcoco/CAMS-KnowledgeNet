"""Real embedding backend (optional) — the semantic half of hybrid search.

Mirrors :mod:`nightwish.llm`: the search engine ships with a dependency-free
offline embedding so the whole pipeline runs and tests pass with no network. When
``NIGHTWISH_ENABLE_EMBEDDINGS`` is truthy **and** an embeddings API key is present,
:func:`make_embed_fn` returns a real embedder (any OpenAI-compatible
``/embeddings`` endpoint — OpenAI, Voyage, a local server, …) that the app installs
via :func:`nightwish.search.set_embedder`. Everything else — index, fusion,
ranking, persistence — is identical; only the vector quality changes.

Config (env):
    NIGHTWISH_ENABLE_EMBEDDINGS = 1|true|yes
    EMBEDDINGS_API_KEY          (or OPENAI_API_KEY)
    EMBEDDINGS_BASE_URL         default https://api.openai.com/v1
    EMBEDDINGS_MODEL            default text-embedding-3-small
"""
from __future__ import annotations

import math
import os
from typing import Callable, Optional

DEFAULT_EMBED_MODEL = os.environ.get("EMBEDDINGS_MODEL", "text-embedding-3-small")
DEFAULT_BASE_URL = os.environ.get("EMBEDDINGS_BASE_URL", "https://api.openai.com/v1")


def _api_key() -> Optional[str]:
    return os.environ.get("EMBEDDINGS_API_KEY") or os.environ.get("OPENAI_API_KEY")


def _ready() -> bool:
    if os.environ.get("NIGHTWISH_ENABLE_EMBEDDINGS", "").lower() not in ("1", "true", "yes"):
        return False
    return bool(_api_key())


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def embed_remote(
    text: str, *, model: str = DEFAULT_EMBED_MODEL, base_url: str = DEFAULT_BASE_URL
) -> list[float]:
    """Embed one text via an OpenAI-compatible ``/embeddings`` endpoint."""
    import httpx  # lazy — only when the real backend is active

    resp = httpx.post(
        f"{base_url.rstrip('/')}/embeddings",
        headers={"Authorization": f"Bearer {_api_key()}",
                 "Content-Type": "application/json"},
        json={"model": model, "input": text or " "},
        timeout=30.0,
    )
    resp.raise_for_status()
    vec = resp.json()["data"][0]["embedding"]
    return _l2_normalize([float(x) for x in vec])  # cosine == dot on normalised


def make_embed_fn() -> Optional[Callable[[str], list[float]]]:
    """A cached real embedder, or ``None`` if the backend is not configured.

    Embedding is a paid/network call, so identical texts (e.g. on reindex or a
    re-edit that didn't change the body) are memoised in-process.
    """
    if not _ready():
        return None
    model = DEFAULT_EMBED_MODEL
    base_url = DEFAULT_BASE_URL
    cache: dict[str, list[float]] = {}

    def embed(text: str) -> list[float]:
        key = text or ""
        hit = cache.get(key)
        if hit is not None:
            return hit
        vec = embed_remote(key, model=model, base_url=base_url)
        cache[key] = vec
        return vec

    return embed
