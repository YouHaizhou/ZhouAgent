from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable
from uuid import uuid4
from .tools import ToolRegistry, empty_tool_registry
from .memory.enrichment import derive_turn_tags, derive_memory_candidates, normalize_string_list
@dataclass(slots=True)
class Skill: name:str;title:str;description:str;tags:list[str];body:str;path:Path
@dataclass(slots=True)
class ToolCallRecord: name:str;arguments:str
@dataclass(slots=True)
class TurnRecord:
    session_id:str;timestamp:str;user:str;assistant:str;reasoning_summary:str="";tool_calls:list[ToolCallRecord]=field(default_factory=list);tags:list[str]=field(default_factory=list);memory_candidates:list[str]=field(default_factory=list)
    def to_storage_dict(self)->dict[str,object]:
        payload=asdict(self);payload["tool_calls"]=[asdict(t) for t in self.tool_calls];return payload
@dataclass(slots=True)
class SessionState:
    cwd:Path;session_id:str=field(default_factory=lambda:uuid4().hex);started_at:str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat());last_active_at:str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat());available_skills:list[Skill]=field(default_factory=list);active_skills:list[Skill]=field(default_factory=list);pending_active_skill_names:list[str]=field(default_factory=list);tool_registry:ToolRegistry=field(default_factory=empty_tool_registry);message_history:list[dict[str,object]]=field(default_factory=list)
    @classmethod
    def load_latest_or_new(cls,cwd:Path)->"SessionState":
        latest=cls.load_latest(cwd);return latest if latest is not None else cls(cwd=cwd)
    @classmethod
    def load_latest(cls,cwd:Path)->"SessionState|None":
        root=cwd/".zhou"/"session"
        if not root.is_dir():return None
        candidates:list[tuple[str,Path]]=[]
        for child in root.iterdir():
            meta_path=child/"meta.json"
            if not child.is_dir() or not meta_path.is_file():continue
            try:meta=json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:continue
            candidates.append((str(meta.get("last_active_at") or meta.get("started_at") or ""),child))
        if not candidates:return None
        _,latest_dir=max(candidates,key=lambda item:item[0]);return cls.from_storage(cwd,latest_dir.name)
    @classmethod
    def from_storage(cls,cwd:Path,session_id:str)->"SessionState":
        root=cwd/".zhou"/"session"/session_id;meta_path=root/"meta.json";turns_path=root/"turns.jsonl";meta:dict[str,object]={}
        if meta_path.is_file():
            try:meta=json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:meta={}
        state=cls(cwd=cwd,session_id=str(meta.get("session_id") or session_id),started_at=str(meta.get("started_at") or datetime.now(timezone.utc).isoformat()),last_active_at=str(meta.get("last_active_at") or meta.get("started_at") or datetime.now(timezone.utc).isoformat()),pending_active_skill_names=parse_string_list(meta.get("active_skill_names")))
        state.message_history=load_message_history(turns_path);return state
    def set_available_skills(self,skills:Iterable[Skill])->None:
        self.available_skills=list(skills);by_name={s.name:s for s in self.available_skills};desired=self.pending_active_skill_names or self.active_skill_names();self.active_skills=[by_name[n] for n in desired if n in by_name];self.pending_active_skill_names=self.active_skill_names()
    def set_active_skills_by_names(self,names:Iterable[str])->None:
        desired=list(names);by_name={s.name:s for s in self.available_skills};self.active_skills=[by_name[n] for n in desired if n in by_name];self.pending_active_skill_names=self.active_skill_names();self.touch();self.save()
    def active_skill_names(self)->list[str]:return [s.name for s in self.active_skills]
    def active_skill_titles(self)->list[str]:return [s.title for s in self.active_skills]
    def build_turn_messages(self,user_input:str,memory_context:str="")->list[dict[str,object]]:
        messages=list(self.message_history)
        if memory_context.strip():messages.append({"role":"system","content":memory_context.strip()})
        messages.append({"role":"user","content":user_input});return messages
    def append_assistant_turn(self,user_input:str,assistant_text:str)->None:
        self.message_history.append({"role":"user","content":user_input});self.message_history.append({"role":"assistant","content":assistant_text})
    def append_turn(self,turn:TurnRecord)->None:
        self.append_assistant_turn(turn.user,turn.assistant);self.append_turn_to_storage(turn);self.touch();self.save()
    def replace_turn(self,turn:TurnRecord)->bool:
        turns=load_turn_records(self.turns_path());replaced=False;updated:list[TurnRecord]=[]
        for item in turns:
            if item.session_id==turn.session_id and item.timestamp==turn.timestamp:updated.append(turn);replaced=True
            else:updated.append(item)
        if not replaced:return False
        self.turns_path().write_text("".join(json.dumps(item.to_storage_dict(),ensure_ascii=False)+"\n" for item in updated),encoding="utf-8")
        self.message_history=load_message_history(self.turns_path());self.touch();self.save();return True
    def clear_history(self)->None:self.message_history.clear();self.touch();self.save()
    def storage_root(self)->Path:return self.cwd/".zhou"/"session"/self.session_id
    def meta_path(self)->Path:return self.storage_root()/"meta.json"
    def turns_path(self)->Path:return self.storage_root()/"turns.jsonl"
    def touch(self)->None:self.last_active_at=datetime.now(timezone.utc).isoformat()
    def meta_payload(self)->dict[str,object]:return {"session_id":self.session_id,"cwd":str(self.cwd),"started_at":self.started_at,"last_active_at":self.last_active_at,"active_skill_names":self.pending_active_skill_names or self.active_skill_names()}
    def ensure_storage(self)->None:
        self.storage_root().mkdir(parents=True,exist_ok=True);self.meta_path().write_text(json.dumps(self.meta_payload(),ensure_ascii=False,indent=2),encoding="utf-8")
        if not self.turns_path().exists():self.turns_path().write_text("",encoding="utf-8")
    def save(self)->None:self.ensure_storage()
    def append_turn_to_storage(self,turn:TurnRecord)->None:
        with self.turns_path().open("a",encoding="utf-8") as fh:fh.write(json.dumps(turn.to_storage_dict(),ensure_ascii=False)+"\n")
