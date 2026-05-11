from __future__ import annotations
from dataclasses import dataclass,field
from enum import Enum
from pathlib import Path
from typing import Any,Protocol
from ..core.config import MemorySettings
from ..core.errors import MemoryInitError
from ..session import SessionState, TurnRecord
try:
    from mem0 import Memory
    from mem0.configs.base import MemoryConfig
except ImportError:
    Memory=None;MemoryConfig=None
class MemoryScope(str,Enum):GLOBAL="global";FOLDER="folder";SESSION="session"
class MemoryKind(str,Enum):KNOWLEDGE="knowledge";LONG_TERM="long_term";SHORT_TERM="short_term"
class MemoryClass(str,Enum):EPISODIC="episodic";SEMANTIC="semantic";PROCEDURAL="procedural"
@dataclass(slots=True)
class MemoryRecord:content:str;scope:MemoryScope;kind:MemoryKind;memory_class:MemoryClass;cwd:str|None=None;session_id:str|None=None;user_id:str|None=None;agent_id:str|None=None;importance:float=0.0;source:str="conversation";metadata:dict[str,Any]=field(default_factory=dict)
@dataclass(slots=True)
class MemorySearchHit:record:MemoryRecord;score:float
@dataclass(slots=True)
class MemorySearchResult:
    hits:list[MemorySearchHit]=field(default_factory=list)
    def top_contents(self)->list[str]:return [i.record.content for i in self.hits]
    def is_empty(self)->bool:return not self.hits
@dataclass(slots=True)
class MemoryApplyStatus:
    turn_replaced:bool=False
    session_episodic_action:str="skip"
    session_semantic_action:str="skip"
    folder_procedural_action:str="skip"
    error:str=""
    def summary_line(self)->str:
        if self.error.strip():return f"[memory] failed: {self.error.strip()}"
        return f"[memory] session_episodic={self.session_episodic_action} session_semantic={self.session_semantic_action} folder_procedural={self.folder_procedural_action}"
class MemoryManager(Protocol):
    def write_memory(self,record:MemoryRecord)->None: ...
    def write_versioned_memory(self,record:MemoryRecord,*,memory_key:str,revision:int)->None: ...
    def next_memory_revision(self,*,memory_key:str,cwd:str|None,session_id:str|None,scope:MemoryScope,kind:MemoryKind)->int: ...
    def search_memory(self,query:str,*,scope:MemoryScope|None=None,cwd:str|None=None,session_id:str|None=None,kind:MemoryKind|None=None,limit:int=8)->MemorySearchResult: ...
    def recent_memory(self,*,scope:MemoryScope|None=None,cwd:str|None=None,session_id:str|None=None,kind:MemoryKind|None=None,limit:int=8)->MemorySearchResult: ...
    def search_all_scopes(self,query:str,*,cwd:str,session_id:str,limit_per_scope:int=4)->dict[str,MemorySearchResult]: ...
    def write_session_turn(self,*,cwd:str,turn:TurnRecord)->None: ...
    def write_global_knowledge(self,*,content:str,source:str="knowledge_base")->None: ...
class NullMemoryManager:
    def write_memory(self,record:MemoryRecord)->None:return None
    def write_versioned_memory(self,record:MemoryRecord,*,memory_key:str,revision:int)->None:return None
    def next_memory_revision(self,*,memory_key:str,cwd:str|None,session_id:str|None,scope:MemoryScope,kind:MemoryKind)->int:return 1
    def search_memory(self,query:str,*,scope:MemoryScope|None=None,cwd:str|None=None,session_id:str|None=None,kind:MemoryKind|None=None,limit:int=8)->MemorySearchResult:return MemorySearchResult()
    def recent_memory(self,*,scope:MemoryScope|None=None,cwd:str|None=None,session_id:str|None=None,kind:MemoryKind|None=None,limit:int=8)->MemorySearchResult:return MemorySearchResult()
    def search_all_scopes(self,query:str,*,cwd:str,session_id:str,limit_per_scope:int=4)->dict[str,MemorySearchResult]:e=MemorySearchResult();return {MemoryScope.SESSION.value:e,MemoryScope.FOLDER.value:e,MemoryScope.GLOBAL.value:e}
    def write_session_turn(self,*,cwd:str,turn:TurnRecord)->None:return None
    def write_global_knowledge(self,*,content:str,source:str="knowledge_base")->None:return None
