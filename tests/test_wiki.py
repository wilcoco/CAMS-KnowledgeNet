"""The shared LLM-Wiki: pages, wikilinks, stubs, and the hub/authority signal."""

import pytest

from nightwish.wiki import Wiki, slugify


def test_save_and_get_page():
    w = Wiki()
    p = w.save_page("사출 하이그로시", "# 사출 하이그로시\n\n무도장 유광...", "Json")
    assert p.author == "Json" and not p.is_stub
    assert w.get_by_title("사출 하이그로시") is p
    assert w.get(slugify("사출 하이그로시")) is p


def test_wikilink_creates_stub_and_backlink():
    w = Wiki()
    w.save_page("게이트 설계", "참고: [[웰드라인]] 위치가 핵심", "Json")
    stub = w.get_by_title("웰드라인")
    assert stub is not None and stub.is_stub
    # backlink points from the writing page to the stub
    assert any(b.title == "게이트 설계" for b in w.backlinks(stub.slug))


def test_link_order_rewards_foresight():
    """누가 먼저 좋은 문서를 알아보고 링크했나 = 허브(안목)."""
    w = Wiki()
    w.save_page("페이지 A", "[[핵심 노하우]] 참고", "a1")
    w.save_page("페이지 B", "[[핵심 노하우]] 도 보세요", "a2")
    w.save_page("페이지 C", "역시 [[핵심 노하우]]", "a3")
    # earliest linker earns the most hub; the last earns nothing new
    assert w.hub_of("a1") > w.hub_of("a2") > w.hub_of("a3")
    assert w.hub_of("a3") == 0.0
    # the linked page accrues authority
    assert w.authority_of(slugify("핵심 노하우")) > 0


def test_resaving_same_body_does_not_double_count():
    w = Wiki()
    w.save_page("A", "[[T]]", "u1")
    w.save_page("B", "[[T]]", "u2")  # validates u1 -> u1 gains hub
    hub_before = w.hub_of("u1")
    w.save_page("B", "[[T]] 그대로", "u2")  # same link target, no new link
    assert w.hub_of("u1") == hub_before


def test_editing_stub_fills_it():
    w = Wiki()
    w.save_page("A", "[[목표]]", "u1")          # creates stub '목표'
    assert w.get_by_title("목표").is_stub
    w.save_page("목표", "# 목표\n\n채워진 내용", "u2")
    filled = w.get_by_title("목표")
    assert not filled.is_stub and filled.author == "u2"


def test_top_pages_excludes_stubs():
    w = Wiki()
    w.save_page("A", "[[T]]", "u1")
    w.save_page("B", "[[T]]", "u2")
    # T is a stub (never written) -> must not appear in top_pages
    assert all(p.slug != slugify("T") for p, _ in w.top_pages())


def test_search_is_forgiving_and_covers_thread():
    w = Wiki()
    p = w.save_page("사출 공정", "웰드라인 불량률을 낮추는 법", "a")
    w.add_contribution(p.slug, "answer", "AI", "게이트를 0.1mm 미세조정한다")
    w.save_page("게이트 설계", "사출 압력 조정", "a")
    titles = lambda q: [x.title for x in w.search(q)]
    assert "사출 공정" in titles("불량")        # 불량 ⊂ 불량률 (substring-forgiving)
    assert "사출 공정" in titles("미세조정")     # contribution thread is searchable
    assert set(titles("사출")) == {"사출 공정", "게이트 설계"}  # both contain 사출


def test_persistence_round_trip(tmp_path):
    path = str(tmp_path / "wiki.json")
    w = Wiki()
    w.save_page("A", "[[T]] 설명", "u1")
    w.save_page("B", "[[T]] 또", "u2")
    w.save(path)

    w2 = Wiki.load(path)
    assert w2 is not None
    assert w2.get_by_title("A").body.startswith("[[T]]")
    assert w2.hub_of("u1") == w.hub_of("u1")
    assert w2.authority_of(slugify("T")) == w.authority_of(slugify("T"))
