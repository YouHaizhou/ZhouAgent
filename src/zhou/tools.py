from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO
import json
import os
import re
import shutil
import subprocess
import threading
import tomllib
from queue import Empty, Queue

from .core.config import user_home_dir
from .core.errors import InvalidToolsConfigError


TOOLS_CONFIG_RELATIVE_PATH = Path(".zhou") / "tools.toml"
USER_TOOLS_CONFIG_RELATIVE_PATH = Path(".zhou") / "tools.toml"
MCP_PROTOCOL_VERSION = "2024-11-05"
PROJECT_DIR_TOKENS = ("${project_dir}", "$PROJECT_DIR", "{project_dir}")
PROJECT_LOGS_RELATIVE_DIR = Path(".zhou") / "logs"
MCP_SERVER_LOG_FILENAME = "mcp-server.log"
MCP_DISCOVERY_TRACE_FILENAME = "mcp-discovery-trace.jsonl"


@dataclass(slots=True)
class ToolSourceConfig:
    id: str
    type: str
    enabled: bool
    transport: str
    command: str
    args: list[str] = field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ToolSourceState:
    source_id: str
    status: str
    message: str
    discovered_count: int = 0


@dataclass(slots=True)
class ToolDescriptor:
    source_id: str
    name: str
    qualified_name: str
    description: str
    input_schema: dict[str, object] = field(default_factory=dict)
    enabled: bool = True

    def to_openai_tool(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


@dataclass(slots=True)
class ToolRegistry:
    config_path: Path | None = None
    sources: list[ToolSourceConfig] = field(default_factory=list)
    states: list[ToolSourceState] = field(default_factory=list)
    tools: list[ToolDescriptor] = field(default_factory=list)

    @property
    def configured_count(self) -> int:
        return len(self.sources)

    @property
    def enabled_count(self) -> int:
        return sum(1 for source in self.sources if source.enabled)

    @property
    def discovered_count(self) -> int:
        return len(self.tools)

    @property
    def ready_count(self) -> int:
        return sum(1 for state in self.states if state.status == "ready")

    @property
    def failed_count(self) -> int:
        return sum(1 for state in self.states if state.status == "failed")

    def get_tool(self, qualified_name: str) -> ToolDescriptor | None:
        return next((tool for tool in self.tools if tool.qualified_name == qualified_name), None)

    def get_source(self, source_id: str) -> ToolSourceConfig | None:
        return next((source for source in self.sources if source.id == source_id), None)


def empty_tool_registry() -> ToolRegistry:
    return ToolRegistry()


def default_project_tools_contents(cwd: Path) -> str:
    user_config = discover_user_tools_config_path()
    if user_config is not None and user_config.is_file():
        return normalize_project_tools_template(user_config.read_text(encoding="utf-8"), cwd)
    project_path = str(cwd).replace("\\", "/")
    return f'''[[sources]]
id = "filesystem"
type = "mcp"
enabled = true
transport = "stdio"
command = "node"
args = [
  "C:/Users/34306/.zhou/mcp/filesystem/node_modules/@modelcontextprotocol/server-filesystem/dist/index.js",
  "${{project_dir}}"
]

[[sources]]
id = "git"
type = "mcp"
enabled = true
transport = "stdio"
command = "node"
args = [
  "C:/Users/34306/.zhou/mcp/git/node_modules/@cyanheads/git-mcp-server/dist/index.js"
]
cwd = "${{project_dir}}"

[sources.env]
MCP_TRANSPORT_TYPE = "stdio"
'''


def ensure_project_tools_file(cwd: Path) -> Path:
    config_path = cwd / TOOLS_CONFIG_RELATIVE_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(default_project_tools_contents(cwd), encoding="utf-8")
    return config_path


def discover_tool_registry(cwd: Path) -> ToolRegistry:
    """只读取项目级 tools.toml，并按项目配置决定启用哪些 tools。"""
    config_path = ensure_project_tools_file(cwd)
    if not config_path.is_file():
        return ToolRegistry(config_path=config_path)

    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    raw_sources = data.get("sources")
    if raw_sources is None:
        return ToolRegistry(config_path=config_path)
    if not isinstance(raw_sources, list):
        raise InvalidToolsConfigError("`sources` 必须是数组表")

    sources = [parse_source_config(item, index) for index, item in enumerate(raw_sources, start=1)]
    sources = [resolve_source_templates(source, cwd) for source in sources]

    states: list[ToolSourceState] = []
    tools: list[ToolDescriptor] = []
    for source in sources:
        state, discovered = inspect_and_discover_source(source, cwd)
        states.append(state)
        tools.extend(discovered)

    return ToolRegistry(config_path=config_path, sources=sources, states=states, tools=tools)


def discover_user_tools_config_path() -> Path | None:
    home_dir = user_home_dir()
    if home_dir is None:
        return None
    return home_dir / USER_TOOLS_CONFIG_RELATIVE_PATH


def normalize_project_tools_template(contents: str, cwd: Path) -> str:
    project_path = str(cwd).replace("\\", "/")
    normalized = contents.replace("\\", "/")
    return normalized.replace(project_path, "${project_dir}")


def expand_project_tokens(value: str, project_cwd: Path) -> str:
    expanded = value
    for token in PROJECT_DIR_TOKENS:
        expanded = expanded.replace(token, str(project_cwd))
    return expanded


def parse_source_config(raw: object, index: int) -> ToolSourceConfig:
    if not isinstance(raw, dict):
        raise InvalidToolsConfigError(f"第 {index} 个 source 必须是表")

    source_id = require_string(raw, "id", index)
    source_type = require_string(raw, "type", index).lower()
    enabled = bool(raw.get("enabled", True))
    transport = str(raw.get("transport", "stdio")).strip().lower()
    command = str(raw.get("command", "")).strip()
    args_raw = raw.get("args", [])
    cwd = raw.get("cwd")
    env_raw = raw.get("env", {})

    if args_raw is None:
        args = []
    elif isinstance(args_raw, list):
        args = [str(item) for item in args_raw]
    else:
        raise InvalidToolsConfigError(f"source `{source_id}` 的 args 必须是数组")

    if cwd is not None and not isinstance(cwd, str):
        raise InvalidToolsConfigError(f"source `{source_id}` 的 cwd 必须是字符串")

    if not isinstance(env_raw, dict):
        raise InvalidToolsConfigError(f"source `{source_id}` 的 env 必须是表")
    env = {str(key): str(value) for key, value in env_raw.items()}

    return ToolSourceConfig(
        id=source_id,
        type=source_type,
        enabled=enabled,
        transport=transport,
        command=command,
        args=args,
        cwd=cwd,
        env=env,
    )


def resolve_source_templates(source: ToolSourceConfig, project_cwd: Path) -> ToolSourceConfig:
    resolved_command = expand_project_tokens(source.command, project_cwd)
    resolved_args = [expand_project_tokens(arg, project_cwd) for arg in source.args]
    resolved_cwd = expand_project_tokens(source.cwd, project_cwd) if source.cwd else None
    resolved_env = {key: expand_project_tokens(value, project_cwd) for key, value in source.env.items()}
    return ToolSourceConfig(
        id=source.id,
        type=source.type,
        enabled=source.enabled,
        transport=source.transport,
        command=resolved_command,
        args=resolved_args,
        cwd=resolved_cwd,
        env=resolved_env,
    )


def require_string(raw: dict[str, object], field_name: str, index: int) -> str:
    value = raw.get(field_name)
    if value is None or not str(value).strip():
        raise InvalidToolsConfigError(f"第 {index} 个 source 缺少字段 `{field_name}`")
    return str(value).strip()


def inspect_and_discover_source(source: ToolSourceConfig, project_cwd: Path) -> tuple[ToolSourceState, list[ToolDescriptor]]:
    """校验 source 并通过 MCP handshake 拉取该 source 暴露的 tools。"""
    if not source.enabled:
        return ToolSourceState(source_id=source.id, status="disabled", message="source disabled"), []

    if source.type != "mcp":
        return ToolSourceState(source_id=source.id, status="failed", message=f"unsupported type: {source.type}"), []

    if source.transport != "stdio":
        return ToolSourceState(source_id=source.id, status="failed", message=f"unsupported transport: {source.transport}"), []

    if not source.command:
        return ToolSourceState(source_id=source.id, status="failed", message="missing command"), []

    working_directory = resolve_source_cwd(project_cwd, source.cwd)
    if source.cwd and not working_directory.is_dir():
        return ToolSourceState(source_id=source.id, status="failed", message=f"cwd not found: {working_directory}"), []

    resolved = resolve_command(source.command, working_directory)
    if resolved is None:
        return ToolSourceState(source_id=source.id, status="failed", message=f"command not found: {source.command}"), []

    before_snapshot = snapshot_top_level_entries(project_cwd)
    discovered: list[ToolDescriptor] = []
    status = "ready"
    message = ""
    try:
        discovered = discover_tools_via_stdio(source, working_directory)
        message = f"discovered {len(discovered)} tools"
    except Exception as exc:
        status = "failed"
        message = str(exc)
    finally:
        after_snapshot = snapshot_top_level_entries(project_cwd)
        append_mcp_discovery_trace(
            project_cwd,
            source=source,
            working_directory=working_directory,
            status=status,
            message=message,
            created_entries=diff_created_entries(before_snapshot, after_snapshot),
        )

    if status != "ready":
        return ToolSourceState(source_id=source.id, status=status, message=message), []

    return ToolSourceState(
        source_id=source.id,
        status=status,
        message=message,
        discovered_count=len(discovered),
    ), discovered


class McpSession:
    """Context manager that encapsulates the lifecycle of a single MCP stdio session.

    Usage::

        with McpSession(source, working_directory) as session:
            tools = session.list_tools()
            result = session.call_tool("read", {"path": "/foo"})
    """

    def __init__(self, source: ToolSourceConfig, working_directory: Path) -> None:
        self._source = source
        self._working_directory = working_directory
        self._process: subprocess.Popen[bytes] | None = None
        self._next_id = 2  # id=1 is consumed by initialize_mcp_session

    # --- context manager -------------------------------------------------

    def __enter__(self) -> "McpSession":
        self._process = start_stdio_process(self._source, self._working_directory)
        initialize_mcp_session(self._process)
        return self

    def __exit__(self, *args: object) -> bool:
        if self._process is not None:
            terminate_process(self._process)
        return False

    # --- MCP operations --------------------------------------------------

    def list_tools(self) -> list[ToolDescriptor]:
        """Send ``tools/list`` and parse the result into descriptors."""
        assert self._process is not None, "session not active"
        result = request_mcp(self._process, self._next_id, "tools/list", {})
        self._next_id += 1
        return parse_tools_list(self._source.id, result)

    def call_tool(self, name: str, arguments: dict[str, object], *, timeout_seconds: float = 5.0) -> object:
        """Send ``tools/call`` and return the raw result object."""
        assert self._process is not None, "session not active"
        result = request_mcp(
            self._process,
            self._next_id,
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout_seconds=timeout_seconds,
        )
        self._next_id += 1
        return result


def discover_tools_via_stdio(source: ToolSourceConfig, working_directory: Path) -> list[ToolDescriptor]:
    """启动 MCP stdio 进程，完成 initialize 后请求 tools/list。"""
    with McpSession(source, working_directory) as session:
        return session.list_tools()


def start_stdio_process(source: ToolSourceConfig, working_directory: Path) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [source.command, *source.args],
        cwd=str(working_directory),
        env=build_process_env(source),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    attach_mcp_stderr_logger(process, project_cwd=working_directory)
    return process


def initialize_mcp_session(process: subprocess.Popen[bytes]) -> None:
    initialize_result = request_mcp(process, 1, "initialize", {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "zhou", "version": "0.1.0"},
    })
    if not isinstance(initialize_result, dict):
        raise RuntimeError("initialize result invalid")
    notify_mcp(process, "notifications/initialized", {})


