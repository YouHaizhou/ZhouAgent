from __future__ import annotations
from pathlib import Path
import os
import json
import subprocess
from .core.commands import CommandType, parse_command
from .core.config import AppConfig, ensure_project_config_file, ensure_user_config_file
from .core.errors import ZhouError
from .core.llm import LlmClient
from .global_archive import build_global_archive_writer
from .memory.manager import Mem0MemoryManager, NullMemoryManager, MemoryKind, MemoryScope, apply_enriched_result, format_memory_context, normalize_cwd
from .memory.commands import handle_memory_command
from .memory.model import MemoryJobResult, MemoryModelClient, MemoryModelJob, MemoryModelWorker
from .session import SessionState, TurnRecord, build_turn_record, load_turn_records
from .skills import build_skill_system_prompt, discover_skills
from .tools import ToolDescriptor, call_tool, discover_tool_registry
from .tui import SkillPickerResult, append_answer_delta, begin_answer_stream, end_answer_stream, finish_open_streams, open_tools_screen, pick_skills, render_stream_event
AGENT_MARKDOWN_PATH="Agent.md"
DEFAULT_AGENT_MARKDOWN="""<!--
这个文件用于定义当前项目的基础 Agent 提示词。
该版本仅服务主对话处理模型，不负责记忆写入、记忆提升或长期记忆决策。
-->

# Agent Profile

## Role
你是当前项目中的主对话处理 Agent。
你的核心职责是：理解用户当前请求，结合必要的工具与上下文，以低成本、高正确性和高可执行性的方式完成当前任务。

## Project Context
- 这是一个本地 Agent 项目，具备工具调用、技能系统、会话管理和后台异步记忆处理能力。
- 你的首要目标是处理“当前问题”，而不是主动设计或决策长期记忆存取。
- 记忆写入、记忆提升、记忆更新由独立的后台 memory model 负责。

## Behavioral Rules
- 先判断任务复杂度，再决定是否使用工具或长链路处理。
- 若不需要外部信息、文件读取或执行结果支持，优先直接回答。
- 工具调用应以“最少必要次数”为原则，避免重复调用、验证性调用和低收益调用。
- 除非确有必要，不要为了确认而再次调用相同或相近工具。
- 优先给出结论、最小修改方案或下一步动作，不要无目的展开。
- 若信息已足够，应尽快收敛并输出最终结果。
- 除用户明确要求外，不主动扩展到与当前任务无关的话题。

## Cost Control Rules
- 控制输出长度，避免生成冗长解释、重复表述和大段无用背景。
- 控制思考成本：简单任务使用简短推理，复杂任务再使用更深推理。
- 控制工具成本：一次能解决的问题不要拆成多次工具调用。
- 控制上下文成本：不要反复复述已知信息，不要引入不必要的历史上下文。
- 不主动为了“沉淀记忆”而展开额外描述；主回答以完成当前任务为准。

## Memory Boundary
- 你可以使用系统已经提供的记忆上下文来帮助回答当前问题。
- 你不负责决定哪些内容应写入长期记忆。
- 你不负责设计记忆 revision、promotion、merge 或 skip 策略。
- 这些记忆相关决策交由后台异步 memory model 处理。

## Output Preferences
- 默认使用中文。
- 先给结论，再给必要解释。
- 输出应简洁、直接、可执行。
- 代码相关问题优先给出定位、原因、修改点和验证方式。
- 若存在多种方案，优先给出成本最低、实现最直接、风险最可控的方案。

## Out of Scope
- 不主动进行与当前任务无关的长篇教学式展开。
- 不主动进行高成本的多轮探索，除非任务收益明显大于成本。
- 不主动生成大段重复内容、无依据判断或形式化空话。
- 不主动承担记忆写入、长期记忆提升或用户画像归纳职责。
"""
RESET="\033[0m";DIM="\033[2m";ACCENT="\033[38;5;153m";BLUE="\033[38;5;117m";GREEN="\033[38;5;48m";GRAY="\033[38;5;245m";RED="\033[38;5;203m"
WORDMARK=[f"{ACCENT}███████╗{RESET} {ACCENT}██╗  ██╗{RESET} {ACCENT} ██████╗ {RESET} {ACCENT}██╗   ██╗{RESET}",f"{ACCENT}╚══███╔╝{RESET} {ACCENT}██║  ██║{RESET} {ACCENT}██╔═══██╗{RESET} {ACCENT}██║   ██║{RESET}",f"{ACCENT}  ███╔╝ {RESET} {ACCENT}███████║{RESET} {ACCENT}██║   ██║{RESET} {ACCENT}██║   ██║{RESET}",f"{ACCENT} ███╔╝  {RESET} {ACCENT}██╔══██║{RESET} {ACCENT}██║   ██║{RESET} {ACCENT}██║   ██║{RESET}",f"{ACCENT}███████╗{RESET} {ACCENT}██║  ██║{RESET} {ACCENT}╚██████╔╝{RESET} {ACCENT}╚██████╔╝{RESET}",f"{ACCENT}╚══════╝{RESET} {ACCENT}╚═╝  ╚═╝{RESET} {ACCENT} ╚═════╝ {RESET} {ACCENT} ╚═════╝ {RESET}"]
WELCOME_HINTS=(f"{DIM}输入内容开始对话{RESET}",f"{DIM}输入 /skills 管理技能{RESET}",f"{DIM}输入 /tools 查看工具{RESET}",f"{DIM}输入 /memory help 查看记忆命令{RESET}",f"{DIM}输入 /exit 退出{RESET}")
def main()->None:
    try:run()
    except ZhouError as error:print(f"\nerror: {error}");raise SystemExit(1) from error
    except KeyboardInterrupt:print("\n\nbye.");raise SystemExit(0)
