from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from .errors import ConfigNotFoundError, InvalidConfigError

PROJECT_CONFIG_RELATIVE_PATH = Path(".zhou") / "config.toml"
USER_CONFIG_RELATIVE_PATH = Path(".zhou") / "config.toml"
LEGACY_PROJECT_CONFIG_PATHS = (Path("config.toml"), Path("config.md"))
DEFAULT_EMBEDDING_MODEL_PATH = r"G:/Memory/models/embedding-models/bge-small-zh-v1.5"
DEFAULT_QDRANT_STORAGE_PATH = r"G:/Memory/database"
DEFAULT_GLOBAL_ARCHIVE_ROOT = r"G:/Memory/daily-memory/raw"

@dataclass(slots=True)
class MemoryModelSettings:
    enabled: bool
    api_key: str
    base_url: str
    model: str
    temperature: float
    max_tokens: int
    top_p: float
    top_k: int
    mode: str
    generate_reasoning_summary: bool
    generate_session_memory: bool
    generate_folder_memory: bool
    allow_model_decide_promotion: bool
    promotion_min_turns: int

@dataclass(slots=True)
class GlobalArchiveSettings:
    enabled: bool
    root_dir: str
    format: str
    sync_on_turn: bool
    include_tool_calls: bool
    include_tags: bool
    include_reasoning_summary: bool

@dataclass(slots=True)
class GlobalMemorySettings:
    archive: GlobalArchiveSettings

@dataclass(slots=True)
class MemorySettings:
    enabled: bool
    api_key: str
    user_id: str
    agent_id: str
    collection_name: str
    qdrant_host: str
    qdrant_port: int
    qdrant_grpc_port: int
    qdrant_storage_path: str
    qdrant_container_name: str
    qdrant_image: str
    qdrant_auto_start: bool
    embedding_model: str
    embedding_dims: int
    deepseek_base_url: str
    deepseek_model: str
    deepseek_temperature: float
    deepseek_max_tokens: int
    deepseek_top_p: float
    deepseek_top_k: int
    memory_model: MemoryModelSettings

@dataclass(slots=True)
class AppConfig:
    base_url: str
    api_key: str
    model: str
    memory: MemorySettings
    global_memory: GlobalMemorySettings

    @classmethod
    def load(cls) -> "AppConfig":
        merged = load_merged_config_data()
        base_url = normalize_string(merged.get("base_url"))
        api_key = normalize_string(merged.get("api_key"))
        model = normalize_string(merged.get("model"))
        if not base_url:
            raise InvalidConfigError("BASE_URL")
        if not api_key:
            raise InvalidConfigError("API_KEY")
        if not model:
            raise InvalidConfigError("model")
        return cls(base_url=base_url, api_key=api_key, model=model, memory=parse_memory_settings(merged, api_key), global_memory=parse_global_memory_settings(merged))

    @property
    def chat_completions_url(self) -> str:
        normalized = self.base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/chat/completions"
        return f"{normalized}/chat/completions"

def load_merged_config_data() -> dict[str, object]:
    user_path = discover_user_config_path()
    project_path = discover_project_config_path()
    executable_path = discover_executable_config_path()
    if user_path is None and project_path is None and executable_path is None:
        raise ConfigNotFoundError()
    merged: dict[str, object] = {}
    if executable_path is not None:
        merged = deep_merge_dicts(merged, load_config_file(executable_path))
    if user_path is not None:
        merged = deep_merge_dicts(merged, load_config_file(user_path))
    if project_path is not None:
        merged = deep_merge_dicts(merged, load_config_file(project_path))
    return merged

def load_config_file(path: Path) -> dict[str, object]:
    if path.suffix.lower() == ".toml":
        return {str(key).lower(): value for key, value in tomllib.loads(path.read_text(encoding="utf-8")).items()}
    return parse_key_value_text(path.read_text(encoding="utf-8"))

