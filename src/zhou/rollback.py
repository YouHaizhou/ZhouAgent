from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from .session import SessionState, load_message_history

BACKUP_ROOT_RELATIVE_PATH = Path(".zhou") / "backup" / "last-turn"
MEMORY_TOMBSTONES_RELATIVE_PATH = Path(".zhou") / "memory_tombstones.json"


@dataclass(slots=True)
class RollbackResult:
    ok: bool
    message: str
    restored_files: list[str]
    deleted_files: list[str]
    tombstoned_memories: list[str]


@dataclass(slots=True)
class RollbackPreview:
    ok: bool
    message: str
    user_input: str
    assistant_preview: str
    tool_names: list[str]
    created_files: list[str]
    modified_files: list[str]
    deleted_files: list[str]
    memory_revisions: list[str]
    status: str


class LastTurnRollbackManager:
    def __init__(self, project_cwd: Path) -> None:
        self.project_cwd = project_cwd

    def backup_root(self) -> Path:
        return self.project_cwd / BACKUP_ROOT_RELATIVE_PATH

    def meta_path(self) -> Path:
        return self.backup_root() / "meta.json"

    def workspace_dir(self) -> Path:
        return self.backup_root() / "files" / "workspace"

    def workspace_manifest_path(self) -> Path:
        return self.backup_root() / "files" / "manifest-before.json"

    def session_dir(self) -> Path:
        return self.backup_root() / "session"

    def session_meta_backup_path(self) -> Path:
        return self.session_dir() / "meta.json"

    def session_turns_backup_path(self) -> Path:
        return self.session_dir() / "turns.jsonl"

    def ensure_storage(self) -> None:
        self.backup_root().mkdir(parents=True, exist_ok=True)

    def start_turn(self, session: SessionState, user_input: str) -> None:
        backup_root = self.backup_root()
        if backup_root.exists():
            shutil.rmtree(backup_root, ignore_errors=True)
        self.ensure_storage()
        self.session_dir().mkdir(parents=True, exist_ok=True)
        shutil.copy2(session.meta_path(), self.session_meta_backup_path())
        shutil.copy2(session.turns_path(), self.session_turns_backup_path())
        self._write_meta({
            "created_at": _utcnow(),
            "status": "collecting",
            "session_id": session.session_id,
            "user_input": user_input,
            "turn_timestamp": "",
            "assistant_preview": "",
            "workspace_snapshot_taken": False,
            "workspace_changes": {"created": [], "modified": [], "deleted": []},
            "tool_calls": [],
            "memory_writes": [],
            "memory_sync_complete": False,
            "rolled_back_at": "",
        })

    def ensure_workspace_snapshot(self) -> None:
        meta = self._read_meta()
        if meta.get("workspace_snapshot_taken"):
            return
        self.workspace_dir().mkdir(parents=True, exist_ok=True)
        manifest = snapshot_workspace(self.project_cwd, self.workspace_dir())
        self.workspace_manifest_path().write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        meta["workspace_snapshot_taken"] = True
        self._write_meta(meta)

    def record_tool_call(self, *, name: str, arguments: str, result: str) -> None:
        meta = self._read_meta()
        tool_calls = list(meta.get("tool_calls") or [])
        tool_calls.append({
            "name": name,
            "arguments": arguments,
            "result_preview": shorten(result, 300),
            "timestamp": _utcnow(),
        })
        meta["tool_calls"] = tool_calls
        self._write_meta(meta)

    def finalize_turn(self, *, turn_timestamp: str, assistant_text: str) -> None:
        meta = self._read_meta()
        meta["turn_timestamp"] = turn_timestamp
        meta["assistant_preview"] = shorten(assistant_text, 300)
        if meta.get("workspace_snapshot_taken"):
            before = self._read_workspace_manifest()
            after = build_workspace_manifest(self.project_cwd)
            meta["workspace_changes"] = diff_manifests(before, after)
        meta["status"] = "pending_memory"
        self._write_meta(meta)

    def record_memory_write(self, *, scope: str, memory_class: str, memory_key: str, revision: int) -> None:
        meta = self._read_meta()
        writes = list(meta.get("memory_writes") or [])
        writes.append({
            "scope": scope,
            "memory_class": memory_class,
            "memory_key": memory_key,
            "revision": revision,
        })
        meta["memory_writes"] = writes
        self._write_meta(meta)

    def mark_memory_complete(self) -> None:
        meta = self._read_meta()
        meta["memory_sync_complete"] = True
        if meta.get("status") != "rolled_back":
            meta["status"] = "ready"
        self._write_meta(meta)

    def rollback_last_turn(self, session: SessionState) -> RollbackResult:
        meta = self._read_meta()
        if not meta:
            return RollbackResult(False, "没有可回滚的上一轮记录。", [], [], [])
        if meta.get("status") == "rolled_back":
            return RollbackResult(False, "上一轮已经回滚过了。", [], [], [])

        restored_files: list[str] = []
        deleted_files: list[str] = []
        tombstoned_memories: list[str] = []

        if meta.get("workspace_snapshot_taken"):
            restored_files, deleted_files = restore_workspace_from_snapshot(self.project_cwd, self.workspace_dir())

        self._restore_session_snapshot(session)

        for item in meta.get("memory_writes") or []:
            memory_key = str(item.get("memory_key") or "").strip()
            revision = safe_int(item.get("revision"), default=0)
            if not memory_key or revision <= 0:
                continue
            append_memory_tombstone(self.project_cwd, memory_key=memory_key, revision=revision)
            tombstoned_memories.append(f"{memory_key}@{revision}")

        meta["status"] = "rolled_back"
        meta["rolled_back_at"] = _utcnow()
        self._write_meta(meta)
        return RollbackResult(
            True,
            "上一轮回滚完成。",
            restored_files=restored_files,
            deleted_files=deleted_files,
            tombstoned_memories=tombstoned_memories,
        )

    def _restore_session_snapshot(self, session: SessionState) -> None:
        if self.session_meta_backup_path().is_file():
            shutil.copy2(self.session_meta_backup_path(), session.meta_path())
        if self.session_turns_backup_path().is_file():
            shutil.copy2(self.session_turns_backup_path(), session.turns_path())
        session.message_history = load_message_history(session.turns_path())

    def _read_workspace_manifest(self) -> dict[str, str]:
        path = self.workspace_manifest_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return {str(key): str(value) for key, value in data.items()} if isinstance(data, dict) else {}

    def _read_meta(self) -> dict[str, Any]:
        path = self.meta_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return dict(data) if isinstance(data, dict) else {}

    def _write_meta(self, payload: dict[str, Any]) -> None:
        self.ensure_storage()
        self.meta_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_rollback_result(result: RollbackResult) -> None:
    print()
    print(result.message)
    if result.restored_files:
        print("已恢复文件：")
        for path in result.restored_files[:20]:
            print(f"  - {path}")
    if result.deleted_files:
        print("已删除新增文件：")
        for path in result.deleted_files[:20]:
            print(f"  - {path}")
    if result.tombstoned_memories:
        print("已撤回记忆 revision：")
        for item in result.tombstoned_memories[:20]:
            print(f"  - {item}")
    print()


