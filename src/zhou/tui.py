from __future__ import annotations

from contextlib import contextmanager
from enum import Enum
import os
import shutil
import sys
import unicodedata
from typing import Iterable, Iterator

from .core.llm import TurnEvent
from .session import Skill
from .tools import ToolRegistry

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
BLUE = "\033[38;5;117m"
GREEN = "\033[38;5;48m"
PURPLE = "\033[38;5;141m"
GRAY = "\033[38;5;245m"
ANSI_PREFIX = "\033["
MAX_THINKING_PREVIEW_WIDTH = 88


class SkillPickerResult(str, Enum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class ToolScreenResult(str, Enum):
    CLOSED = "closed"


@contextmanager
def alternate_screen() -> Iterator[None]:
    if os.name == "nt":
        sys.stdout.write("\033[?1049h")
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        try:
            yield
        finally:
            sys.stdout.write("\033[?1049l")
            sys.stdout.flush()
    else:
        yield


def pick_skills(skills: list[Skill], active_names: Iterable[str]) -> tuple[SkillPickerResult, list[str]]:
    active_set = list(active_names)
    if os.name != "nt":
        return fallback_pick_skills(skills, active_set)

    import msvcrt

    selected = list(active_set)
    index = 0
    scroll = 0

    with alternate_screen():
        while True:
            visible_count = visible_skill_item_count(len(skills))
            scroll = clamp_scroll(index, scroll, len(skills), visible_count)
            render_skill_picker(skills, selected, index, scroll)
            key = msvcrt.getwch()

            if key in {"\r", "\n"}:
                return SkillPickerResult.CONFIRMED, selected
            if key == "\x1b":
                return SkillPickerResult.CANCELLED, list(active_set)

            if key in {"\x00", "\xe0"}:
                arrow = msvcrt.getwch()
                if arrow == "H" and skills:
                    index = max(0, index - 1)
                elif arrow == "P" and skills:
                    index = min(len(skills) - 1, index + 1)
                elif arrow == "I" and skills:
                    index = max(0, index - max(1, visible_count))
                elif arrow == "Q" and skills:
                    index = min(len(skills) - 1, index + max(1, visible_count))
                elif arrow == "M" and skills:
                    selected = ensure_selected(selected, skills[index].name)
                elif arrow == "K" and skills:
                    selected = ensure_unselected(selected, skills[index].name)

def render_skill_picker(skills: list[Skill], selected: list[str], index: int, scroll: int) -> None:
    terminal_width, terminal_height = get_terminal_dimensions()
    width, content_width, body_height = skills_layout_metrics(terminal_width, terminal_height)
    selected_set = set(selected)
    current_name = skills[index].name if skills else "none"
    selected_summary = "、".join(skill.name for skill in skills if skill.name in selected_set) or "无"

    header_lines = [
        f"{BOLD}{BLUE}Skills{RESET}",
        f"Active  {len(selected_set)} / {len(skills)}",
        f"Current {fit_plain_text(current_name, max(12, content_width - 10))}",
    ]

    body_lines: list[str] = []
    visible_rows = visible_skill_item_count(len(skills), body_height)
    compact_body_height = min(body_height, max(3, (visible_rows * 2) + 1 if skills else 1))
    if not skills:
        body_lines.append("当前项目下没有可用 skills。")
    else:
        visible_skills = skills[scroll:scroll + visible_rows]
        name_width = max(10, content_width - 16)
        desc_width = max(10, content_width - 6)
        for offset, skill in enumerate(visible_skills, start=scroll + 1):
            is_current = offset - 1 == index
            marker = ">" if is_current else " "
            checked = f"{GREEN}[●]{RESET}" if skill.name in selected_set else f"{GRAY}[ ]{RESET}"
            plain_name = fit_plain_text(skill.name, name_width)
            name = f"{GREEN}{plain_name}{RESET}" if skill.name in selected_set else plain_name
            desc = fit_plain_text(skill.description or "无描述", desc_width)
            body_lines.append(f"{marker} {offset}. {checked} {name}")
            body_lines.append(f"    {DIM}{GRAY}{desc}{RESET}")

    footer_lines = [
        build_range_label(scroll, visible_rows, len(skills)),
        f"Selected {len(selected_set)}  {fit_plain_text(selected_summary, max(12, content_width - 12))}",
        "↑/↓ move  PgUp/PgDn page  ← remove  → add",
        "Enter apply  Esc cancel",
    ]

    page = build_three_panel_page(
        header_lines,
        body_lines,
        footer_lines,
        width,
        content_width,
        compact_body_height,
    )
    paint_fullscreen(page)


def fallback_pick_skills(skills: list[Skill], active_names: list[str]) -> tuple[SkillPickerResult, list[str]]:
    print("\nSkills\n")
    if not skills:
        print("当前项目下没有可用 skills。\n")
        return SkillPickerResult.CANCELLED, active_names

    for idx, skill in enumerate(skills, start=1):
        marker = "[●]" if skill.name in active_names else "[ ]"
        print(f"{idx}. {marker} {skill.name}")
        print(f"   {skill.description or '无描述'}")

    raw = input("输入编号，使用逗号分隔；直接回车保留当前选择: ").strip()
    if not raw:
        return SkillPickerResult.CANCELLED, active_names

    indexes: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            indexes.append(int(part))

    selected = [skills[i - 1].name for i in indexes if 1 <= i <= len(skills)]
    return SkillPickerResult.CONFIRMED, selected


def draw_box(lines: list[str], width: int, content_width: int, min_height: int = 0) -> str:
    rendered = [box_line(line, content_width) for line in lines]
    while len(rendered) < min_height:
        rendered.append(box_line("", content_width))
    body = "\n".join(rendered)
    top = f"┌{'─' * content_width}┐"
    bottom = f"└{'─' * content_width}┘"
    return f"{top}\n{body}\n{bottom}"


def box_line(content: str, content_width: int) -> str:
    inner_width = max(0, content_width - 2)
    cropped = truncate_ansi_text(content, inner_width)
    visible_width = visual_width(strip_ansi(cropped))
    padding = max(0, inner_width - visible_width)
    return f"│{cropped}{' ' * padding}│"


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


def strip_ansi(text: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith(ANSI_PREFIX, i):
            end = text.find("m", i)
            if end == -1:
                break
            i = end + 1
            continue
        result.append(text[i])
        i += 1
    return "".join(result)


def truncate_ansi_text(text: str, max_width: int) -> str:
    if visual_width(strip_ansi(text)) <= max_width:
        return text

    plain_target = max_width - 3
    out: list[str] = []
    width = 0
    i = 0
    while i < len(text):
        if text.startswith(ANSI_PREFIX, i):
            end = text.find("m", i)
            if end == -1:
                break
            out.append(text[i:end + 1])
            i = end + 1
            continue

        ch = text[i]
        ch_width = char_width(ch)
        if width + ch_width > plain_target:
            break
        out.append(ch)
        width += ch_width
        i += 1

    out.append("...")
    if not "\033[0m" in "".join(out):
        out.append(RESET)
    return "".join(out)


def visual_width(text: str) -> int:
    return sum(char_width(ch) for ch in text if not unicodedata.combining(ch))


def char_width(ch: str) -> int:
    return 2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1


def ensure_selected(selected: list[str], name: str) -> list[str]:
    if name in selected:
        return selected
    return [*selected, name]


def ensure_unselected(selected: list[str], name: str) -> list[str]:
    return [item for item in selected if item != name]


def open_tools_screen(registry: ToolRegistry) -> ToolScreenResult:
    if os.name != "nt":
        return fallback_open_tools_screen(registry)

    import msvcrt

    groups = build_tool_groups(registry)
    scroll = 0
    with alternate_screen():
        while True:
            _, _, body_height = tools_layout_metrics()
            visible_count = visible_tool_group_count(len(groups), body_height)
            scroll = clamp_scroll(scroll, scroll, len(groups), visible_count)
            render_tools_screen(registry, scroll)
            key = msvcrt.getwch()
            if key == "\x1b":
                return ToolScreenResult.CLOSED
            if key in {"\x00", "\xe0"}:
                arrow = msvcrt.getwch()
                if arrow == "H" and groups:
                    scroll = max(0, scroll - 1)
                elif arrow == "P" and groups:
                    scroll = min(max(0, len(groups) - 1), scroll + 1)
                elif arrow == "I" and groups:
                    scroll = max(0, scroll - max(1, visible_count))
                elif arrow == "Q" and groups:
                    scroll = min(max(0, len(groups) - 1), scroll + max(1, visible_count))


def render_tools_screen(registry: ToolRegistry, scroll: int) -> None:
    terminal_width, terminal_height = get_terminal_dimensions()
    width, content_width, body_height = tools_layout_metrics(terminal_width, terminal_height)
    groups = build_tool_groups(registry)
    name_width = max(12, content_width - 20)

    header_lines = [
        f"{BOLD}{BLUE}Tools{RESET}",
        f"Total  {registry.discovered_count}    Enabled  {registry.enabled_count}",
        f"Ready  {registry.ready_count}    Failed   {registry.failed_count}",
    ]

    body_lines: list[str] = []
    visible_count = visible_tool_group_count(len(groups), body_height)
    compact_body_height = min(body_height, max(3, visible_count))
    if not groups:
        body_lines.append("当前没有可用工具组。")
    else:
        visible_groups = groups[scroll:scroll + visible_count]
        for idx, (label, count) in enumerate(visible_groups, start=scroll + 1):
            body_lines.append(f"{idx}. {fit_plain_text(label, name_width)}  {GRAY}{count} tools{RESET}")

    footer_lines = [
        build_range_label(scroll, visible_count, len(groups)),
        "↑/↓ scroll groups  PgUp/PgDn page",
        "Esc return",
    ]

    page = build_three_panel_page(
        header_lines,
        body_lines,
        footer_lines,
        width,
        content_width,
        compact_body_height,
    )
    paint_fullscreen(page)


def fallback_open_tools_screen(registry: ToolRegistry) -> ToolScreenResult:
    print("\nTools\n")
    print(f"Total: {registry.discovered_count}  Enabled: {registry.enabled_count}  Ready: {registry.ready_count}  Failed: {registry.failed_count}\n")
    groups = build_tool_groups(registry)
    if not groups:
        print("当前没有可用工具组。")
    else:
        for idx, (label, count) in enumerate(groups, start=1):
            print(f"{idx}. {label} ({count})")
    input("\n按回车返回对话界面: ")
    return ToolScreenResult.CLOSED


def get_terminal_dimensions() -> tuple[int, int]:
    size = shutil.get_terminal_size((110, 30))
    return size.columns, size.lines


def compute_page_width(terminal_width: int) -> int:
    return max(52, min(terminal_width - 4, 100))


def compute_body_height(terminal_height: int, header_rows: int, footer_rows: int) -> int:
    used_rows = (header_rows + 2) + (footer_rows + 2) + 4
    return max(3, terminal_height - used_rows)


def skills_layout_metrics(
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> tuple[int, int, int]:
    width_value, height_value = get_terminal_dimensions()
    width = compute_page_width(terminal_width if terminal_width is not None else width_value)
    content_width = width - 2
    body_height = compute_body_height(terminal_height if terminal_height is not None else height_value, 3, 4)
    return width, content_width, body_height


def tools_layout_metrics(
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> tuple[int, int, int]:
    width_value, height_value = get_terminal_dimensions()
    width = compute_page_width(terminal_width if terminal_width is not None else width_value)
    content_width = width - 2
    body_height = compute_body_height(terminal_height if terminal_height is not None else height_value, 3, 3)
    return width, content_width, body_height


def visible_skill_item_count(total: int, max_body_height: int | None = None) -> int:
    _, _, body_height = skills_layout_metrics() if max_body_height is None else (0, 0, max_body_height)
    capacity = max(1, body_height // 2)
    if total <= 0:
        return 1
    return max(1, min(capacity, total))


def visible_tool_group_count(total: int, max_body_height: int | None = None) -> int:
    _, _, body_height = tools_layout_metrics() if max_body_height is None else (0, 0, max_body_height)
    if total <= 0:
        return 1
    return max(1, min(body_height, max(3, total)))


def pad_ansi_line(line: str, target_width: int) -> str:
    visible = visual_width(strip_ansi(line))
    if visible >= target_width:
        return line
    return f"{line}{' ' * (target_width - visible)}"


def build_three_panel_page(
    header_lines: list[str],
    body_lines: list[str],
    footer_lines: list[str],
    width: int,
    content_width: int,
    body_height: int,
) -> str:
    header_box = draw_box(header_lines, width, content_width, min_height=len(header_lines))
    body_box = draw_box(body_lines, width, content_width, min_height=body_height)
    footer_box = draw_box(footer_lines, width, content_width, min_height=len(footer_lines))
    return "\n\n".join([header_box, body_box, footer_box])


def paint_fullscreen(content: str) -> None:
    terminal_width, terminal_height = get_terminal_dimensions()
    lines = content.splitlines()
    padded_lines = [pad_ansi_line(line, terminal_width) for line in lines]
    if len(padded_lines) < terminal_height:
        padded_lines.extend([" " * terminal_width] * (terminal_height - len(padded_lines)))
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("\n".join(padded_lines[:terminal_height]))
    sys.stdout.flush()


def clamp_scroll(index: int, scroll: int, total: int, visible_count: int) -> int:
    if total <= 0 or visible_count <= 0:
        return 0
    max_scroll = max(0, total - visible_count)
    scroll = max(0, min(scroll, max_scroll))
    if index < scroll:
        return index
    if index >= scroll + visible_count:
        return min(max_scroll, index - visible_count + 1)
    return scroll


def build_range_label(scroll: int, visible_count: int, total: int) -> str:
    if total <= 0:
        return "Showing 0-0 of 0"
    start = scroll + 1
    end = min(total, scroll + visible_count)
    return f"Showing {start}-{end} of {total}"


def build_tool_groups(registry: ToolRegistry) -> list[tuple[str, int]]:
    grouped = summarize_registry_tools(registry)
    groups = [(tool_group_label(source_id), count) for source_id, count in grouped.items()]
    groups.sort(key=lambda item: item[0])
    return groups


def render_thinking_summary(reasoning: str) -> None:
    normalized = reasoning.strip()
    if not normalized:
        return

    preview = build_thinking_preview(normalized)
    print()
    print(f"  {GRAY}> Show thinking{RESET}  {DIM}{GRAY}{preview}{RESET}")
    sys.stdout.flush()

    if os.name == "nt" and wait_for_arrow_down(0.9):
        render_expanded_thinking(normalized)


def build_thinking_preview(reasoning: str, max_width: int = MAX_THINKING_PREVIEW_WIDTH) -> str:
    lines = [line.strip() for line in reasoning.splitlines() if line.strip()]
    if not lines:
        return ""

    preview = lines[0]
    needs_ellipsis = len(lines) > 1 or visual_width(preview) > max_width
    if visual_width(preview) > max_width:
        preview = truncate_plain_text(preview, max_width - 3)
        needs_ellipsis = True

    if needs_ellipsis and not preview.endswith("..."):
        preview = f"{preview}..."
    return preview


def render_expanded_thinking(reasoning: str) -> None:
    print(f"  {GRAY}↓ Show thinking{RESET}")
    for line in reasoning.splitlines():
        stripped = line.strip()
        if stripped:
            print(f"    {DIM}{GRAY}{stripped}{RESET}")
        else:
            print()
    print()
    sys.stdout.flush()


def render_tool_event(name: str, arguments: str, result: str) -> None:
    print(f"  → tool {BLUE}{name}{RESET}({arguments})")
    summary = build_tool_result_preview(result)
    print(f"  ← result {DIM}{summary}{RESET}")
    print()
    sys.stdout.flush()


def render_tool_call_event(name: str, arguments: str) -> None:
    print(f"  → tool {BLUE}{name}{RESET}({arguments})")
    sys.stdout.flush()


def render_tool_result_event(result: str) -> None:
    summary = build_tool_result_preview(result)
    print(f"  ← result {DIM}{summary}{RESET}")
    print()
    sys.stdout.flush()


def render_reasoning_summary(reasoning: str) -> None:
    render_thinking_summary(reasoning)


def begin_reasoning_stream() -> None:
    print("> Show thinking  ", end="", flush=True)


def append_reasoning_delta(text: str) -> None:
    print(f"{DIM}{text}{RESET}", end="", flush=True)


def end_reasoning_stream() -> None:
    print()
    print()
    sys.stdout.flush()


def begin_answer_stream() -> None:
    return None


def append_answer_delta(text: str) -> None:
    print(text, end="", flush=True)


def end_answer_stream() -> None:
    print()
    print()
    sys.stdout.flush()


def build_tool_result_preview(result: str, max_width: int = MAX_THINKING_PREVIEW_WIDTH) -> str:
    lines = [line.strip() for line in result.splitlines() if line.strip()]
    if not lines:
        return "(empty)"

    preview = lines[0]
    needs_ellipsis = len(lines) > 1 or visual_width(preview) > max_width
    if visual_width(preview) > max_width:
        preview = truncate_plain_text(preview, max_width - 3)
        needs_ellipsis = True

    if needs_ellipsis and not preview.endswith("..."):
        preview = f"{preview}..."
    return preview


def wait_for_arrow_down(timeout_seconds: float) -> bool:
    if os.name != "nt":
        return False

    import msvcrt
    import time

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if not msvcrt.kbhit():
            time.sleep(0.02)
            continue

        key = msvcrt.getwch()
        if key in {"\x00", "\xe0"}:
            arrow = msvcrt.getwch()
            if arrow == "P":
                return True
        return False

    return False


def truncate_plain_text(text: str, max_width: int) -> str:
    if visual_width(text) <= max_width:
        return text

    out: list[str] = []
    width = 0
    for ch in text:
        ch_width = char_width(ch)
        if width + ch_width > max_width:
            break
        out.append(ch)
        width += ch_width
    return "".join(out)


def fit_plain_text(text: str, max_width: int) -> str:
    if max_width <= 0:
        return ""
    if visual_width(text) <= max_width:
        return text
    if max_width <= 3:
        return "." * max_width
    return f"{truncate_plain_text(text, max_width - 3)}..."


def summarize_registry_tools(registry: ToolRegistry) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tool in registry.tools:
        counts[tool.source_id] = counts.get(tool.source_id, 0) + 1
    return counts


def tool_group_label(source_id: str | None) -> str:
    if source_id == "filesystem":
        return "file"
    if source_id == "git":
        return "git"
    return source_id or "none"


def tool_status_color(status: str) -> str:
    if status == "ready":
        return GREEN
    if status == "failed":
        return "\033[38;5;203m"
    if status == "disabled":
        return GRAY
    return BLUE


def render_stream_event(event: TurnEvent, state: dict[str, object]) -> None:
    """Render a single streaming TurnEvent onto the terminal.

    Moved from ``main.py`` — this is pure TUI rendering.
    """
    if event.type == "reasoning_delta":
        state["reasoning_parts"].append(event.text)
        return
    if event.type == "reasoning_done":
        reasoning_text = "".join(state["reasoning_parts"]).strip()
        state["reasoning_text"] = reasoning_text
        state["reasoning_parts"].clear()
        if reasoning_text:
            render_reasoning_summary(reasoning_text)
        return
    if event.type == "reasoning_summary":
        state["reasoning_summary"] = event.text
        return
    if event.type == "tool_call":
        state["tool_calls"].append({"name": event.name, "arguments": event.arguments})
        render_tool_call_event(event.name, event.arguments)
        return
    if event.type == "tool_result":
        render_tool_result_event(event.result)
        return
    if event.type == "answer_delta":
        if not state["answer_open"]:
            begin_answer_stream()
            state["answer_open"] = True
        state["answer_parts"].append(event.text)
        append_answer_delta(event.text)
        return
    if event.type == "answer_done" and state["answer_open"]:
        end_answer_stream()
        state["answer_open"] = False


def finish_open_streams(state: dict[str, object]) -> None:
    """Ensure any open answer stream is properly closed."""
    if state["answer_open"]:
        end_answer_stream()
        state["answer_open"] = False