def build_process_env(source: ToolSourceConfig) -> dict[str, str]:
    env = dict(os.environ)
    env.update(source.env)
    return env


def project_logs_dir(project_cwd: Path) -> Path:
    log_dir = project_cwd / PROJECT_LOGS_RELATIVE_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def snapshot_top_level_entries(project_cwd: Path) -> set[str]:
    try:
        return {child.name for child in project_cwd.iterdir()}
    except OSError:
        return set()


def diff_created_entries(before: set[str], after: set[str]) -> list[str]:
    return sorted(name for name in after - before if name and name not in {".zhou", "__pycache__"})


def append_mcp_discovery_trace(
    project_cwd: Path,
    *,
    source: ToolSourceConfig,
    working_directory: Path,
    status: str,
    message: str,
    created_entries: list[str],
) -> None:
    try:
        log_path = project_logs_dir(project_cwd) / MCP_DISCOVERY_TRACE_FILENAME
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_id": source.id,
            "command": source.command,
            "args": list(source.args),
            "configured_cwd": source.cwd,
            "working_directory": str(working_directory),
            "status": status,
            "message": message,
            "created_entries": created_entries,
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return


def attach_mcp_stderr_logger(process: subprocess.Popen[bytes], *, project_cwd: Path) -> None:
    if process.stderr is None:
        return

    log_path = project_logs_dir(project_cwd) / MCP_SERVER_LOG_FILENAME

    def _reader() -> None:
        try:
            with log_path.open("a", encoding="utf-8") as fh:
                while True:
                    line = process.stderr.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace")
                    if text:
                        fh.write(text)
                        fh.flush()
        except Exception:
            return

    threading.Thread(target=_reader, daemon=True, name="zhou-mcp-stderr-logger").start()


