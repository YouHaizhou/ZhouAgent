from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from zhou.core.llm import TurnEvent
from zhou.main import _handle_turn
from zhou.memory.manager import MemoryClass, MemoryKind, MemoryRecord, MemoryScope, MemorySearchHit, MemorySearchResult
from zhou.memory.model import EnrichedTurnResult, MemoryDecisionDraft, MemoryJobResult, MemoryModelOutput
from zhou.session import SessionState, TurnRecord, build_turn_record
from zhou.tools import ToolDescriptor, ToolRegistry


class FakeLlmClient:
    def __init__(self, events: list[TurnEvent]) -> None:
        self.events = events
        self.calls: list[dict[str, Any]] = []

    def respond_turn(self, system_prompt: str, messages: list[dict[str, object]], tools: list[dict[str, object]], tool_executor: Any = None):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": messages,
                "tools": tools,
                "tool_executor": tool_executor,
            }
        )
        for event in self.events:
            yield event


class FakeArchiveWriter:
    def __init__(self) -> None:
        self.turns: list[tuple[Path, TurnRecord]] = []

    def append_turn(self, *, cwd: Path, turn: TurnRecord) -> None:
        self.turns.append((cwd, turn))


class FakeMemoryManager:
    def __init__(self, session_hits: list[MemorySearchHit] | None = None) -> None:
        self.session_hits = session_hits or []
        self.search_all_calls: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.writes: list[MemoryRecord] = []
        self.versioned_writes: list[tuple[MemoryRecord, str, int]] = []
        self.revision_counter = 0
        self.settings = type("Settings", (), {"user_id": "test-user", "agent_id": "test-agent"})()

    def search_all_scopes(self, query: str, *, cwd: str, session_id: str, limit_per_scope: int = 4) -> dict[str, MemorySearchResult]:
        self.search_all_calls.append({"query": query, "cwd": cwd, "session_id": session_id, "limit_per_scope": limit_per_scope})
        return {
            MemoryScope.SESSION.value: MemorySearchResult(hits=self.session_hits[:limit_per_scope]),
            MemoryScope.FOLDER.value: MemorySearchResult(),
            MemoryScope.GLOBAL.value: MemorySearchResult(),
        }

    def search_memory(self, query: str, **kwargs: Any) -> MemorySearchResult:
        self.search_calls.append({"query": query, **kwargs})
        if kwargs.get("scope") == MemoryScope.SESSION:
            return MemorySearchResult(hits=self.session_hits[: kwargs.get("limit", 8)])
        return MemorySearchResult()

    def write_memory(self, record: MemoryRecord) -> None:
        self.writes.append(record)

    def write_versioned_memory(self, record: MemoryRecord, *, memory_key: str, revision: int) -> None:
        self.versioned_writes.append((record, memory_key, revision))

    def next_memory_revision(self, *, memory_key: str, cwd: str | None, session_id: str | None, scope: MemoryScope, kind: MemoryKind) -> int:
        self.revision_counter += 1
        return self.revision_counter

    def write_session_turn(self, *, cwd: str, turn: TurnRecord) -> None:
        self.writes.append(
            MemoryRecord(
                content=turn.assistant,
                scope=MemoryScope.SESSION,
                kind=MemoryKind.SHORT_TERM,
                memory_class=MemoryClass.EPISODIC,
                cwd=cwd,
                session_id=turn.session_id,
            )
        )

    def write_global_knowledge(self, *, content: str, source: str = "knowledge_base") -> None:
        self.writes.append(
            MemoryRecord(
                content=content,
                scope=MemoryScope.GLOBAL,
                kind=MemoryKind.KNOWLEDGE,
                memory_class=MemoryClass.SEMANTIC,
                source=source,
            )
        )


class FakeWorker:
    def __init__(self, *, submit_behavior: str = "record_only") -> None:
        self.submit_behavior = submit_behavior
        self.started = False
        self.shutdown_called = False
        self.jobs: list[Any] = []

    def start(self) -> None:
        self.started = True

    def submit(self, job: Any) -> bool:
        self.jobs.append(job)
        if self.submit_behavior == "callback_immediately":
            output = MemoryModelOutput(
                reasoning_summary="补充后的摘要",
                tags=["session", "test"],
                memory_candidates=["用户询问 session 作用"],
                session_episodic=MemoryDecisionDraft(provided=True),
                session_semantic=MemoryDecisionDraft(
                    decision="insert",
                    target_memory_key="session-fact",
                    content="当前测试用例验证了 session 主流程可被隔离执行。",
                    importance=0.8,
                    reason="沉淀稳定测试结论",
                    provided=True,
                ),
                folder_procedural=MemoryDecisionDraft(
                    decision="insert",
                    target_memory_key="flow-procedure",
                    content="先构造 fake 依赖，再执行单轮主流程，最后验证 turn 持久化与异步回写。",
                    importance=0.7,
                    reason="沉淀可复用测试流程",
                    provided=True,
                ),
            )
            enriched_turn = build_turn_record(
                session_id=job.session_id,
                user_input=job.turn.user,
                assistant_text=job.turn.assistant,
                reasoning_summary=output.reasoning_summary or job.turn.reasoning_summary,
                tool_calls=[{"name": call.name, "arguments": call.arguments} for call in job.turn.tool_calls],
                tags=output.tags or job.turn.tags,
                memory_candidates=output.memory_candidates or job.turn.memory_candidates,
                auto_enrich=False,
            )
            enriched_turn.timestamp = job.turn.timestamp
            enriched = EnrichedTurnResult(turn=enriched_turn, output=output)
            status = job.callback(enriched)
            if callable(job.on_complete):
                job.on_complete(MemoryJobResult(status=status, debug="fake-worker"))
        return True

    def shutdown(self) -> None:
        self.shutdown_called = True


