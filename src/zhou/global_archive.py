from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from .core.config import GlobalArchiveSettings
from .session import TurnRecord


@dataclass(slots=True)
class GlobalArchiveRecord:
    timestamp: str
    session_id: str
    cwd: str
    project_name: str
    scope: str
    user: str
    assistant: str
    tool_calls: list[dict[str, str]]
    tags: list[str]


class NullGlobalArchiveWriter:
    def append_turn(self, *, cwd: Path, turn: TurnRecord) -> None:
        return None


class JsonlGlobalArchiveWriter:
    def __init__(self, settings: GlobalArchiveSettings) -> None:
        self.settings = settings

    def append_turn(self, *, cwd: Path, turn: TurnRecord) -> None:
        if not self.settings.enabled or not self.settings.sync_on_turn:
            return
        root = Path(self.settings.root_dir)
        root.mkdir(parents=True, exist_ok=True)
        day_file = root / f"{archive_day(turn.timestamp)}.jsonl"
        record = GlobalArchiveRecord(
            timestamp=turn.timestamp or datetime.now(timezone.utc).isoformat(),
            session_id=turn.session_id,
            cwd=str(cwd),
            project_name=project_name_from_cwd(cwd),
            scope="global_episodic_archive",
            user=turn.user,
            assistant=turn.assistant,
            tool_calls=serialize_tool_calls(turn) if self.settings.include_tool_calls else [],
            tags=list(turn.tags) if self.settings.include_tags else [],
        )
        with day_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")


def build_global_archive_writer(settings: GlobalArchiveSettings):
    if not settings.enabled:
        return NullGlobalArchiveWriter()
    if settings.format.lower() != "jsonl":
        return NullGlobalArchiveWriter()
    return JsonlGlobalArchiveWriter(settings)


def archive_day(timestamp: str) -> str:
    text = str(timestamp or "").strip()
    return text[:10] if len(text) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")


def project_name_from_cwd(cwd: Path) -> str:
    name = cwd.name.strip()
    return name or str(cwd)


def serialize_tool_calls(turn: TurnRecord) -> list[dict[str, str]]:
    return [{"name": item.name, "arguments": item.arguments} for item in turn.tool_calls]
