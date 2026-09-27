"""Render untrusted answer Markdown without raw HTML or remote images."""
from html import escape
import re

from markdown_it import MarkdownIt


_md = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("table").disable("image")


def _text(tokens, idx, options, env):
    # Wiki titles stay data; the browser attaches its existing navigation handler.
    text = tokens[idx].content
    parts, start = [], 0
    for match in re.finditer(r"\[\[([^\]\n]+)\]\]", text):
        parts.append(escape(text[start:match.start()]))
        title = escape(match[1], quote=True)
        parts.append(f'<a class="wl" data-link="{title}">{title}</a>')
        start = match.end()
    parts.append(escape(text[start:]))
    return "".join(parts)


_md.renderer.rules["text"] = _text


def render_answer(text: str) -> str:
    tokens = _md.parse(text or "")
    for token in tokens:
        for child in token.children or []:
            if child.type == "link_open":
                child.attrSet("target", "_blank")
                child.attrSet("rel", "noopener noreferrer")
    return _md.renderer.render(tokens, _md.options, {})
