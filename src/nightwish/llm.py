"""Optional real-LLM draft backend (Anthropic SDK).

Wired into the MVP wiki via :func:`nightwish.mvp.set_ai`. Active only when
``NIGHTWISH_ENABLE_LLM`` is truthy **and** ``ANTHROPIC_API_KEY`` is set **and**
the ``anthropic`` package is installed (``pip install -e ".[llm]"``); otherwise
the service keeps using the offline stub. Network access to api.anthropic.com is
required at call time.

Follows the Anthropic SDK best practices: the official SDK, the current default
model (Opus 4.8), adaptive thinking, streaming (so long drafts don't hit the
request timeout), and prompt caching on the stable system prompt.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

#: Override with NIGHTWISH_LLM_MODEL; defaults to the current flagship.
DEFAULT_MODEL = os.environ.get("NIGHTWISH_LLM_MODEL", "claude-opus-4-8")

WIKI_SYSTEM = (
    "당신은 사용자들이 공유하는 '업무 지식' 위키의 작성 도우미입니다. "
    "주어진 제목과 요청에 대해, 한국어 **마크다운** 문서 초안을 작성하세요.\n"
    "규칙:\n"
    "- 제목을 '# 제목'으로 시작하고, 개요 → 핵심 내용 → (가능하면) 근거 순으로 구성.\n"
    "- 관련 개념은 [[다른 문서 제목]] 형태의 위키링크로 연결하세요. 이 링크가 문서끼리의 "
    "관계망과 평가(허브/권위)를 만듭니다.\n"
    "- 사실에 근거해 간결하게. 모르면 모른다고 표시하고 사람이 채울 자리를 남기세요.\n"
    "- 군더더기 인사말 없이 문서 본문만 출력하세요."
)


def claude_draft(title: str, prompt: str, *, model: str = DEFAULT_MODEL) -> str:
    """Draft a wiki page with Claude. Returns markdown text."""
    import anthropic  # lazy — only needed when the backend is active

    client = anthropic.Anthropic()
    ask = prompt.strip() or f"'{title}' 문서를 작성해줘."
    user = (
        f"문서 제목: {title}\n\n요청: {ask}\n\n"
        "이 제목에 맞는 위키 문서 본문을 마크다운으로 작성해줘."
    )
    with client.messages.stream(
        model=model,
        max_tokens=4096,
        thinking={"type": "adaptive"},
        system=[
            {
                "type": "text",
                "text": WIKI_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user}],
    ) as stream:
        final = stream.get_final_message()
    return "".join(b.text for b in final.content if b.type == "text").strip()


def make_draft_fn() -> Optional[Callable[[str, str], str]]:
    """Return the Claude-backed draft fn if enabled+available, else ``None``."""
    if os.environ.get("NIGHTWISH_ENABLE_LLM", "").lower() not in ("1", "true", "yes"):
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic  # noqa: F401
    except Exception:
        return None
    return claude_draft