def snapshot_workspace(project_cwd: Path, snapshot_dir: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for file_path in iter_workspace_files(project_cwd):
        relative = file_path.relative_to(project_cwd).as_posix()
        manifest[relative] = hash_file(file_path)
        backup_path = snapshot_dir / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, backup_path)
    return manifest


def build_workspace_manifest(project_cwd: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for file_path in iter_workspace_files(project_cwd):
        relative = file_path.relative_to(project_cwd).as_posix()
        manifest[relative] = hash_file(file_path)
    return manifest


def restore_workspace_from_snapshot(project_cwd: Path, snapshot_dir: Path) -> tuple[list[str], list[str]]:
    before = build_workspace_manifest(project_cwd)
    snapshot_manifest = build_workspace_manifest(snapshot_dir)
    restored_files: list[str] = []
    deleted_files: list[str] = []

    for relative in sorted(before):
        if relative in snapshot_manifest:
            continue
        current_path = project_cwd / relative
        if current_path.is_file():
            current_path.unlink(missing_ok=True)
            deleted_files.append(relative)

    prune_empty_dirs(project_cwd)

    for relative in sorted(snapshot_manifest):
        source = snapshot_dir / relative
        target = project_cwd / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        restored_files.append(relative)

    return restored_files, deleted_files


def diff_manifests(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    before_keys = set(before)
    after_keys = set(after)
    created = sorted(after_keys - before_keys)
    deleted = sorted(before_keys - after_keys)
    modified = sorted(path for path in before_keys & after_keys if before[path] != after[path])
    return {"created": created, "modified": modified, "deleted": deleted}


def iter_workspace_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == ".zhou":
            continue
        yield path


def prune_empty_dirs(root: Path) -> None:
    paths = sorted((path for path in root.rglob("*") if path.is_dir()), key=lambda item: len(item.parts), reverse=True)
    for path in paths:
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if relative.parts and relative.parts[0] == ".zhou":
            continue
        try:
            path.rmdir()
        except OSError:
            continue


def hash_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def append_memory_tombstone(project_cwd: Path, *, memory_key: str, revision: int) -> None:
    path = project_cwd / MEMORY_TOMBSTONES_RELATIVE_PATH
    payload = load_memory_tombstones(project_cwd)
    entries = payload.get("entries") or []
    key = f"{memory_key}@{revision}"
    if any(str(item.get("id") or "") == key for item in entries if isinstance(item, dict)):
        return
    entries.append({"id": key, "memory_key": memory_key, "revision": revision, "timestamp": _utcnow()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_memory_tombstones(project_cwd: Path) -> dict[str, Any]:
    path = project_cwd / MEMORY_TOMBSTONES_RELATIVE_PATH
    if not path.is_file():
        return {"entries": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"entries": []}
    return dict(data) if isinstance(data, dict) else {"entries": []}


def is_tombstoned_memory(project_cwd: Path | None, *, memory_key: str, revision: int) -> bool:
    if project_cwd is None or not memory_key or revision <= 0:
        return False
    payload = load_memory_tombstones(project_cwd)
    for item in payload.get("entries") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("memory_key") or "") == memory_key and safe_int(item.get("revision"), default=0) == revision:
            return True
    return False


def safe_int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def shorten(text: str, max_length: int) -> str:
    compact = " ".join(str(text or "").split()).strip()
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 1].rstrip() + "…"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()
