"""Real embedding backend: gating, normalisation, caching, and live install."""

import math

import nightwish.embeddings as emb
from nightwish import search


def test_disabled_returns_none(monkeypatch):
    monkeypatch.delenv("NIGHTWISH_ENABLE_EMBEDDINGS", raising=False)
    assert emb.make_embed_fn() is None
    # enabled flag but no key → still None
    monkeypatch.setenv("NIGHTWISH_ENABLE_EMBEDDINGS", "1")
    monkeypatch.delenv("EMBEDDINGS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert emb.make_embed_fn() is None


def test_embedder_normalises_and_caches(monkeypatch):
    monkeypatch.setenv("NIGHTWISH_ENABLE_EMBEDDINGS", "1")
    monkeypatch.setenv("EMBEDDINGS_API_KEY", "test-key")
    calls = {"n": 0}

    def fake_remote(text, *, model, base_url):
        calls["n"] += 1
        return emb._l2_normalize([3.0, 4.0])      # → [0.6, 0.8]

    monkeypatch.setattr(emb, "embed_remote", fake_remote)
    fn = emb.make_embed_fn()
    assert fn is not None
    v = fn("벡터 시계")
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-9)
    fn("벡터 시계")                                 # identical text → cache hit
    assert calls["n"] == 1                          # remote called only once


def test_configure_embeddings_installs_into_search(monkeypatch):
    from nightwish import unified

    monkeypatch.setenv("NIGHTWISH_ENABLE_EMBEDDINGS", "1")
    monkeypatch.setenv("EMBEDDINGS_API_KEY", "test-key")
    monkeypatch.setattr(emb, "embed_remote",
                        lambda t, *, model, base_url: [1.0, 0.0, 0.0])
    try:
        assert unified.configure_embeddings() is True
        idx = search.HybridIndex()
        idx.upsert("x", "hello")
        assert idx.docs["x"].vec == [1.0, 0.0, 0.0]   # real embedder in effect
    finally:
        search.set_embedder(search.offline_embed)     # restore offline default