def deep_merge_dicts(base: dict[str, object], override: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in override.items():
        lowered = str(key).lower()
        if isinstance(merged.get(lowered), dict) and isinstance(value, dict):
            merged[lowered] = deep_merge_dicts(merged[lowered], {str(k).lower(): v for k, v in value.items()})
        else:
            merged[lowered] = value
    return merged

def parse_memory_settings(config: dict[str, object], fallback_api_key: str) -> MemorySettings:
    memory_config = config.get("memory") if isinstance(config.get("memory"), dict) else {}
    identity = memory_config.get("identity") if isinstance(memory_config.get("identity"), dict) else {}
    embedding = memory_config.get("embedding") if isinstance(memory_config.get("embedding"), dict) else {}
    vector_store = memory_config.get("vector_store") if isinstance(memory_config.get("vector_store"), dict) else {}
    enabled = to_bool(memory_config.get("enabled"), default=True)
    deepseek_api_key = normalize_string(memory_config.get("api_key")) or os.environ.get("DEEPSEEK_API_KEY") or fallback_api_key
    if enabled and not deepseek_api_key:
        raise InvalidConfigError("memory.api_key")
    return MemorySettings(enabled=enabled, api_key=deepseek_api_key, user_id=normalize_string(identity.get("user_id")) or "default_user", agent_id=normalize_string(identity.get("agent_id")) or "zhou_agent", collection_name=normalize_string(identity.get("collection_name")) or "agent_memory_main", qdrant_host=normalize_string(vector_store.get("host")) or "127.0.0.1", qdrant_port=to_int(vector_store.get("port"), default=6333), qdrant_grpc_port=to_int(vector_store.get("grpc_port"), default=6334), qdrant_storage_path=normalize_string(vector_store.get("storage_path")) or DEFAULT_QDRANT_STORAGE_PATH, qdrant_container_name=normalize_string(vector_store.get("container_name")) or "zhou-qdrant", qdrant_image=normalize_string(vector_store.get("image")) or "qdrant/qdrant", qdrant_auto_start=to_bool(vector_store.get("auto_start"), default=True), embedding_model=normalize_string(embedding.get("model")) or DEFAULT_EMBEDDING_MODEL_PATH, embedding_dims=to_int(embedding.get("dims"), default=512), deepseek_base_url=normalize_string(memory_config.get("deepseek_base_url")) or "https://api.deepseek.com", deepseek_model=normalize_string(memory_config.get("deepseek_model")) or "deepseek-chat", deepseek_temperature=to_float(memory_config.get("deepseek_temperature"), default=0.1), deepseek_max_tokens=to_int(memory_config.get("deepseek_max_tokens"), default=2000), deepseek_top_p=to_float(memory_config.get("deepseek_top_p"), default=0.1), deepseek_top_k=to_int(memory_config.get("deepseek_top_k"), default=1), memory_model=parse_memory_model_settings(memory_config, deepseek_api_key))

def parse_memory_model_settings(memory_config: dict[str, object], fallback_api_key: str) -> MemoryModelSettings:
    worker = memory_config.get("model_worker") if isinstance(memory_config.get("model_worker"), dict) else {}
    enabled = to_bool(worker.get("enabled"), default=False)
    api_key = normalize_string(worker.get("api_key")) or os.environ.get("MEMORY_MODEL_API_KEY") or fallback_api_key
    if enabled and not api_key:
        raise InvalidConfigError("memory.model_worker.api_key")
    return MemoryModelSettings(enabled=enabled, api_key=api_key, base_url=normalize_string(worker.get("base_url")) or normalize_string(memory_config.get("deepseek_base_url")) or "https://api.deepseek.com", model=normalize_string(worker.get("model")) or normalize_string(memory_config.get("deepseek_model")) or "deepseek-chat", temperature=to_float(worker.get("temperature"), default=0.1), max_tokens=to_int(worker.get("max_tokens"), default=1200), top_p=to_float(worker.get("top_p"), default=0.1), top_k=to_int(worker.get("top_k"), default=1), mode=normalize_string(worker.get("mode")) or "async", generate_reasoning_summary=to_bool(worker.get("generate_reasoning_summary"), default=True), generate_session_memory=to_bool(worker.get("generate_session_memory"), default=True), generate_folder_memory=to_bool(worker.get("generate_folder_memory"), default=True), allow_model_decide_promotion=to_bool(worker.get("allow_model_decide_promotion"), default=True), promotion_min_turns=to_int(worker.get("promotion_min_turns"), default=3))

def parse_global_memory_settings(config: dict[str, object]) -> GlobalMemorySettings:
    global_config = config.get("global_memory") if isinstance(config.get("global_memory"), dict) else {}
    archive_config = global_config.get("archive") if isinstance(global_config.get("archive"), dict) else {}
    return GlobalMemorySettings(archive=GlobalArchiveSettings(enabled=to_bool(archive_config.get("enabled"), default=True), root_dir=normalize_string(archive_config.get("root_dir")) or DEFAULT_GLOBAL_ARCHIVE_ROOT, format=normalize_string(archive_config.get("format")) or "jsonl", sync_on_turn=to_bool(archive_config.get("sync_on_turn"), default=True), include_tool_calls=to_bool(archive_config.get("include_tool_calls"), default=True), include_tags=to_bool(archive_config.get("include_tags"), default=True), include_reasoning_summary=to_bool(archive_config.get("include_reasoning_summary"), default=False)))

def discover_project_config_path() -> Path | None:
    for candidate in [Path.cwd() / PROJECT_CONFIG_RELATIVE_PATH, *[Path.cwd() / p for p in LEGACY_PROJECT_CONFIG_PATHS]]:
        if candidate.is_file():
            return candidate
    return None

def discover_user_config_path() -> Path | None:
    home_dir = user_home_dir()
    if home_dir is None:
        return None
    for candidate in (home_dir / USER_CONFIG_RELATIVE_PATH, home_dir / ".zhou" / "config.md"):
        if candidate.is_file():
            return candidate
    return None

def discover_executable_config_path() -> Path | None:
    executable_dir = Path(sys.argv[0]).resolve().parent
    for candidate in (executable_dir / "config.toml", executable_dir / "config.md"):
        if candidate.is_file():
            return candidate
    return None

def default_user_config_contents() -> str:
    return f'''base_url = ""
api_key = ""
model = ""

[memory]
enabled = true
api_key = ""
deepseek_base_url = "https://api.deepseek.com"
deepseek_model = "deepseek-chat"
deepseek_temperature = 0.1
deepseek_max_tokens = 2000
deepseek_top_p = 0.1
deepseek_top_k = 1

[memory.embedding]
model = "{DEFAULT_EMBEDDING_MODEL_PATH}"
dims = 512

[memory.vector_store]
host = "127.0.0.1"
port = 6333
grpc_port = 6334
storage_path = "{DEFAULT_QDRANT_STORAGE_PATH}"
container_name = "zhou-qdrant"
image = "qdrant/qdrant"
auto_start = true

[memory.model_worker]
enabled = false
api_key = ""
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
temperature = 0.1
max_tokens = 1200
top_p = 0.1
top_k = 1
mode = "async"
generate_reasoning_summary = true
generate_session_memory = true
generate_folder_memory = true
allow_model_decide_promotion = true
promotion_min_turns = 3

[global_memory.archive]
enabled = true
root_dir = "{DEFAULT_GLOBAL_ARCHIVE_ROOT}"
format = "jsonl"
sync_on_turn = true
include_tool_calls = true
include_tags = true
include_reasoning_summary = false
'''

def default_project_config_contents() -> str:
    return '''[memory]
enabled = true

[memory.identity]
user_id = "default_user"
agent_id = "zhou_agent"
collection_name = "agent_memory_main"
'''

def ensure_user_config_file() -> Path | None:
    home_dir = user_home_dir()
    if home_dir is None:
        return None
    config_path = home_dir / USER_CONFIG_RELATIVE_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(default_user_config_contents(), encoding="utf-8")
    return config_path

def ensure_project_config_file(cwd: Path) -> Path:
    config_path = cwd / PROJECT_CONFIG_RELATIVE_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if not config_path.exists():
        config_path.write_text(default_project_config_contents(), encoding="utf-8")
    return config_path

def user_home_dir() -> Path | None:
    if os.environ.get("USERPROFILE"): return Path(os.environ["USERPROFILE"])
    if os.environ.get("HOME"): return Path(os.environ["HOME"])
    return None

def parse_key_value_text(content: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line: continue
        key, value = line.split("=", 1)
        parsed[key.strip().lower()] = value.strip().strip('"')
    return parsed

def normalize_string(value: object) -> str:
    return "" if value is None else str(value).strip()

def to_bool(value: object, *, default: bool) -> bool:
    if value is None: return default
    if isinstance(value, bool): return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}: return True
    if normalized in {"0", "false", "no", "off"}: return False
    return default

def to_int(value: object, *, default: int) -> int:
    try: return default if value is None else int(value)
    except (TypeError, ValueError): return default

def to_float(value: object, *, default: float) -> float:
    try: return default if value is None else float(value)
    except (TypeError, ValueError): return default