@dataclass
class SessionBundle:
    tempdir: TemporaryDirectory[str]
    root: Path
    session: SessionState


def build_session() -> SessionBundle:
    tempdir = TemporaryDirectory()
    root = Path(tempdir.name)
    session = SessionState(cwd=root)
    session.ensure_storage()
    return SessionBundle(tempdir=tempdir, root=root, session=session)


def build_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        tools=[
            ToolDescriptor(
                source_id="filesystem",
                name="read_file",
                qualified_name="filesystem.read_file",
                description="Read one file",
                input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            )
        ]
    )


def test_main_flow_without_tool_still_persists_turn_and_submits_memory_job() -> None:
    bundle = build_session()
    try:
        bundle.session.tool_registry = ToolRegistry()
        client = FakeLlmClient(
            [
                TurnEvent(type="reasoning_delta", text="分析用户问题"),
                TurnEvent(type="reasoning_done"),
                TurnEvent(type="reasoning_summary", text="直接回答 session 的职责"),
                TurnEvent(type="answer_delta", text="Session 是当前对话的状态容器。"),
                TurnEvent(type="answer_done"),
            ]
        )
        memory = FakeMemoryManager(
            session_hits=[
                MemorySearchHit(
                    record=MemoryRecord(
                        content="之前的 session 相关知识",
                        scope=MemoryScope.SESSION,
                        kind=MemoryKind.SHORT_TERM,
                        memory_class=MemoryClass.SEMANTIC,
                        cwd=str(bundle.root),
                        session_id=bundle.session.session_id,
                    ),
                    score=0.9,
                )
            ]
        )
        archive = FakeArchiveWriter()
        worker = FakeWorker()

        _handle_turn(
            "请解释一下 session 的作用",
            session=bundle.session,
            client=client,
            memory=memory,
            archive_writer=archive,
            worker=worker,
        )

        turns = bundle.session.message_history
        stored_turns = bundle.session.turns_path().read_text(encoding="utf-8")

        assert worker.started is False
        assert len(memory.search_all_calls) == 1
        assert len(worker.jobs) == 1
        assert len(archive.turns) == 1
        assert len(turns) == 2
        assert "Session 是当前对话的状态容器" in stored_turns
        assert client.calls[0]["messages"][-1]["role"] == "user"
    finally:
        bundle.tempdir.cleanup()


def test_main_flow_with_tool_call_records_tool_and_final_answer() -> None:
    bundle = build_session()
    try:
        bundle.session.tool_registry = build_tool_registry()
        client = FakeLlmClient(
            [
                TurnEvent(type="tool_call", name="filesystem.read_file", arguments='{"path":"Agent.md"}'),
                TurnEvent(type="tool_result", result="Agent.md content"),
                TurnEvent(type="reasoning_summary", text="先读文件再总结"),
                TurnEvent(type="answer_delta", text="我已经读取 Agent.md，并提炼了重点。"),
                TurnEvent(type="answer_done"),
            ]
        )
        memory = FakeMemoryManager()
        archive = FakeArchiveWriter()
        worker = FakeWorker()

        _handle_turn(
            "读取 Agent.md 并总结",
            session=bundle.session,
            client=client,
            memory=memory,
            archive_writer=archive,
            worker=worker,
        )

        turns = bundle.session.turns_path().read_text(encoding="utf-8")
        assert "filesystem.read_file" in turns
        assert "我已经读取 Agent.md" in turns
        assert len(worker.jobs) == 1
    finally:
        bundle.tempdir.cleanup()


def test_async_callback_path_replaces_turn_and_writes_memory() -> None:
    bundle = build_session()
    try:
        bundle.session.tool_registry = ToolRegistry()
        client = FakeLlmClient(
            [
                TurnEvent(type="reasoning_summary", text="初始摘要"),
                TurnEvent(type="answer_delta", text="这是一条会触发回写的回答。"),
                TurnEvent(type="answer_done"),
            ]
        )
        memory = FakeMemoryManager()
        archive = FakeArchiveWriter()
        worker = FakeWorker(submit_behavior="callback_immediately")

        _handle_turn(
            "解释 session 并沉淀记忆",
            session=bundle.session,
            client=client,
            memory=memory,
            archive_writer=archive,
            worker=worker,
        )

        turns = bundle.session.turns_path().read_text(encoding="utf-8")
        assert "补充后的摘要" in turns
        assert len(memory.versioned_writes) >= 1
        assert any(record.scope == MemoryScope.FOLDER for record, _, _ in memory.versioned_writes)
    finally:
        bundle.tempdir.cleanup()


def test_isolated_session_starts_without_old_message_history() -> None:
    first = build_session()
    second = build_session()
    try:
        first.session.append_assistant_turn("旧问题", "旧回答")
        assert len(first.session.message_history) == 2
        assert second.session.message_history == []
    finally:
        first.tempdir.cleanup()
        second.tempdir.cleanup()
