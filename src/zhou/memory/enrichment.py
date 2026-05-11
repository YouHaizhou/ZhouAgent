"""Turn enrichment — heuristic derivation of tags, memory candidates, and folder promotions.

These are pure functions that operate on turn text and tool-call data.
They do not depend on SessionState or any I/O.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from ..session import ToolCallRecord, TurnRecord

# ---------------------------------------------------------------------------
# Patterns shared by the heuristic functions
# ---------------------------------------------------------------------------

PATH_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/][^\s'\"]+|(?:\.?\.?(?:[\\/][^\s'\"]+)+))")
WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_.\-/]{2,}")
MEMORY_PATTERNS = (
    re.compile(r"([^。！？\n]{0,40}(?:路径|目录|配置|端口|模型|技能|记忆|会话|规则|约定)[^。！？\n]{0,60})"),
    re.compile(r"([^。！？\n]{0,40}(?:需要|必须|应该|优先|说明|表示|位于|使用|采用)[^。！？\n]{0,60})"),
)
PROCEDURAL_HINTS = ("先", "再", "最后", "优先", "然后", "步骤", "排查", "检查")
STOPWORDS = {"zhou", "agent", "session", "memory", "tool", "tools", "error", "debug", "issue", "json", "user", "assistant"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_string_list(values: Iterable[str]) -> list[str]:
    """Deduplicate strings case-insensitively while preserving first-occurrence order."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def clean_candidate_text(text: str, max_length: int = 120) -> str:
    """Collapse whitespace and trim to *max_length* chars."""
    compact = " ".join(str(text).split()).strip(" ，,。；;:-")
    if not compact:
        return ""
    return compact if len(compact) <= max_length else compact[: max_length - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Derivation functions
# ---------------------------------------------------------------------------

def derive_turn_tags(
    user_input: str,
    assistant_text: str,
    reasoning_summary: str,
    tool_calls: Iterable[ToolCallRecord],
) -> list[str]:
    """Extract lightweight tags from turn text (paths, keywords, tool names)."""
    text = "\n".join([user_input, assistant_text, reasoning_summary])
    tags: list[str] = []

    for match in PATH_PATTERN.findall(text):
        parts = [p for p in match.replace("\\", "/").split("/") if p not in {".", "..", ""}]
        if parts:
            tags.append(parts[-1].lower())

    for match in WORD_PATTERN.findall(text):
        word = match.strip("._-/").lower()
        if len(word) >= 3 and word not in STOPWORDS:
            tags.append(word)

    tags.extend(call.name.lower() for call in tool_calls if call.name.strip())
    return normalize_string_list(tags)[:8]


def derive_memory_candidates(
    user_input: str,
    assistant_text: str,
    reasoning_summary: str,
    tool_calls: Iterable[ToolCallRecord],
) -> list[str]:
    """Heuristically pick sentences that may be worth persisting as memory."""
    text = "\n".join(part for part in (reasoning_summary, assistant_text) if part.strip())
    candidates: list[str] = []

    for pattern in MEMORY_PATTERNS:
        for match in pattern.findall(text):
            cleaned = clean_candidate_text(match)
            if cleaned:
                candidates.append(cleaned)

    for match in PATH_PATTERN.findall(text):
        candidates.append("本轮涉及路径：" + match.replace("\\", "/"))

    tool_names = ", ".join(call.name for call in tool_calls if call.name.strip())
    if tool_names:
        candidates.append(f"本轮使用的工具链包括：{tool_names}")

    goal = clean_candidate_text(user_input)
    if goal:
        candidates.append(f"用户当前关注点：{goal}")

    return normalize_string_list(candidates)[:6]


def derive_folder_promotions(turn: TurnRecord) -> tuple[list[str], list[str]]:
    """Derive semantic and procedural memory candidates for folder-level promotion."""
    semantic = normalize_string_list(turn.memory_candidates)[:3]
    procedural: list[str] = []

    if turn.reasoning_summary and any(
        token in turn.reasoning_summary for token in PROCEDURAL_HINTS
    ):
        procedural.append(
            f"处理这类问题时，可采用以下顺序：{turn.reasoning_summary}"
        )
    else:
        tool_names = " -> ".join(
            call.name for call in turn.tool_calls if call.name.strip()
        )
        if tool_names:
            procedural.append(f"处理这类问题时，常用工具顺序为：{tool_names}")

    return semantic, normalize_string_list(procedural)[:2]
