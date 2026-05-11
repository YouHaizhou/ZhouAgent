from __future__ import annotations

from pathlib import Path

from .manager import MemoryManager, MemoryKind, MemoryScope, format_memory_context, normalize_cwd
from ..session import SessionState, load_turn_records


def handle_memory_command(command_text: str, session: SessionState, memory: MemoryManager) -> bool:
    normalized = command_text.strip()
    if not normalized.startswith("/memory"):
        return False

    parts = normalized.split(maxsplit=2)
    subcommand = parts[1].lower() if len(parts) >= 2 else "help"
    argument = parts[2].strip() if len(parts) >= 3 else ""

    if subcommand in {"help", "?"}:
        render_memory_help()
        return True
    if subcommand == "turns":
        render_turns(session.turns_path(), limit=4)
        return True
    if subcommand == "session":
        render_scope_memory(memory, scope=MemoryScope.SESSION, cwd=str(session.cwd), session_id=session.session_id, query=argument, limit=4)
        return True
    if subcommand == "folder":
        render_scope_memory(memory, scope=MemoryScope.FOLDER, cwd=str(session.cwd), session_id=session.session_id, query=argument, limit=4)
        return True
    if subcommand == "global":
        query = argument or "全局记忆"
        render_scope_memory(memory, scope=MemoryScope.GLOBAL, cwd=str(session.cwd), session_id=session.session_id, query=query)
        return True
    if subcommand == "search":
        query = argument or "当前请求"
        render_search(memory, cwd=str(session.cwd), session_id=session.session_id, query=query)
        return True

    print("未知 /memory 子命令，输入 /memory help 查看可用命令。")
    return True


def render_memory_help() -> None:
    print("\nMemory Commands\n")
    print("  /memory help               查看帮助")
    print("  /memory turns              查看当前 session 最近 4 条结构化 turns")
    print("  /memory session [query]    不带参数查看最近 4 条 session memory；带参数按 query 检索")
    print("  /memory folder [query]     不带参数查看最近 4 条 folder memory；带参数按 query 检索")
    print("  /memory global [query]     查看 global memory 命中")
    print("  /memory search [query]     查看三层 memory 检索结果")
    print()


def render_turns(turns_path: Path, limit: int = 4) -> None:
    turns = load_turn_records(turns_path)
    print("\nSession Turns\n")
    if not turns:
        print("  当前 session 暂无 turns。\n")
        return

    latest_turns = turns[-limit:]
    start_index = len(turns) - len(latest_turns) + 1
    for offset, turn in enumerate(latest_turns, start=start_index):
        print(f"  [{offset}] {turn.timestamp}")
        print(f"    user: {shorten(turn.user, 120)}")
        print(f"    assistant: {shorten(turn.assistant, 120)}")
        if turn.reasoning_summary:
            print(f"    reasoning_summary: {shorten(turn.reasoning_summary, 160)}")
        if turn.tool_calls:
            tools = ", ".join(call.name for call in turn.tool_calls if call.name.strip())
            print(f"    tool_calls: {tools}")
        if turn.tags:
            print(f"    tags: {', '.join(turn.tags)}")
        if turn.memory_candidates:
            print("    memory_candidates:")
            for candidate in turn.memory_candidates:
                print(f"      - {shorten(candidate, 160)}")
        print()


def render_scope_memory(memory: MemoryManager, *, scope: MemoryScope, cwd: str, session_id: str, query: str, limit: int = 4) -> None:
    normalized_cwd = normalize_cwd(cwd) or cwd
    if scope == MemoryScope.SESSION:
        result = memory.recent_memory(scope=scope, cwd=normalized_cwd, session_id=session_id, kind=MemoryKind.SHORT_TERM, limit=limit) if not query else memory.search_memory(query, scope=scope, cwd=normalized_cwd, session_id=session_id, kind=MemoryKind.SHORT_TERM, limit=limit)
        title = "Session Memory"
    elif scope == MemoryScope.FOLDER:
        result = memory.recent_memory(scope=scope, cwd=normalized_cwd, kind=MemoryKind.LONG_TERM, limit=limit) if not query else memory.search_memory(query, scope=scope, cwd=normalized_cwd, kind=MemoryKind.LONG_TERM, limit=limit)
        title = "Folder Memory"
    else:
        result = memory.search_memory(query, scope=scope, kind=None, limit=limit)
        title = "Global Memory"

    print(f"\n{title}\n")
    if result.is_empty():
        print("  无命中。\n")
        return

    for index, hit in enumerate(result.hits, start=1):
        memory_key = str(hit.record.metadata.get("memory_key") or "").strip()
        revision = str(hit.record.metadata.get("revision") or "").strip()
        extra = f" key={memory_key} rev={revision}" if memory_key else ""
        print(f"  [{index}] score={hit.score:.3f} class={hit.record.memory_class.value} kind={hit.record.kind.value}{extra}")
        print(f"      {shorten(hit.record.content, 220)}")
    print()


def render_search(memory: MemoryManager, *, cwd: str, session_id: str, query: str) -> None:
    results = memory.search_all_scopes(query, cwd=cwd, session_id=session_id)
    rendered = format_memory_context(results)
    print("\nMemory Search\n")
    print(rendered or "  无命中。")
    print()


def shorten(text: str, max_length: int) -> str:
    compact = " ".join(str(text).split()).strip()
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 1].rstrip() + "…"
