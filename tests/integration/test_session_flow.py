from __future__ import annotations

from typing import Any

import pytest
import zhou.main as main_module
from zhou.core.llm import TurnEvent
from zhou.main import _handle_turn
from zhou.session import SessionState, load_turn_records

from test_main_flow import FakeArchiveWriter, FakeLlmClient, FakeMemoryManager, FakeWorker, build_session


@pytest.fixture(autouse=True)
def disable_real_tool_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "refresh_tools", lambda session: None)


class RecordingLlmClient(FakeLlmClient):
    @property
    def last_messages(self) -> list[dict[str, object]]:
        return self.calls[-1]["messages"]


class TurnMutatingWorker(FakeWorker):
    def submit(self, job: Any) -> bool:
        self.jobs.append(job)
        if self.submit_behavior == "callback_immediately":
            enriched_turn = job.turn
            enriched_turn.assistant = f"{job.turn.assistant} [enriched]"
            enriched_turn.reasoning_summary = "异步回写后的摘要"
            enriched_turn.tags = ["async", "session"]
            enriched_turn.memory_candidates = ["异步回写后的候选"]
            status = job.callback(type("Enriched", (), {"turn": enriched_turn, "output": type("Output", (), {
                "session_episodic": type("Draft", (), {"decision": "skip", "content": "", "target_memory_key": "", "importance": 0.0, "reason": "", "provided": True})(),
                "session_semantic": type("Draft", (), {"decision": "skip", "content": "", "target_memory_key": "", "importance": 0.0, "reason": "", "provided": True})(),
                "folder_procedural": type("Draft", (), {"decision": "skip", "content": "", "target_memory_key": "", "importance": 0.0, "reason": "", "provided": True})(),
            })()})())
            if callable(job.on_complete):
                job.on_complete(type("Result", (), {"status": status, "debug": "mutating-worker"})())
        return True


def test_same_session_should_carry_previous_history_into_next_turn() -> None:
    bundle = build_session()
    try:
        bundle.session.tool_registry = bundle.session.tool_registry.__class__()
        first_client = RecordingLlmClient(
            [
                TurnEvent(type="reasoning_summary", text="第一轮摘要"),
                TurnEvent(type="answer_delta", text="第一轮回答"),
                TurnEvent(type="answer_done"),
            ]
        )
        second_client = RecordingLlmClient(
            [
                TurnEvent(type="reasoning_summary", text="第二轮摘要"),
                TurnEvent(type="answer_delta", text="第二轮回答"),
                TurnEvent(type="answer_done"),
            ]
        )
        memory = FakeMemoryManager()
        archive = FakeArchiveWriter()
        worker = FakeWorker()

        _handle_turn(
            "第一轮问题",
            session=bundle.session,
            client=first_client,
            memory=memory,
            archive_writer=archive,
            worker=worker,
        )
        _handle_turn(
            "第二轮问题",
            session=bundle.session,
            client=second_client,
            memory=memory,
            archive_writer=archive,
            worker=worker,
        )

        messages = second_client.last_messages
        assert [item["role"] for item in messages[-3:]] == ["user", "assistant", "user"]
        assert messages[-3]["content"] == "第一轮问题"
        assert messages[-2]["content"] == "第一轮回答"
        assert messages[-1]["content"] == "第二轮问题"
    finally:
        bundle.tempdir.cleanup()


def test_new_session_should_not_leak_old_history() -> None:
    first = build_session()
    second = build_session()
    try:
        first.session.tool_registry = first.session.tool_registry.__class__()
        second.session.tool_registry = second.session.tool_registry.__class__()
        first_client = RecordingLlmClient(
            [
                TurnEvent(type="reasoning_summary", text="第一轮摘要"),
                TurnEvent(type="answer_delta", text="只属于旧 session 的回答"),
                TurnEvent(type="answer_done"),
            ]
        )
        second_client = RecordingLlmClient(
            [
                TurnEvent(type="reasoning_summary", text="新 session 摘要"),
                TurnEvent(type="answer_delta", text="新 session 回答"),
                TurnEvent(type="answer_done"),
            ]
        )
        archive = FakeArchiveWriter()
        worker = FakeWorker()

        _handle_turn(
            "旧 session 问题",
            session=first.session,
            client=first_client,
            memory=FakeMemoryManager(),
            archive_writer=archive,
            worker=worker,
        )
        _handle_turn(
            "新 session 问题",
            session=second.session,
            client=second_client,
            memory=FakeMemoryManager(),
            archive_writer=archive,
            worker=worker,
        )

        messages = second_client.last_messages
        contents = [str(item.get("content", "")) for item in messages]
        assert "旧 session 问题" not in contents
        assert "只属于旧 session 的回答" not in contents
        assert messages[-1]["content"] == "新 session 问题"
        assert second.session.session_id != first.session.session_id
        assert second.session.message_history == [{"role": "user", "content": "新 session 问题"}, {"role": "assistant", "content": "新 session 回答"}]
    finally:
        first.tempdir.cleanup()
        second.tempdir.cleanup()


def test_enriched_turn_should_replace_persisted_record_and_be_visible_after_reload() -> None:
    bundle = build_session()
    try:
        bundle.session.tool_registry = bundle.session.tool_registry.__class__()
        first_client = RecordingLlmClient(
            [
                TurnEvent(type="reasoning_summary", text="原始摘要"),
                TurnEvent(type="answer_delta", text="原始回答"),
                TurnEvent(type="answer_done"),
            ]
        )
        second_client = RecordingLlmClient(
            [
                TurnEvent(type="reasoning_summary", text="第二轮摘要"),
                TurnEvent(type="answer_delta", text="第二轮回答"),
                TurnEvent(type="answer_done"),
            ]
        )
        archive = FakeArchiveWriter()
        worker = TurnMutatingWorker(submit_behavior="callback_immediately")
        memory = FakeMemoryManager()

        _handle_turn(
            "第一轮问题",
            session=bundle.session,
            client=first_client,
            memory=memory,
            archive_writer=archive,
            worker=worker,
        )

        reloaded = SessionState.from_storage(bundle.root, bundle.session.session_id)
        persisted_turns = load_turn_records(bundle.session.turns_path())

        assert persisted_turns[-1].assistant == "原始回答 [enriched]"
        assert persisted_turns[-1].reasoning_summary == "异步回写后的摘要"
        assert reloaded.message_history[-1]["content"] == "原始回答 [enriched]"

        _handle_turn(
            "第二轮问题",
            session=reloaded,
            client=second_client,
            memory=FakeMemoryManager(),
            archive_writer=archive,
            worker=FakeWorker(),
        )

        messages = second_client.last_messages
        assert messages[-3]["content"] == "第一轮问题"
        assert messages[-2]["content"] == "原始回答 [enriched]"
        assert messages[-1]["content"] == "第二轮问题"
    finally:
        bundle.tempdir.cleanup()
