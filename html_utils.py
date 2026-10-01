"""
html_utils.py
-------------
MVG's message descriptions are HTML (<p>, <strong>, <ul>/<li>, ...), not
plain text. This converts that HTML into clean text with light Discord
markdown (bold, bullet lists with indentation for nesting) instead of
dumping raw tags into the embed.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag


def _inline_text(node: Tag) -> str:
    """Render a tag's inline content, turning <strong>/<b> into **bold**."""
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
        elif isinstance(child, Tag):
            if child.name in ("strong", "b"):
                raw = _inline_text(child)
                core = raw.strip()
                if core:
                    # Discord only renders **bold** correctly without
                    # whitespace touching the asterisks, so any leading/
                    # trailing space from the source HTML is moved
                    # outside the markers instead of being dropped.
                    lead = raw[: len(raw) - len(raw.lstrip())]
                    trail = raw[len(raw.rstrip()):]
                    parts.append(f"{lead}**{core}**{trail}")
            elif child.name == "br":
                parts.append("\n")
            elif child.name == "ul":
                # Nested list inside inline content: leave it out here, the
                # caller (render_list) handles nested <ul> separately.
                continue
            else:
                parts.append(_inline_text(child))
    return "".join(parts)


def _render_list(ul_tag: Tag, level: int = 0) -> list[str]:
    lines: list[str] = []
    for li in ul_tag.find_all("li", recursive=False):
        nested_uls = li.find_all("ul", recursive=False)

        # Get a copy of this <li> with nested <ul>s removed, so we can run
        # the normal inline renderer (which correctly handles <strong>/<b>)
        # on just this item's own text.
        li_copy = BeautifulSoup(str(li), "html.parser").find("li")
        for ul in li_copy.find_all("ul"):
            ul.decompose()
        text = re.sub(r"\s+", " ", _inline_text(li_copy)).strip()

        if text:
            lines.append("  " * level + f"- {text}")

        for nested_ul in nested_uls:
            lines.extend(_render_list(nested_ul, level + 1))

    return lines


def html_to_discord_text(html: str) -> str:
    """
    Convert an HTML snippet (as returned by MVG for message descriptions)
    into text suitable for a Discord embed description: bold markdown,
    indented bullet lists, blank lines between paragraphs. Falls back to
    a plain-text strip if the input doesn't look like HTML at all.
    """
    if not html:
        return ""
    if "<" not in html:
        return html.strip()

    soup = BeautifulSoup(html, "html.parser")
    blocks: list[str] = []

    for node in soup.children:
        if isinstance(node, Tag):
            if node.name == "p":
                text = _inline_text(node).strip()
                if text:
                    blocks.append(text)
            elif node.name == "ul":
                lines = _render_list(node)
                if lines:
                    blocks.append("\n".join(lines))
            else:
                text = node.get_text(" ", strip=True)
                if text:
                    blocks.append(text)
        elif isinstance(node, NavigableString):
            text = str(node).strip()
            if text:
                blocks.append(text)

    result = "\n\n".join(blocks)
    result = re.sub(r"[ \t]+", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()