def call_tool(registry: ToolRegistry, qualified_name: str, arguments_json: str, project_cwd: Path) -> str:
    """按模型给出的工具名和参数执行一次 MCP tools/call。"""
    tool = registry.get_tool(qualified_name)
    if tool is None:
        return f"tool not found: {qualified_name}"

    source = registry.get_source(tool.source_id)
    if source is None:
        return f"tool source not found: {tool.source_id}"

    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        return f"invalid tool arguments JSON: {exc}"

    if not isinstance(arguments, dict):
        return "invalid tool arguments: expected JSON object"

    validation_error = validate_common_tool_arguments(tool, arguments)
    if validation_error:
        return validation_error

    timeout_seconds = infer_tool_call_timeout_seconds(tool, arguments)

    try:
        with McpSession(source, resolve_source_cwd(project_cwd, source.cwd)) as session:
            result = session.call_tool(tool.name, arguments, timeout_seconds=timeout_seconds)
            return stringify_tool_result(result)
    except Exception as exc:
        return f"tool call failed: {humanize_tool_error(tool, exc)}"


def stringify_tool_result(result: object) -> str:
    """把 tools/call 返回值收敛成可回注模型的文本结果。"""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = [str(item["text"]) for item in content if isinstance(item, dict) and item.get("text") is not None]
            if parts:
                return "\n".join(parts)
        return json.dumps(result, ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def validate_common_tool_arguments(tool: ToolDescriptor, arguments: dict[str, object]) -> str:
    if tool.qualified_name == "shell.shell_execute" and not str(arguments.get("command") or "").strip():
        return "invalid tool arguments: shell.shell_execute requires non-empty field `command`"
    return ""


def infer_tool_call_timeout_seconds(tool: ToolDescriptor, arguments: dict[str, object]) -> float:
    if tool.source_id != "shell":
        return 5.0
    requested = safe_float(arguments.get("timeout_seconds"), default=60.0)
    foreground = safe_float(arguments.get("foreground_timeout_seconds"), default=15.0)
    mode = str(arguments.get("execution_mode") or "adaptive").strip().lower()
    if mode == "foreground":
        return min(max(requested, 10.0) + 5.0, 3700.0)
    if mode == "adaptive":
        return min(max(foreground, 10.0) + 5.0, 3700.0)
    if mode in {"background", "detached"}:
        return 15.0
    return 30.0


def humanize_tool_error(tool: ToolDescriptor, exc: Exception) -> str:
    message = str(exc).strip()
    if tool.qualified_name == "shell.shell_execute":
        if "timeout waiting for response: tools/call" in message:
            return "shell.shell_execute timed out waiting for MCP response; command may still be running or the shell server may require a longer call timeout"
        if "Required" in message and '"command"' in message:
            return "shell.shell_execute missing required field `command`"
        if "spawn /bin/bash ENOENT" in message:
            return "shell.shell_execute failed because the shell server tried to use /bin/bash on Windows; a Windows shell such as powershell.exe is required"
        restrictive = re.search(r"Command '(.+?)' is not allowed in restrictive mode", message)
        if restrictive:
            blocked_command = restrictive.group(1)
            return f"shell.shell_execute was blocked by shell server restrictive mode: `{blocked_command}`; switch the shell MCP security mode to permissive or relax server rules for practical development commands"
        if "unsupported client method" in message:
            return f"shell MCP server requested an unsupported client method: {message}"
    return message


def safe_float(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def request_mcp(process: subprocess.Popen[bytes], request_id: int, method: str, params: dict[str, object], *, timeout_seconds: float = 5.0) -> object:
    """发送一条 JSON-RPC 请求，并等待对应 MCP 响应结果。"""
    write_mcp_message(process, {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    })
    while True:
        response = read_mcp_message(process, timeout_seconds=timeout_seconds)
        if response is None:
            raise RuntimeError(f"timeout waiting for response: {method}")
        if "id" in response and "method" in response:
            handle_mcp_server_request(process, response)
            continue
        if "id" not in response:
            continue
        if response.get("id") != request_id:
            continue
        if "error" in response:
            raise RuntimeError(f"{method} failed: {response['error']}")
        return response.get("result")


def handle_mcp_server_request(process: subprocess.Popen[bytes], request: dict[str, object]) -> None:
    request_id = request.get("id")
    method = str(request.get("method") or "").strip()
    if request_id is None or not method:
        return
    if method == "sampling/createMessage":
        write_mcp_message(process, {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": build_sampling_create_message_result(request.get("params")),
        })
        return
    write_mcp_message(process, {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"unsupported client method: {method}"},
    })


def build_sampling_create_message_result(params: object) -> dict[str, object]:
    command = extract_sampling_command(params)
    tool_name, tool_arguments = choose_sampling_tool_response(command)
    payload = {
        "tool_calls": [{
            "id": "call_zhou_sampling",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(tool_arguments, ensure_ascii=False),
            },
        }]
    }
    return {
        "role": "assistant",
        "content": {"type": "text", "text": json.dumps(payload, ensure_ascii=False)},
        "model": "zhou-mcp-client",
        "stopReason": "tool_calls",
    }