class Mem0MemoryManager:
    def __init__(self,settings:MemorySettings)->None:
        if Memory is None or MemoryConfig is None:raise MemoryInitError("未安装 mem0 依赖，请先安装项目依赖。")
        self.settings=settings;vector_store_config={"collection_name":settings.collection_name,"host":settings.qdrant_host,"port":settings.qdrant_port,"embedding_model_dims":settings.embedding_dims,"on_disk":True}
        config=MemoryConfig(llm={"provider":"deepseek","config":{"api_key":settings.api_key,"model":settings.deepseek_model,"deepseek_base_url":settings.deepseek_base_url,"temperature":settings.deepseek_temperature,"max_tokens":settings.deepseek_max_tokens,"top_p":settings.deepseek_top_p,"top_k":settings.deepseek_top_k}},embedder={"provider":"huggingface","config":{"model":settings.embedding_model,"model_kwargs":{}}},vector_store={"provider":"qdrant","config":vector_store_config},version="v1.1")
        try:self.client=Memory(config)
        except Exception as exc:raise MemoryInitError(f"初始化 mem0 失败: {exc}") from exc
    def write_memory(self,record:MemoryRecord)->None:
        normalized_record=normalize_memory_record(record)
        try:self.client.add(normalized_record.content,user_id=normalized_record.user_id or self.settings.user_id,agent_id=normalized_record.agent_id or self.settings.agent_id,run_id=normalized_record.session_id,metadata=build_metadata(normalized_record),infer=False)
        except Exception as exc:raise MemoryInitError(f"写入记忆失败: {exc}") from exc
    def write_versioned_memory(self,record:MemoryRecord,*,memory_key:str,revision:int)->None:
        meta=dict(record.metadata);meta.update({"memory_key":memory_key,"revision":revision})
        self.write_memory(MemoryRecord(content=record.content,scope=record.scope,kind=record.kind,memory_class=record.memory_class,cwd=record.cwd,session_id=record.session_id,user_id=record.user_id,agent_id=record.agent_id,importance=record.importance,source=record.source,metadata=meta))
    def next_memory_revision(self,*,memory_key:str,cwd:str|None,session_id:str|None,scope:MemoryScope,kind:MemoryKind)->int:
        result=self.search_memory(memory_key,scope=scope,cwd=cwd,session_id=session_id,kind=kind,limit=8);highest=0
        for hit in result.hits:
            if str(hit.record.metadata.get("memory_key") or "")!=memory_key:continue
            try:highest=max(highest,int(hit.record.metadata.get("revision") or 0))
            except (TypeError,ValueError):continue
        return highest+1
    def search_memory(self,query:str,*,scope:MemoryScope|None=None,cwd:str|None=None,session_id:str|None=None,kind:MemoryKind|None=None,limit:int=8)->MemorySearchResult:
        normalized_cwd=normalize_cwd(cwd)
        try:raw=self.client.search(query=query,top_k=max(limit*3,limit),threshold=0.1,filters=build_filters(user_id=self.settings.user_id,agent_id=self.settings.agent_id,scope=scope,cwd=normalized_cwd,session_id=session_id,kind=kind))
        except Exception as exc:raise MemoryInitError(f"检索记忆失败: {exc}") from exc
        return collapse_memory_result(parse_search_result(raw),limit=limit)
    def recent_memory(self,*,scope:MemoryScope|None=None,cwd:str|None=None,session_id:str|None=None,kind:MemoryKind|None=None,limit:int=8)->MemorySearchResult:
        query=session_id or normalized_scope_query(scope) or "memory"
        return self.search_memory(query,scope=scope,cwd=cwd,session_id=session_id,kind=kind,limit=limit)
    def search_all_scopes(self,query:str,*,cwd:str,session_id:str,limit_per_scope:int=4)->dict[str,MemorySearchResult]:return {MemoryScope.SESSION.value:self.search_memory(query,scope=MemoryScope.SESSION,cwd=cwd,session_id=session_id,kind=MemoryKind.SHORT_TERM,limit=limit_per_scope),MemoryScope.FOLDER.value:self.search_memory(query,scope=MemoryScope.FOLDER,cwd=cwd,kind=MemoryKind.LONG_TERM,limit=limit_per_scope),MemoryScope.GLOBAL.value:self.search_memory(query,scope=MemoryScope.GLOBAL,kind=MemoryKind.KNOWLEDGE,limit=limit_per_scope)}
    def write_session_turn(self,*,cwd:str,turn:TurnRecord)->None:
        meta={"timestamp":turn.timestamp,"tags":list(turn.tags),"memory_candidates":list(turn.memory_candidates),"tool_names":[c.name for c in turn.tool_calls]}
        self.write_memory(MemoryRecord(content=format_turn_memory_content(turn),scope=MemoryScope.SESSION,kind=MemoryKind.SHORT_TERM,memory_class=MemoryClass.EPISODIC,cwd=cwd,session_id=turn.session_id,user_id=self.settings.user_id,agent_id=self.settings.agent_id,importance=1.0,source="conversation",metadata=meta))
    def write_global_knowledge(self,*,content:str,source:str="knowledge_base")->None:self.write_memory(MemoryRecord(content=content,scope=MemoryScope.GLOBAL,kind=MemoryKind.KNOWLEDGE,memory_class=MemoryClass.SEMANTIC,user_id=self.settings.user_id,agent_id=self.settings.agent_id,importance=0.8,source=source))
