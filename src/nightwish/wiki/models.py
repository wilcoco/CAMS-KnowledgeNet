"""위키 도메인 모델 — 사용자와 페이지."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class User:
    id: str
    display_name: str


@dataclass
class WikiPage:
    """마크다운 본문 + LLM이 유지하는 메타(요약·링크).

    ``body`` 는 사람이 쓰는 원천(카파시의 raw + obsidian 노트). ``summary`` 와
    ``links`` 는 LLM 북키핑이 채운다(카파시 wiki 층).
    """

    slug: str
    title: str
    body: str
    author_id: str
    created_at: int
    updated_at: int
    shared: bool = False
    summary: str = ""
    links: list[str] = field(default_factory=list)  # 이 페이지가 링크한 슬러그들

    def touch(self, clock: int) -> None:
        self.updated_at = clock