def extract_sampling_command(params: object) -> str:
    if not isinstance(params, dict):
        return ""
    messages = params.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, dict):
            text = str(content.get("text") or "")
        else:
            text = str(content or "")
        match = re.search(r"\*\*Command\*\*:\s*`([^`]+)`", text)
        if match:
            return match.group(1).strip()
    return ""


def choose_sampling_tool_response(command: str) -> tuple[str, dict[str, object]]:
    normalized = command.strip().lower()
    if is_obviously_destructive_command(normalized):
        return "deny", {
            "reasoning": f"The command $COMMAND appears destructive or high-risk and is denied by the Zhou MCP compatibility layer.",
            "suggested_alternatives": ["Review the command manually and rerun a safer scoped variant."],
        }
    return "allow", {
        "reasoning": f"The command $COMMAND is allowed by the Zhou MCP compatibility layer so the shell server can proceed without interactive sampling support.",
    }


def is_obviously_destructive_command(command: str) -> bool:
    dangerous_patterns = (
        r"(^|\s)rm\s+-rf\s+(/|\\|\*)",
        r"(^|\s)del\s+/[a-z/]*[sqf]*\s+.*",
        r"(^|\s)rmdir\s+/[a-z/]*[sqf]*\s+.*",
        r"(^|\s)format(\s|$)",
        r"(^|\s)shutdown(\s|$)",
        r"(^|\s)reboot(\s|$)",
        r"(^|\s)init\s+0(\s|$)",
        r":\(\)\s*\{\s*:\|:\s*&\s*\};:",
    )
    return any(re.search(pattern, command, flags=re.IGNORECASE) for pattern in dangerous_patterns)