def format_turn_memory_content(turn:TurnRecord)->str:
    parts=[f"用户问题：{turn.user.strip()}"]
    if turn.reasoning_summary.strip():parts.append(f"推理摘要：{turn.reasoning_summary.strip()}")
    if turn.tool_calls:parts.append("工具调用："+", ".join(f"{c.name}({c.arguments})" for c in turn.tool_calls))
    parts.append(f"最终回答：{turn.assistant.strip()}")
    if turn.memory_candidates:parts.append("记忆候选："+"；".join(turn.memory_candidates))
    return "\n".join(parts)
def format_memory_context(search_results:dict[str,MemorySearchResult],*,max_items_per_scope:int=3,max_chars_per_item:int=220)->str:
    sections:list[str]=[];titles={MemoryScope.SESSION.value:"Session Memory",MemoryScope.FOLDER.value:"Project Memory",MemoryScope.GLOBAL.value:"Global Memory"}
    for scope in (MemoryScope.SESSION.value,MemoryScope.FOLDER.value,MemoryScope.GLOBAL.value):
        result=search_results.get(scope) or MemorySearchResult();lines=[]
        for hit in result.hits[:max_items_per_scope]:
            content=compact_memory_text(hit.record.content,max_chars=max_chars_per_item)
            if content:lines.append(f"- {content}")
        if lines:sections.append(f"[{titles[scope]}]\n"+"\n".join(lines))
    return "" if not sections else "以下是与当前请求相关的历史记忆，仅在有帮助时参考，不要盲从旧信息：\n\n"+"\n\n".join(sections)
def build_metadata(record:MemoryRecord)->dict[str,Any]:meta=dict(record.metadata);meta.update({"scope":record.scope.value,"kind":record.kind.value,"memory_class":record.memory_class.value,"cwd":normalize_cwd(record.cwd),"importance":record.importance,"source":record.source});return {k:v for k,v in meta.items() if v is not None}
def build_filters(*,user_id:str,agent_id:str,scope:MemoryScope|None,cwd:str|None,session_id:str|None,kind:MemoryKind|None)->dict[str,Any]:
    filters:dict[str,Any]={"user_id":user_id,"agent_id":agent_id}
    if session_id:filters["run_id"]=session_id
    if scope is not None:filters["scope"]=scope.value
    normalized_cwd=normalize_cwd(cwd)
    if normalized_cwd:filters["cwd"]=normalized_cwd
    if kind is not None:filters["kind"]=kind.value
    return filters
def parse_search_result(raw:object)->MemorySearchResult:
    if not isinstance(raw,dict) or not isinstance(raw.get("results"),list):return MemorySearchResult()
    hits:list[MemorySearchHit]=[]
    for item in raw["results"]:
        if not isinstance(item,dict):continue
        meta=item.get("metadata") if isinstance(item.get("metadata"),dict) else {}
        record=MemoryRecord(content=str(item.get("memory") or ""),scope=parse_scope(meta.get("scope")),kind=parse_kind(meta.get("kind")),memory_class=parse_memory_class(meta.get("memory_class")),cwd=normalize_cwd(string_or_none(meta.get("cwd"))),session_id=string_or_none(item.get("run_id")),user_id=string_or_none(item.get("user_id")),agent_id=string_or_none(item.get("agent_id")),importance=float(meta.get("importance") or 0.0),source=str(meta.get("source") or "conversation"),metadata=dict(meta))
        hits.append(MemorySearchHit(record=record,score=float(item.get("score") or 0.0)))
    return MemorySearchResult(hits=hits)
