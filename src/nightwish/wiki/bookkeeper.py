"""LLM 북키핑 — 카파시 LLM Wiki의 "LLM이 북키핑한다" 부분.

카파시 설계의 핵심 분업: 인간은 쓰고/큐레이션하고, LLM은 **요약·엔티티 추출·
링크 정리**의 고된 북키핑을 맡는다. 여기서 인터페이스(:class:`Bookkeeper`)와 두
구현을 제공한다:

* :class:`StubBookkeeper` — 네트워크 없이 도는 결정론적 기본값(첫 문장 요약,
  ``[[위키링크]]`` 추출). 테스트·오프라인·키 없는 환경용.
* :class:`LLMBookkeeper` — 실제 Anthropic Claude로 요약·엔티티·링크를 추출
  (공식 ``anthropic`` SDK + 구조화 출력). ``ANTHROPIC_API_KEY`` 필요.

:func:`make_bookkeeper` 가 환경을 보고 적절한 구현을 고른다(키 있으면 LLM, 없으면
stub). 모델은 ``NIGHTWISH_LLM_MODEL`` 로 바꿀 수 있다(기본 ``claude-opus-4-8``).
"""

from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

_WIKILINK = re.compile(r"\[\[([^\[\]|]+?)(?:\|[^\[\]]*)?\]\]")
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")


def slugify(title: str) -> str:
    """제목을 URL 슬러그로. 한글 등 유니코드 단어문자는 보존한다."""
    text = unicodedata.normalize("NFC", title).strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\-]", "", text, flags=re.UNICODE)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text or "untitled"


@dataclass
class BookkeepingResult:
    """북키핑 산출물: 요약 + 링크(슬러그) + 엔티티(개념/고유명사)."""

    summary: str = ""
    links: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)


@runtime_checkable
class Bookkeeper(Protocol):
    def analyze(self, title: str, body: str) -> BookkeepingResult: ...

    def draft(self, title: str, context: str = "") -> str:
        """빈 위키링크 제목을 *질문*으로 보고 페이지 본문 초안을 만든다.

        설계상 노드 = 인간Q + AI답이므로, 채워지지 않은 링크를 누르는 것은 곧
        새 질문을 던지는 행위다. AI가 *재료(죽은 노동)* 로서 초안을 내면 사람이
        받아 큐레이션한다(산 노동). ``context`` 는 이 항목을 링크한 기존 문서들.
        """
        ...


class StubBookkeeper:
    """네트워크 없는 결정론적 북키핑.

    * 요약: 첫 문장(또는 앞 200자).
    * 링크: 본문의 ``[[...]]`` 를 슬러그로 추출(순서 유지·중복 제거).
    * 엔티티: stub은 빈 리스트(실 추출은 LLM 몫).
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

    def analyze(self, title: str, body: str) -> BookkeepingResult:
        return BookkeepingResult(
            summary=self.summarize(title, body),
            links=self.extract_links(body),
            entities=[],
        )

    def draft(self, title: str, context: str = "") -> str:
        """키 없는 환경의 결정론적 초안: 제목을 질문으로 세운 골격.

        실제 AI 답은 :class:`LLMBookkeeper` 의 몫이다. 여기서는 사람이 바로 이어
        쓸 수 있게 질문 틀과 (있다면) 링크 출처만 제시한다.
        """
        lines = [f"# {title}", ""]
        if context.strip():
            lines += ["> 이 항목을 링크한 문서:", ""]
            lines += [f"> - {ln}" for ln in context.strip().splitlines()]
            lines += [""]
        lines += [
            "## 질문",
            "",
            f"{title}(이)란 무엇이며, 왜 중요한가?",
            "",
            "## 답 (초안)",
            "",
            "_아직 채워지지 않았습니다. 직접 작성하거나, `ANTHROPIC_API_KEY` 를 "
            "설정하면 AI가 초안을 생성합니다._",
        ]
        return "\n".join(lines)


_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "entities": {"type": "array", "items": {"type": "string"}},
        "wikilinks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "entities", "wikilinks"],
    "additionalProperties": False,
}

_SYSTEM = (
    "You are the bookkeeping layer of a collaborative knowledge wiki (after "
    "Karpathy's LLM Wiki). Given a page title and body, produce: a one- to two-"
    "sentence summary in the body's own language; the key entities/concepts "
    "(proper nouns, technical terms) as short strings; and the set of related "
    "page titles that should be wiki-linked. Always include any titles already "
    "marked with [[double brackets]] in the body among the wikilinks. Keep it "
    "faithful — do not invent facts."
)


_DRAFT_SYSTEM = (
    "You are the drafting layer of a collaborative knowledge wiki (after "
    "Karpathy's LLM Wiki). A user clicked an empty wiki-link; treat its title as "
    "a question/topic and write a concise FIRST-DRAFT page that a human will then "
    "curate and verify. Write in the title's language (Korean if the title is "
    "Korean). Use short markdown: one heading, then 2-4 short paragraphs or "
    "bullets. Link clearly-related concepts with [[double brackets]]. Be honest "
    "about uncertainty — do NOT invent specific numbers, sources, or facts; frame "
    "open questions plainly so the human knows what to verify."
)


class LLMBookkeeper:
    """실제 Claude로 요약·엔티티·링크를 추출 (구조화 출력)."""

    def __init__(self, client=None, model: str | None = None) -> None:
        import anthropic  # 지연 임포트: 키 없는 환경에서 import 비용 회피

        self._anthropic = anthropic
        self.client = client or anthropic.Anthropic()  # ANTHROPIC_API_KEY 사용
        self.model = model or os.environ.get("NIGHTWISH_LLM_MODEL", "claude-opus-4-8")
        self._stub = StubBookkeeper()  # 실패 시 폴백

    def analyze(self, title: str, body: str) -> BookkeepingResult:
        if not body.strip():
            return BookkeepingResult()
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                # 안정적 접두사를 캐시 (프롬프트 캐싱 모범사례; 짧으면 무해히 미적용)
                system=[{
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
                messages=[{
                    "role": "user",
                    "content": f"TITLE: {title}\n\nBODY:\n{body}",
                }],
            )
        except Exception:
            # 네트워크/한도/인증 오류 시 결정론적 stub으로 폴백 — 서비스는 죽지 않는다
            return self._stub.analyze(title, body)

        import json
        text = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return self._stub.analyze(title, body)

        links = [slugify(s) for s in data.get("wikilinks", []) if s.strip()]
        # 순서 유지 중복 제거
        seen: dict[str, None] = {}
        for s in links:
            seen.setdefault(s, None)
        return BookkeepingResult(
            summary=data.get("summary", "").strip(),
            links=list(seen),
            entities=[e.strip() for e in data.get("entities", []) if e.strip()],
        )

    def draft(self, title: str, context: str = "") -> str:
        user = f"TITLE: {title}"
        if context.strip():
            user += f"\n\nThis page is linked from these existing pages:\n{context.strip()}"
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=[{
                    "type": "text",
                    "text": _DRAFT_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user}],
            )
        except Exception:
            # 네트워크/한도/인증 오류 시 결정론적 stub 초안으로 폴백
            return self._stub.draft(title, context)
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        return text or self._stub.draft(title, context)


def make_bookkeeper() -> Bookkeeper:
    """환경에 맞는 북키퍼를 고른다.

    ``ANTHROPIC_API_KEY`` 가 있으면 실제 LLM, 없으면 결정론적 stub.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return LLMBookkeeper()
        except Exception:
            return StubBookkeeper()
    return StubBookkeeper()