def render_welcome()->None:
    print();[print(f"  {line}") for line in WORDMARK];print();[print(f"  {hint}") for hint in WELCOME_HINTS];print()
def ensure_project_layout(cwd:Path)->None:
    project_root=cwd/".zhou";(project_root/"skills").mkdir(parents=True,exist_ok=True);(project_root/"session").mkdir(parents=True,exist_ok=True);ensure_agent_markdown(cwd)
def ensure_agent_markdown(cwd:Path)->Path:
    path=cwd/AGENT_MARKDOWN_PATH
    if not path.exists():path.write_text(DEFAULT_AGENT_MARKDOWN,encoding="utf-8")
    return path
def ensure_qdrant_container(config:AppConfig)->None:
    if not config.memory.enabled or not config.memory.qdrant_auto_start:return
    try:
        docker_check=subprocess.run(["docker","info"],capture_output=True,text=True,timeout=15)
    except FileNotFoundError as exc:
        raise ZhouError("未检测到 docker 命令，请先安装 Docker Desktop 并确保 docker 在 PATH 中。") from exc
    except Exception as exc:
        raise ZhouError(f"检测 Docker 状态失败: {exc}") from exc
    if docker_check.returncode!=0:
        detail=(docker_check.stderr or docker_check.stdout or "").strip()
        raise ZhouError("Docker Desktop 未启动或 Docker daemon 不可用，请先启动 Docker Desktop 后再运行 zhou。"+(f"\n{detail}" if detail else ""))
    storage=Path(config.memory.qdrant_storage_path).expanduser();storage.mkdir(parents=True,exist_ok=True)
    name=config.memory.qdrant_container_name;image=config.memory.qdrant_image;host=config.memory.qdrant_host;http_port=str(config.memory.qdrant_port);grpc_port=str(config.memory.qdrant_grpc_port)
    inspect_result=subprocess.run(["docker","inspect","-f","{{.State.Running}}",name],capture_output=True,text=True,timeout=15)
    state=(inspect_result.stdout or "").strip().lower()
    if state=="true":return
    if state=="false":
        start_result=subprocess.run(["docker","start",name],capture_output=True,text=True,timeout=30)
        if start_result.returncode==0:return
        detail=(start_result.stderr or start_result.stdout or "").strip()
        raise ZhouError(f"无法启动 Qdrant 容器: {name}"+(f"\n{detail}" if detail else ""))
    if host not in {"127.0.0.1","localhost"}:return
    run_result=subprocess.run(["docker","run","-d","--name",name,"-p",f"{http_port}:6333","-p",f"{grpc_port}:6334","-v",f"{storage}:/qdrant/storage",image],capture_output=True,text=True,timeout=60)
    if run_result.returncode!=0:
        detail=(run_result.stderr or run_result.stdout or "").strip()
        raise ZhouError(f"无法创建 Qdrant 容器: {name}"+(f"\n{detail}" if detail else ""))