def collapse_memory_result(result:MemorySearchResult,*,limit:int)->MemorySearchResult:
    grouped:dict[str,MemorySearchHit]={};others:list[MemorySearchHit]=[]
    for hit in result.hits:
        key=str(hit.record.metadata.get("memory_key") or "").strip()
        if not key:others.append(hit);continue
        existing=grouped.get(key)
        if existing is None or safe_revision(hit)>safe_revision(existing) or (safe_revision(hit)==safe_revision(existing) and hit.score>=existing.score):grouped[key]=hit
    merged=list(grouped.values())+others;merged.sort(key=lambda i:(safe_revision(i),i.score),reverse=True)
    return MemorySearchResult(hits=merged[:limit])
def safe_revision(hit:MemorySearchHit)->int:
    try:return int(hit.record.metadata.get("revision") or 0)
    except (TypeError,ValueError):return 0
def compact_memory_text(content:str,*,max_chars:int)->str:
    compact=" ".join(str(content).split()).strip();return compact if len(compact)<=max_chars else compact[:max_chars-1].rstrip()+"…"

def normalize_cwd(cwd:str|None)->str|None:
    text=str(cwd or "").strip()
    if not text:return None
    normalized=Path(text).expanduser()
    try:normalized=normalized.resolve()
    except OSError:normalized=normalized.absolute()
    return normalized.as_posix().lower()

def normalize_memory_record(record:MemoryRecord)->MemoryRecord:
    return MemoryRecord(content=record.content,scope=record.scope,kind=record.kind,memory_class=record.memory_class,cwd=normalize_cwd(record.cwd),session_id=record.session_id,user_id=record.user_id,agent_id=record.agent_id,importance=record.importance,source=record.source,metadata=dict(record.metadata))

def normalized_scope_query(scope:MemoryScope|None)->str:
    if scope==MemoryScope.SESSION:return "session"
    if scope==MemoryScope.FOLDER:return "folder"
    if scope==MemoryScope.GLOBAL:return "global"
    return "memory"


def build_memory_key(*, scope: MemoryScope, memory_class: MemoryClass, session_id: str, decision_key: str) -> str:
    """Derive a stable key for versioned (upsert) memory records."""
    return f"{scope.value}:{memory_class.value}:{(decision_key.strip() or session_id)}"


def looks_like_procedural_memory(text: str) -> bool:
    compact = " ".join(str(text or "").split()).strip()
    if not compact:
        return False
    procedural_tokens = ("流程", "步骤", "排查", "检查", "先", "然后", "最后", "第1步", "第2步", "第3步", "第4步", "第5步", "第6步", "解决问题", "如何")
    if any(token in compact for token in procedural_tokens):
        return True
    return bool(__import__("re").search(r"(?:^|\s)[1-9][\.、]|第\d+步", compact))