def notify_mcp(process: subprocess.Popen[bytes], method: str, params: dict[str, object]) -> None:
    write_mcp_message(process, {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    })


def write_mcp_message(process: subprocess.Popen[bytes], payload: dict[str, object]) -> None:
    if process.stdin is None:
        raise RuntimeError("mcp process stdin unavailable")

    body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    process.stdin.write(body)
    process.stdin.flush()


def read_mcp_message(process: subprocess.Popen[bytes], timeout_seconds: float) -> dict[str, object] | None:
    """从 MCP 进程 stdout 读取一条完整协议消息。"""
    if process.stdout is None:
        raise RuntimeError("mcp process stdout unavailable")

    queue: Queue[dict[str, object] | None] = Queue(maxsize=1)

    def _reader() -> None:
        try:
            queue.put(read_single_message(process.stdout))
        except Exception as exc:
            queue.put({"error": str(exc)})

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()

    try:
        result = queue.get(timeout=timeout_seconds)
    except Empty:
        return None

    if result is None:
        return None
    if "error" in result and "jsonrpc" not in result:
        raise RuntimeError(str(result["error"]))
    return result


def read_single_message(stream: subprocess.PIPE) -> dict[str, object] | None:
    """按一行一个 JSON 的 stdio framing 解析单条 MCP 消息体。"""
    while True:
        line = stream.readline()
        if not line:
            return None
        decoded = line.decode("utf-8", errors="replace").strip()
        if not decoded:
            continue
        payload = json.loads(decoded)
        if not isinstance(payload, dict):
            raise RuntimeError("mcp payload must be object")
        return payload


