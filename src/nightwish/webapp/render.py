"""아주 작은 마크다운 + `[[위키링크]]` 렌더러 (외부 의존성 회피).

완전한 마크다운이 아니라 MVS에 필요한 만큼만: 헤더, 굵게/기울임, 인라인 코드,
목록, 문단, 그리고 옵시디안식 `[[제목]]` / `[[제목|표시]]` 링크. 먼저 HTML을
이스케이프한 뒤 인라인 태그를 삽입하므로 사용자 입력은 안전하게 처리된다.
"""

from __future__ import annotations

import html
import re

from nightwish.wiki.bookkeeper import slugify

_WIKILINK = re.compile(r"\[\[([^\[\]|]+?)(?:\|([^\[\]]*))?\]\]")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE = re.compile(r"`([^`]+?)`")


def _inline(text: str, existing: set[str]) -> str:
    text = html.escape(text)

    def wl(m: re.Match) -> str:
        target = m.group(1).strip()
        label = (m.group(2) or target).strip()
        slug = slugify(target)
        cls = "wikilink" if slug in existing else "wikilink missing"
        return f'<a class="{cls}" href="/wiki/{slug}">{html.escape(label)}</a>'

    # 위키링크 원문은 이스케이프 전 패턴이지만, escape가 []|를 건드리지 않으므로
    # 이스케이프 후에도 매칭된다.
    text = _WIKILINK.sub(wl, text)
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def render_markdown(body: str, existing_slugs: set[str] | None = None) -> str:
    """마크다운 본문을 안전한 HTML로 변환한다."""
    existing = existing_slugs or set()
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in body.splitlines():
        line = raw.rstrip()
        if not line.strip():
            close_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2), existing)}</h{level}>")
            continue
        item = re.match(r"^[-*]\s+(.*)$", line)
        if item:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(item.group(1), existing)}</li>")
            continue
        close_list()
        out.append(f"<p>{_inline(line, existing)}</p>")

    close_list()
    return "\n".join(out)