def apply_enriched_result(session: SessionState, memory: Any, result: EnrichedTurnResult) -> MemoryApplyStatus:
    """Apply the async memory-model output back onto the session turn and memory store.

    This function was previously in ``main.py``; moved here because it operates
    exclusively on memory and session concerns.
    """
    from .model import EnrichedTurnResult  # local to avoid circular import at module level

    status=MemoryApplyStatus()
    turn = result.turn
    if not session.replace_turn(turn):
        status.error="turn_replace_failed"
        return status
    status.turn_replaced=True

    output = result.output
    user_id = getattr(memory, "settings", None).user_id if hasattr(memory, "settings") else None
    agent_id = getattr(memory, "settings", None).agent_id if hasattr(memory, "settings") else None

    session_episodic_changed = False
    has_tool_calls = bool(turn.tool_calls)

    if has_tool_calls and output.session_episodic.decision in {"insert", "update"} and output.session_episodic.content:
        key = build_memory_key(
            scope=MemoryScope.SESSION,
            memory_class=MemoryClass.EPISODIC,
            session_id=turn.session_id,
            decision_key=output.session_episodic.target_memory_key,
        )
        rev = memory.next_memory_revision(
            memory_key=key, cwd=str(session.cwd), session_id=turn.session_id,
            scope=MemoryScope.SESSION, kind=MemoryKind.SHORT_TERM,
        )
        memory.write_versioned_memory(
            MemoryRecord(
                content=output.session_episodic.content,
                scope=MemoryScope.SESSION,
                kind=MemoryKind.SHORT_TERM,
                memory_class=MemoryClass.EPISODIC,
                cwd=str(session.cwd),
                session_id=turn.session_id,
                user_id=user_id,
                agent_id=agent_id,
                importance=output.session_episodic.importance or 1.0,
                source="memory_model_session_episodic",
                metadata={
                    "decision": output.session_episodic.decision,
                    "reason": output.session_episodic.reason,
                    "memory_type": "session_episodic",
                },
            ),
            memory_key=key,
            revision=rev,
        )
        session_episodic_changed = True
        status.session_episodic_action=output.session_episodic.decision

    if output.session_semantic.decision in {"insert", "update"} and output.session_semantic.content and not looks_like_procedural_memory(output.session_semantic.content):
        key = build_memory_key(
            scope=MemoryScope.SESSION,
            memory_class=MemoryClass.SEMANTIC,
            session_id=turn.session_id,
            decision_key=output.session_semantic.target_memory_key,
        )
        rev = memory.next_memory_revision(
            memory_key=key, cwd=str(session.cwd), session_id=turn.session_id,
            scope=MemoryScope.SESSION, kind=MemoryKind.SHORT_TERM,
        )
        memory.write_versioned_memory(
            MemoryRecord(
                content=output.session_semantic.content,
                scope=MemoryScope.SESSION,
                kind=MemoryKind.SHORT_TERM,
                memory_class=MemoryClass.SEMANTIC,
                cwd=str(session.cwd),
                session_id=turn.session_id,
                user_id=user_id,
                agent_id=agent_id,
                importance=output.session_semantic.importance or 0.8,
                source="memory_model_session_semantic",
                metadata={
                    "decision": output.session_semantic.decision,
                    "reason": output.session_semantic.reason,
                    "memory_type": "session_semantic",
                },
            ),
            memory_key=key,
            revision=rev,
        )
        status.session_semantic_action=output.session_semantic.decision

    if output.folder_procedural.decision in {"insert", "update"} and output.folder_procedural.content:
        key = build_memory_key(
            scope=MemoryScope.FOLDER,
            memory_class=MemoryClass.PROCEDURAL,
            session_id=turn.session_id,
            decision_key=output.folder_procedural.target_memory_key,
        )
        rev = memory.next_memory_revision(
            memory_key=key, cwd=str(session.cwd), session_id=turn.session_id,
            scope=MemoryScope.FOLDER, kind=MemoryKind.LONG_TERM,
        )
        memory.write_versioned_memory(
            MemoryRecord(
                content=output.folder_procedural.content,
                scope=MemoryScope.FOLDER,
                kind=MemoryKind.LONG_TERM,
                memory_class=MemoryClass.PROCEDURAL,
                cwd=str(session.cwd),
                session_id=turn.session_id,
                user_id=user_id,
                agent_id=agent_id,
                importance=output.folder_procedural.importance or 0.8,
                source="memory_model_folder_procedural",
                metadata={
                    "decision": output.folder_procedural.decision,
                    "reason": output.folder_procedural.reason,
                    "memory_type": "folder_procedural",
                },
            ),
            memory_key=key,
            revision=rev,
        )
        status.folder_procedural_action=output.folder_procedural.decision
    return status

def parse_scope(value:object)->MemoryScope:
    try:return MemoryScope(str(value or MemoryScope.SESSION.value))
    except ValueError:return MemoryScope.SESSION
def parse_kind(value:object)->MemoryKind:
    try:return MemoryKind(str(value or MemoryKind.SHORT_TERM.value))
    except ValueError:return MemoryKind.SHORT_TERM
def parse_memory_class(value:object)->MemoryClass:
    try:return MemoryClass(str(value or MemoryClass.EPISODIC.value))
    except ValueError:return MemoryClass.EPISODIC
def string_or_none(value:object)->str|None:
    text=str(value).strip() if value is not None else "";return text or None