def parse_tools_list(source_id: str, result: object) -> list[ToolDescriptor]:
    if not isinstance(result, dict):
        raise RuntimeError("tools/list result invalid")

    raw_tools = result.get("tools")
    if raw_tools is None:
        return []
    if not isinstance(raw_tools, list):
        raise RuntimeError("tools/list tools invalid")

    discovered: list[ToolDescriptor] = []
    for raw in raw_tools:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        description = str(raw.get("description") or "").strip()
        input_schema = raw.get("inputSchema")
        if not isinstance(input_schema, dict):
            input_schema = {}
        discovered.append(
            ToolDescriptor(
                source_id=source_id,
                name=name,
                qualified_name=f"{source_id}.{name}",
                description=description,
                input_schema=input_schema,
                enabled=True,
            )
        )
    return discovered


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.terminate()
        process.wait(timeout=1.0)
    except Exception:
        try:
            process.kill()
            process.wait(timeout=1.0)
        except Exception:
            pass


def resolve_source_cwd(project_cwd: Path, source_cwd: str | None) -> Path:
    if not source_cwd:
        return project_cwd

    candidate = Path(source_cwd)
    if candidate.is_absolute():
        return candidate
    return project_cwd / candidate


def resolve_command(command: str, working_directory: Path) -> Path | str | None:
    candidate = Path(command)
    if candidate.is_absolute():
        return candidate if candidate.exists() else None

    if any(sep in command for sep in ("/", "\\")):
        resolved = working_directory / candidate
        return resolved if resolved.exists() else None

    return shutil.which(command)