def load_base_system_prompt(cwd:Path)->str:
    content=ensure_agent_markdown(cwd).read_text(encoding="utf-8").strip();return content or "你是 zhou，一个简洁、友好、可靠的中文 AI 助手。请优先使用中文回答，表达清晰，不要冗长。"
def build_memory_manager(config:AppConfig):return Mem0MemoryManager(config.memory) if config.memory.enabled else NullMemoryManager()
def refresh_skills(session:SessionState)->None:session.set_available_skills(discover_skills(session.cwd))
def refresh_tools(session:SessionState)->None:session.tool_registry=discover_tool_registry(session.cwd)
def migrate_existing_turns(session:SessionState)->None:
    turns=load_turn_records(session.turns_path())
    if not turns:return
    original=session.turns_path().read_text(encoding="utf-8")
    if '"reasoning_summary": "' in original and '"tags": [' in original and '"memory_candidates": [' in original:return
    rebuilt=[build_turn_record(session_id=turn.session_id or session.session_id,user_input=turn.user,assistant_text=turn.assistant,reasoning_summary=turn.reasoning_summary,tool_calls=[{"name":call.name,"arguments":call.arguments} for call in turn.tool_calls],tags=turn.tags,memory_candidates=turn.memory_candidates) for turn in turns]
    session.turns_path().write_text("".join(json.dumps(turn.to_storage_dict(),ensure_ascii=False)+"\n" for turn in rebuilt),encoding="utf-8")
def render_skills_summary(session:SessionState,result:SkillPickerResult)->None:
    label="applied" if result==SkillPickerResult.CONFIRMED else "cancelled";color=GREEN if result==SkillPickerResult.CONFIRMED else GRAY
    print(f"{BLUE}Skills{RESET}");print(f"  Result{' ' * 16}{color}{label}{RESET}");print()
    if result!=SkillPickerResult.CONFIRMED:return
    print(f"{BLUE}Skills{RESET}");print(f"  Session active{' ' * 8}{GREEN}{len(session.active_skills)}{RESET}");print()
    for idx,skill in enumerate(session.active_skills,start=1):print(f"  {idx}. {GREEN}[●]{RESET} {GREEN}{skill.name}{RESET}");print(f"     {GRAY}{skill.path}{RESET}")
    print()
def safe_tool_name(tool:ToolDescriptor)->str:return f"{tool.source_id.replace('-', '_')}__{tool.name.replace('-', '_').replace('.', '_')}"
def open_skills_picker(session:SessionState)->None:
    refresh_skills(session);result,selected_names=pick_skills(session.available_skills,session.active_skill_names())
    if result==SkillPickerResult.CONFIRMED:session.set_active_skills_by_names(selected_names)
    render_skills_summary(session,result)
def build_system_prompt(session:SessionState)->str:
    base=load_base_system_prompt(session.cwd);skill_prompt=build_skill_system_prompt(session.active_skills);return base if not skill_prompt else f"{base}\n\n{skill_prompt}"
def build_tool_executor(session:SessionState):
    name_map={safe_tool_name(tool):tool.qualified_name for tool in session.tool_registry.tools if tool.enabled}
    def _execute(qualified_name:str,arguments_json:str)->str:return call_tool(session.tool_registry,name_map.get(qualified_name,qualified_name),arguments_json,session.cwd)
    return _execute
def build_openai_tools(session:SessionState)->list[dict[str,object]]:return [tool_to_openai_function(tool) for tool in session.tool_registry.tools if tool.enabled]
def tool_to_openai_function(tool:ToolDescriptor)->dict[str,object]:return {"type":"function","function":{"name":safe_tool_name(tool),"description":tool.description,"parameters":tool.input_schema or {"type":"object","properties":{}}}}


def _bootstrap():
    """初始化 Zhou 运行时环境：配置、布局、Docker、记忆、会话。

    返回启动后的核心资源句柄；不会进入 REPL。
    """
    # ---- 复用 run() 中的所有 setup 逻辑 ----
    cwd = Path.cwd()
    ensure_project_layout(cwd)
    ensure_user_config_file()
    ensure_project_config_file(cwd)
    config = AppConfig.load()
    ensure_qdrant_container(config)
    client = LlmClient(config)
    memory = build_memory_manager(config)
    archive_writer = build_global_archive_writer(config.global_memory.archive)
    session = SessionState.load_latest_or_new(cwd)
    session.ensure_storage()
    migrate_existing_turns(session)
    refresh_skills(session)
    refresh_tools(session)
    worker = MemoryModelWorker(MemoryModelClient(config))
    return cwd, config, client, memory, archive_writer, session, worker