def build_turn_record(*,session_id:str,user_input:str,assistant_text:str,reasoning_summary:str="",tool_calls:Iterable[dict[str,object]]=(),tags:Iterable[str]=(),memory_candidates:Iterable[str]=(),auto_enrich:bool=True)->TurnRecord:
    calls=[ToolCallRecord(name=str(i.get("name") or "").strip(),arguments=str(i.get("arguments") or "{}").strip() or "{}") for i in tool_calls if str(i.get("name") or "").strip()]
    derived_tags=derive_turn_tags(user_input,assistant_text,reasoning_summary,calls) if auto_enrich else []
    derived_candidates=derive_memory_candidates(user_input,assistant_text,reasoning_summary,calls) if auto_enrich else []
    return TurnRecord(session_id=session_id,timestamp=datetime.now(timezone.utc).isoformat(),user=user_input,assistant=assistant_text,reasoning_summary=normalize_summary(reasoning_summary),tool_calls=calls,tags=normalize_string_list([*tags,*derived_tags]),memory_candidates=normalize_string_list([*memory_candidates,*derived_candidates]))

def parse_string_list(value:object)->list[str]:return [str(i).strip() for i in value if str(i).strip()] if isinstance(value,list) else []

def normalize_summary(value:str,max_length:int=400)->str:
    compact=" ".join(str(value).split()).strip();return compact if len(compact)<=max_length else compact[:max_length-1].rstrip()+"…"
def load_message_history(turns_path:Path,limit_turns:int=3)->list[dict[str,object]]:
    history:list[dict[str,object]]=[]
    turns=load_turn_records(turns_path)
    for turn in turns[-limit_turns:]:
        if turn.user:history.append({"role":"user","content":turn.user})
        if turn.assistant:history.append({"role":"assistant","content":turn.assistant})
    return history
def load_turn_records(turns_path:Path)->list[TurnRecord]:
    if not turns_path.is_file():return []
    turns:list[TurnRecord]=[]
    for raw_line in turns_path.read_text(encoding="utf-8").splitlines():
        line=raw_line.strip()
        if not line:continue
        try:record=json.loads(line)
        except json.JSONDecodeError:continue
        turn=parse_turn_record(record)
        if turn is not None:turns.append(turn)
    return turns
def parse_turn_record(record:object)->TurnRecord|None:
    if not isinstance(record,dict):return None
    user_text=str(record.get("user") or "").strip();assistant_text=str(record.get("assistant") or "").strip()
    if not user_text and not assistant_text:return None
    parsed_calls:list[ToolCallRecord]=[];raw_calls=record.get("tool_calls")
    if isinstance(raw_calls,list):
        for item in raw_calls:
            if isinstance(item,dict) and str(item.get("name") or "").strip():parsed_calls.append(ToolCallRecord(name=str(item.get("name") or "").strip(),arguments=str(item.get("arguments") or "{}").strip() or "{}"))
    return TurnRecord(session_id=str(record.get("session_id") or "").strip(),timestamp=str(record.get("timestamp") or "").strip(),user=user_text,assistant=assistant_text,reasoning_summary=normalize_summary(str(record.get("reasoning_summary") or "")),tool_calls=parsed_calls,tags=parse_string_list(record.get("tags")),memory_candidates=parse_string_list(record.get("memory_candidates")))
