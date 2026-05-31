"""LLM 북키핑 — 카파시 LLM Wiki의 "LLM이 북키핑한다" 부분.

카파시 설계의 핵심 분업: 인간은 쓰고/큐레이션하고, LLM은 **요약·링크 추출·
일관성 유지**의 고된 북키핑을 맡는다. 여기서는 그 인터페이스(:class:`Bookkeeper`)
를 정의하고, 네트워크 없이 도는 결정론적 stub(:class:`StubBookkeeper`)을 둔다.
실제 LLM은 같은 인터페이스를 구현하는 어댑터로 갈아끼우면 된다(로드맵 P3).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Protocol, runtime_checkable

# [[위키링크]] 문법 (옵시디안식)
_WIKILINK = re.compile(r"\[\[([^\[\]|]+?)(?:\|[^\[\]]*)?\]\]")
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")


def slugify(title: str) -> str:
    """제목을 URL 슬러그로. 한글 등 유니코드 단어문자는 보존한다."""
    text = unicodedata.normalize("NFC", title).strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\-]", "", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "untitled"


@runtime_checkable
class Bookkeeper(Protocol):
    """위키 북키핑 인터페이스 (요약 + 링크 추출)."""

    def summarize(self, title: str, body: str) -> str: ...
    def extract_links(self, body: str) -> list[str]: ...


class StubBookkeeper:
    """네트워크 없는 결정론적 북키핑.

    * 요약: 첫 문장(또는 앞 200자)을 추린다.
    * 링크: 본문의 ``[[...]]`` 를 슬러그로 추출(순서 유지·중복 제거).

    실 LLM 어댑터로 교체하면 더 풍부한 요약/엔티티 추출이 가능하지만, MVS는
    이 stub만으로 카파시식 북키핑의 형태를 갖춘다.
    """

    def summarize(self, title: str, body: str) -> str:
        text = body.strip()
        if not text:
            return ""
        first = _SENTENCE_END.split(text, maxsplit=1)[0].strip()
        if len(first) > 200:
            first = first[:197].rstrip() + "..."
        return first

    def extract_links(self, body: str) -> list[str]:
        seen: dict[str, None] = {}
        for match in _WIKILINK.finditer(body):
            seen.setdefault(slugify(match.group(1)), None)
        return list(seen)