def _handle_turn(
    user_input: str,
    *,
    session: SessionState,
    client: LlmClient,
    memory,
    archive_writer,
    worker: MemoryModelWorker,
) -> None:
    """处理单轮对话：LLM 调用 → 流渲染 → 记忆持久化 + 异步富化。"""
    refresh_tools(session)
    normalized_cwd = normalize_cwd(str(session.cwd)) or str(session.cwd)

    search_results = memory.search_all_scopes(
        user_input, cwd=normalized_cwd, session_id=session.session_id
    )
    memory_context = format_memory_context(search_results)
    system_prompt = build_system_prompt(session)
    openai_tools = build_openai_tools(session)
    tool_executor = build_tool_executor(session) if openai_tools else None
    turn_messages = session.build_turn_messages(user_input, memory_context=memory_context)

    stream_state: dict[str, object] = {
        "reasoning_parts": [],
        "reasoning_text": "",
        "reasoning_summary": "",
        "answer_open": False,
        "answer_parts": [],
        "tool_calls": [],
    }

    for event in client.respond_turn(system_prompt, turn_messages, openai_tools, tool_executor):
        render_stream_event(event, stream_state)

    finish_open_streams(stream_state)

    answer_text = "".join(stream_state["answer_parts"]).strip()

    if not answer_text:
        answer_text = "抱歉，我这次没有生成有效回复。"
        begin_answer_stream()
        append_answer_delta(answer_text)
        end_answer_stream()

    reasoning_summary = str(stream_state["reasoning_summary"] or "")

    turn = build_turn_record(
        session_id=session.session_id,
        user_input=user_input,
        assistant_text=answer_text,
        reasoning_summary=reasoning_summary,
        tool_calls=stream_state["tool_calls"],
    )
    session.append_turn(turn)
    archive_writer.append_turn(cwd=session.cwd, turn=turn)

    def _on_memory_complete(_job_result: MemoryJobResult) -> None:
        return None

    # ---- 记忆模型异步富化 ----
    existing_session_episodic = memory.search_memory(
        turn.user,
        scope=MemoryScope.SESSION,
        cwd=normalized_cwd,
        session_id=session.session_id,
        kind=MemoryKind.SHORT_TERM,
        limit=3,
    ).top_contents()
    existing_session_semantic = memory.search_memory(
        turn.assistant,
        scope=MemoryScope.SESSION,
        cwd=normalized_cwd,
        session_id=session.session_id,
        kind=MemoryKind.SHORT_TERM,
        limit=3,
    ).top_contents()
    existing_folder_procedural = memory.search_memory(
        turn.reasoning_summary or turn.user,
        scope=MemoryScope.FOLDER,
        cwd=normalized_cwd,
        kind=MemoryKind.LONG_TERM,
        limit=3,
    ).top_contents()

    submitted = worker.submit(
        MemoryModelJob(
            session_cwd=normalized_cwd,
            session_id=session.session_id,
            turn=turn,
            existing_session_episodic=existing_session_episodic,
            existing_session_semantic=existing_session_semantic,
            existing_folder_procedural=existing_folder_procedural,
            callback=lambda enriched: apply_enriched_result(session, memory, enriched),
            on_complete=_on_memory_complete,
        )
    )
    if not submitted:
        return


def run() -> None:
    """Zhou agent 主入口：启动 → 欢迎 → REPL 循环。"""
    cwd, config, client, memory, archive_writer, session, worker = _bootstrap()
    render_welcome()

    try:
        while True:
            user_input = input("> ").strip()
            if not user_input:
                continue

            command = parse_command(user_input)
            if command == CommandType.EXIT:
                print("\nbye.")
                break
            if command == CommandType.SKILLS:
                open_skills_picker(session)
                continue
            if command == CommandType.TOOLS:
                refresh_tools(session)
                open_tools_screen(session.tool_registry)
                continue
            if command == CommandType.MEMORY:
                handle_memory_command(user_input, session, memory)
                continue

            try:
                _handle_turn(
                    user_input,
                    session=session,
                    client=client,
                    memory=memory,
                    archive_writer=archive_writer,
                    worker=worker,
                )
            except ZhouError:
                raise
            except Exception as exc:
                print(f"\n{RED}error:{RESET} {exc}")
    finally:
        worker.shutdown()
        session.save()
        client.close()
