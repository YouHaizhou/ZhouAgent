from __future__ import annotations
from dataclasses import dataclass,field
import json,queue,re,threading
from pathlib import Path
from typing import Any
import httpx
from ..core.config import AppConfig,MemoryModelSettings
from ..core.errors import ApiRequestError
from ..session import TurnRecord,build_turn_record
from .manager import MemoryApplyStatus


PROJECT_LOGS_DIRNAME = ".zhou/logs"
MEMORY_MODEL_LOG_FILENAME = "memory-model.jsonl"
@dataclass(slots=True)
class MemoryDecisionDraft:
    decision:str="skip"
    target_memory_key:str=""
    content:str=""
    importance:float=0.0
    reason:str=""
    provided:bool=False
    invalid_decision:bool=False
@dataclass(slots=True)
class MemoryModelOutput:
    reasoning_summary:str=""
    tags:list[str]=field(default_factory=list)
    memory_candidates:list[str]=field(default_factory=list)
    session_episodic:MemoryDecisionDraft=field(default_factory=MemoryDecisionDraft)
    session_semantic:MemoryDecisionDraft=field(default_factory=MemoryDecisionDraft)
    folder_procedural:MemoryDecisionDraft=field(default_factory=MemoryDecisionDraft)
    raw_content:str=""
    response_debug:str=""
@dataclass(slots=True)
class EnrichedTurnResult:turn:TurnRecord;output:MemoryModelOutput
@dataclass(slots=True)
class MemoryJobResult:
    status:MemoryApplyStatus|None=None
    error:str=""
    debug:str=""
    def summary_line(self)->str:
        if self.error.strip():return f"[memory] failed: {self.error.strip()}"
        base=self.status.summary_line() if self.status is not None else "[memory] no_result"
        return f"{base} | debug: {self.debug}" if self.debug.strip() else base
@dataclass(slots=True)
class MemoryModelJob:
    session_cwd:str
    session_id:str
    turn:TurnRecord
    existing_session_episodic:list[str]=field(default_factory=list)
    existing_session_semantic:list[str]=field(default_factory=list)
    existing_folder_procedural:list[str]=field(default_factory=list)
    callback:Any=None
    on_complete:Any=None
class MemoryModelClient:
    def __init__(self,config:AppConfig)->None:self.config=config;self.settings:MemoryModelSettings=config.memory.memory_model;self.http_client=httpx.Client(timeout=60.0)
    def is_enabled(self)->bool:return self.settings.enabled and self.settings.mode.lower()=="async"
    def generate_turn_enrichment(self,job:MemoryModelJob)->MemoryModelOutput:
        payload={"model":self.settings.model,"messages":[{"role":"system","content":MEMORY_MODEL_SYSTEM_PROMPT},{"role":"user","content":build_memory_model_prompt(job,self.settings)}],"temperature":self.settings.temperature,"top_p":self.settings.top_p,"stream":False,"response_format":{"type":"json_object"}}
        try:
            response=self.http_client.post(memory_model_chat_url(self.settings.base_url),headers={"Authorization":f"Bearer {self.settings.api_key}"},json=payload);response.raise_for_status();data=response.json();append_memory_model_log(job,payload=payload,response_data=data)
        except httpx.HTTPStatusError as exc:
            body=exc.response.text if exc.response is not None else "无法读取错误响应";append_memory_model_log(job,payload=payload,error=f"HTTP {exc.response.status_code}: {body}");raise ApiRequestError(f"memory model HTTP {exc.response.status_code}: {body}") from exc
        except httpx.HTTPError as exc:append_memory_model_log(job,payload=payload,error=f"HTTPError: {exc}");raise ApiRequestError(f"memory model 请求失败: {exc}") from exc
        except json.JSONDecodeError as exc:append_memory_model_log(job,payload=payload,error=f"JSONDecodeError: {exc}");raise ApiRequestError(f"memory model 响应 JSON 无法解析: {exc}") from exc
        return parse_memory_model_output(data)
    def close(self)->None:self.http_client.close()
class MemoryModelWorker:
    def __init__(self,client:MemoryModelClient)->None:self.client=client;self.jobs:queue.Queue[MemoryModelJob|None]=queue.Queue();self.thread:threading.Thread|None=None;self.started=False
    def start(self)->None:
        if self.started or not self.client.is_enabled():return
        self.started=True;self.thread=threading.Thread(target=self._run,name="zhou-memory-worker",daemon=True);self.thread.start()
    def submit(self,job:MemoryModelJob)->bool:
        if not self.client.is_enabled():return False
        self.start();self.jobs.put(job);return True
    def shutdown(self)->None:
        if not self.started:self.client.close();return
        self.jobs.put(None)
        if self.thread is not None:self.thread.join(timeout=3.0)
        self.client.close()
    def _run(self)->None:
        while True:
            job=self.jobs.get()
            if job is None:return
            try:
                output=self.client.generate_turn_enrichment(job)
                enriched_turn=build_turn_record(session_id=job.session_id,user_input=job.turn.user,assistant_text=job.turn.assistant,reasoning_summary=output.reasoning_summary or job.turn.reasoning_summary,tool_calls=[{"name":c.name,"arguments":c.arguments} for c in job.turn.tool_calls],tags=output.tags or job.turn.tags,memory_candidates=output.memory_candidates or job.turn.memory_candidates,auto_enrich=False)
                enriched_turn.timestamp=job.turn.timestamp
                status=job.callback(EnrichedTurnResult(turn=enriched_turn,output=output))
                if callable(job.on_complete):job.on_complete(MemoryJobResult(status=status,debug=build_memory_debug_summary(output)))
            except Exception as exc:
                if callable(job.on_complete):job.on_complete(MemoryJobResult(error=str(exc)))
                continue
MEMORY_MODEL_SYSTEM_PROMPT="""你是 ZhouAgent 的 memory model。请先完成内部分析，再只输出最终 JSON。除文件名、路径、命令名外，尽量使用中文。最终输出必须包含以下顶层字段：reasoning_summary、tags、memory_candidates、session_episodic、session_semantic、folder_procedural。三类记忆字段都必须包含 decision、target_memory_key、content、importance、reason。decision 只能是 insert、update、skip。当存在 related_memories 时，必须先比较新候选与旧记忆。只有在与已有记忆高度相近且没有任何需要补充、修正、合并、版本推进的信息时，才允许使用 skip；只要旧记忆需要更新、补充、纠正、细化、去重合并，必须优先使用 update；如果没有可更新的旧记忆但本轮产生了值得保留的新信息，必须使用 insert。分类规则必须严格遵守：session_semantic 仅用于稳定事实、偏好、身份、长期有效约束这类“知识型记忆”，不能写方法、流程、步骤、排查顺序、解决套路。内容应写成去上下文后仍成立的知识句，避免“本轮”“用户说”。例如应写“用户名称为 yhz”，不要写“用户表示自己叫 yhz”。只要内容本质上是在描述如何做事、如何解决问题、按什么步骤推进，就不能写入 session_semantic，而应考虑 folder_procedural。session_episodic 只用于值得回看的事件过程，并且只有在本轮确实发生了工具调用时才允许 insert/update；没有工具调用时，session_episodic 必须为 skip。即使有工具调用，内容也必须体现任务/过程/结果中的至少两项。folder_procedural 用于沉淀解决某类问题的一套流程，既可以是当前项目下可复用的流程，也可以是跨项目可复用的通用流程；只要本轮确实形成了可复用步骤、方法、顺序、约束或排障套路，就可以写入 folder_procedural，不再要求 session_episodic 先成立。若只是简单事实更新、一般聊天、没有形成可执行流程，则 folder_procedural 必须 skip。不要输出 markdown，不要解释最终 JSON 之外的内容。"""
def build_memory_model_prompt(job:MemoryModelJob,settings:MemoryModelSettings)->str:
    turn=job.turn
    payload={"generate_reasoning_summary":settings.generate_reasoning_summary,"generate_session_memory":settings.generate_session_memory,"generate_folder_memory":settings.generate_folder_memory,"allow_model_decide_promotion":settings.allow_model_decide_promotion,"user":turn.user,"assistant":turn.assistant,"reasoning_summary":turn.reasoning_summary,"tool_calls":[{"name":i.name,"arguments":i.arguments} for i in turn.tool_calls],"existing_tags":turn.tags,"existing_memory_candidates":turn.memory_candidates,"related_memories":{"session_episodic":job.existing_session_episodic,"session_semantic":job.existing_session_semantic,"folder_procedural":job.existing_folder_procedural},"decision_policy":{"skip":"仅当与已有记忆相近且无需补充、纠正、合并、版本更新时才能使用","update":"只要已有记忆需要补充、修正、细化、合并或版本推进，就必须使用 update","insert":"当不存在合适旧记忆可更新，但本轮有值得保留的新信息时使用 insert"},"requirements":{"session_episodic":"只有当本轮存在工具调用时才允许写入。用于记录值得回看的事件过程，内容至少体现任务/过程/结果中的两项；常见触发包括工具调用、报错定位、修复动作、文件修改、排查步骤、多轮推进。若没有工具调用，或只是姓名、偏好、身份、简单事实告知、寒暄、极简问答，则必须 skip。内容应偏事件叙述，可出现‘本轮/用户/助手/最终’等过程词。","session_semantic":"只提炼稳定事实、用户偏好、身份信息、长期有效约束这类知识，不允许写方法、流程、步骤、解决套路。内容应写成脱离当前轮次也成立的知识句，避免‘本轮’‘用户表示’‘助手回复’等事件措辞。像姓名、称呼偏好、固定约束，优先写入 semantic；凡是描述如何做事、如何解决问题、按什么顺序推进的内容，都不要写到 session_semantic。","folder_procedural":"用于沉淀解决某类问题的一套流程，既可以是当前项目下可复用流程，也可以是跨项目通用流程。只要本轮形成了可复用步骤、顺序、方法、约束、检查清单或排障套路，就可以写入，不要求 session_episodic 先成立；但如果只是一般聊天、简单事实更新、抽象偏好表达，或没有形成可执行流程，则必须 skip。内容应写成可执行流程/方法，而非事件回放。"}}
    return json.dumps(payload,ensure_ascii=False)
def memory_model_chat_url(base_url:str)->str:
    normalized=base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):return normalized
    if normalized.endswith("/v1"):return f"{normalized}/chat/completions"
    return f"{normalized}/chat/completions"
def parse_memory_model_output(data:dict[str,object])->MemoryModelOutput:
    raw_text=extract_memory_model_raw_text(data)
    response_debug=summarize_memory_response(data)
    parsed=parse_memory_model_json_content(raw_text)
    validate_memory_model_output_dict(parsed)
    return MemoryModelOutput(reasoning_summary=normalize_output_text(parsed.get("reasoning_summary"),max_length=600),tags=normalize_output_list(parsed.get("tags"),max_items=8),memory_candidates=normalize_output_list(parsed.get("memory_candidates"),max_items=6),session_episodic=parse_decision_draft(parsed.get("session_episodic"),280),session_semantic=parse_decision_draft(parsed.get("session_semantic"),220),folder_procedural=parse_decision_draft(parsed.get("folder_procedural"),220),raw_content=compact_error_text(raw_text,max_length=2000),response_debug=response_debug)
def parse_decision_draft(value:object,max_length:int)->MemoryDecisionDraft:
    if not isinstance(value,dict):return MemoryDecisionDraft(provided=False)
    raw_decision=str(value.get("decision") or "skip").strip().lower()
    invalid_decision=raw_decision not in {"insert","update","skip"}
    decision=raw_decision if not invalid_decision else "skip"
    return MemoryDecisionDraft(decision=decision,target_memory_key=str(value.get("target_memory_key") or "").strip(),content=normalize_output_text(value.get("content"),max_length=max_length),importance=normalize_importance(value.get("importance")),reason=normalize_output_text(value.get("reason"),max_length=120),provided=True,invalid_decision=invalid_decision)
def extract_message_content(data:dict[str,object])->str:
    choices=data.get("choices")
    if not isinstance(choices,list) or not choices:return ""
    first=choices[0]
    if not isinstance(first,dict):return ""
    message=first.get("message")
    if not isinstance(message,dict):return ""
    return str(message.get("content") or "").strip()

def extract_message_reasoning_content(data:dict[str,object])->str:
    choices=data.get("choices")
    if not isinstance(choices,list) or not choices:return ""
    first=choices[0]
    if not isinstance(first,dict):return ""
    message=first.get("message")
    if not isinstance(message,dict):return ""
    return extract_delta_text(message.get("reasoning_content"))

def extract_memory_model_raw_text(data:dict[str,object])->str:
    content=extract_message_content(data)
    if content.strip():
        return content.strip()
    parsed=extract_message_parsed_text(data)
    if parsed.strip():
        return parsed.strip()
    reasoning_content=extract_message_reasoning_content(data)
    json_candidate=extract_json_object_text(reasoning_content)
    if json_candidate.strip().startswith("{") and json_candidate.strip().endswith("}"):
        return json_candidate.strip()
    raise ValueError(f"memory model raw output does not contain parseable JSON; {summarize_memory_response(data)}")

def extract_message_parsed_text(data:dict[str,object])->str:
    choices=data.get("choices")
    if not isinstance(choices,list) or not choices:return ""
    first=choices[0]
    if not isinstance(first,dict):return ""
    message=first.get("message")
    if not isinstance(message,dict):return ""
    parsed=message.get("parsed")
    if parsed is None:return ""
    if isinstance(parsed,str):return parsed.strip()
    try:return json.dumps(parsed,ensure_ascii=False)
    except (TypeError,ValueError):return str(parsed).strip()

def parse_memory_model_json_content(content:str)->dict[str,object]:
    if not content.strip():
        raise ValueError("memory model raw content is empty")
    try:
        parsed=json.loads(content)
    except json.JSONDecodeError as exc:
        extracted=extract_json_object_text(content)
        if extracted and extracted!=content:
            try:
                parsed=json.loads(extracted)
            except json.JSONDecodeError as inner_exc:
                raise ValueError(f"memory model raw content is not valid JSON: {inner_exc}; raw={compact_error_text(content, max_length=1200)}") from inner_exc
        else:
            raise ValueError(f"memory model raw content is not valid JSON: {exc}; raw={compact_error_text(content, max_length=1200)}") from exc
    if not isinstance(parsed,dict):
        raise ValueError(f"memory model raw content is not a JSON object; raw={compact_error_text(content, max_length=1200)}")
    return parsed

def extract_json_object_text(content:str)->str:
    fenced=re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
    start=fenced.find("{")
    end=fenced.rfind("}")
    if start==-1 or end==-1 or end<=start:
        return fenced
    return fenced[start:end+1].strip()

def compact_error_text(content:str,max_length:int=400)->str:
    compact=" ".join(str(content).split()).strip()
    return compact if len(compact)<=max_length else compact[:max_length-1].rstrip()+"…"

def validate_memory_model_output_dict(parsed:dict[str,object]) -> None:
    required_top_level=("reasoning_summary","tags","memory_candidates","session_episodic","session_semantic","folder_procedural")
    missing=[key for key in required_top_level if key not in parsed]
    if missing:
        raise ValueError(f"memory model JSON missing required fields: {', '.join(missing)}")
    for key in ("session_episodic","session_semantic","folder_procedural"):
        value=parsed.get(key)
        if not isinstance(value,dict):
            raise ValueError(f"memory model field `{key}` must be an object")
        missing_nested=[nested for nested in ("decision","target_memory_key","content","importance","reason") if nested not in value]
        if missing_nested:
            raise ValueError(f"memory model field `{key}` missing nested fields: {', '.join(missing_nested)}")

def summarize_decision_debug(label:str,draft:MemoryDecisionDraft)->str:
    if not draft.provided:
        return f"{label}=fallback_missing"
    suffix=[]
    if draft.invalid_decision:
        suffix.append("invalid_decision")
    if draft.decision in {"insert","update"} and not draft.content:
        suffix.append("empty_content")
    suffix_text=f"({','.join(suffix)})" if suffix else ""
    return f"{label}={draft.decision}{suffix_text}"

def build_memory_debug_summary(output:MemoryModelOutput)->str:
    parts=[
        summarize_decision_debug("session_episodic", output.session_episodic),
        summarize_decision_debug("session_semantic", output.session_semantic),
        summarize_decision_debug("folder_procedural", output.folder_procedural),
    ]
    if output.response_debug.strip():
        parts.append(output.response_debug)
    if output.raw_content.strip():
        parts.append(f"raw={output.raw_content}")
    return " | ".join(parts)

def summarize_memory_response(data:dict[str,object])->str:
    choices=data.get("choices")
    if not isinstance(choices,list) or not choices:
        return f"response=no_choices keys={','.join(sorted(str(k) for k in data.keys())[:8])}"
    first=choices[0]
    if not isinstance(first,dict):
        return f"response=choice_not_object type={type(first).__name__}"
    message=first.get("message") if isinstance(first.get("message"),dict) else {}
    content=message.get("content") if isinstance(message,dict) else None
    reasoning_content=message.get("reasoning_content") if isinstance(message,dict) else None
    role=str(message.get("role") or "") if isinstance(message,dict) else ""
    finish_reason=str(first.get("finish_reason") or "")
    tool_calls=message.get("tool_calls") if isinstance(message,dict) else None
    parsed_field=message.get("parsed") if isinstance(message,dict) else None
    refusal=message.get("refusal") if isinstance(message,dict) else None
    parts=[
        f"finish_reason={finish_reason or 'missing'}",
        f"message_role={role or 'missing'}",
        f"content_len={len(str(content or ''))}",
        f"reasoning_content_len={len(str(reasoning_content or ''))}",
        f"message_keys={','.join(sorted(str(k) for k in message.keys())[:8]) if isinstance(message,dict) else 'none'}",
    ]
    if tool_calls is not None:
        parts.append(f"tool_calls_type={type(tool_calls).__name__}")
    if parsed_field is not None:
        parts.append(f"parsed_type={type(parsed_field).__name__}")
    if refusal is not None:
        parts.append(f"refusal={compact_error_text(str(refusal),max_length=80)}")
    return " | ".join(parts)

def append_memory_model_log(job:MemoryModelJob,*,payload:dict[str,object],response_data:dict[str,object]|None=None,error:str="") -> None:
    try:
        log_dir=Path(job.session_cwd)/PROJECT_LOGS_DIRNAME
        log_dir.mkdir(parents=True,exist_ok=True)
        log_path=log_dir/MEMORY_MODEL_LOG_FILENAME
        entry={
            "session_id":job.session_id,
            "cwd":job.session_cwd,
            "user":job.turn.user,
            "assistant":job.turn.assistant,
            "reasoning_summary":job.turn.reasoning_summary,
            "existing_session_episodic":job.existing_session_episodic,
            "existing_session_semantic":job.existing_session_semantic,
            "existing_folder_procedural":job.existing_folder_procedural,
            "payload":payload,
        }
        if error:
            entry["error"]=error
        if response_data is not None:
            entry["response"]=response_data
            try:
                entry["raw_text_extracted"]=extract_memory_model_raw_text(response_data)
            except Exception as raw_exc:
                entry["raw_text_extract_error"]=str(raw_exc)
        with log_path.open("a",encoding="utf-8") as fh:
            fh.write(json.dumps(entry,ensure_ascii=False)+"\n")
    except Exception:
        return

def extract_delta_text(value:object)->str:
    if value is None:return ""
    if isinstance(value,str):return value
    if isinstance(value,list):
        parts:list[str]=[]
        for item in value:
            if isinstance(item,str):parts.append(item)
            elif isinstance(item,dict):
                text=item.get("text") or item.get("content") or item.get("reasoning_content")
                if text:parts.append(str(text))
        return "".join(parts)
    if isinstance(value,dict):
        text=value.get("text") or value.get("content") or value.get("reasoning_content")
        return str(text) if text else ""
    return str(value)

def normalize_output_text(value:object,max_length:int=180)->str:
    compact=" ".join(str(value or "").split()).strip()
    if len(compact)<=max_length:return compact
    return compact[:max_length-1].rstrip()+"…"
def normalize_output_list(value:object,*,max_items:int)->list[str]:
    if not isinstance(value,list):return []
    seen:set[str]=set();result:list[str]=[]
    for item in value:
        text=normalize_output_text(item,max_length=120);key=text.casefold()
        if not text or key in seen:continue
        seen.add(key);result.append(text)
        if len(result)>=max_items:break
    return result
def normalize_importance(value:object)->float:
    try:parsed=float(value)
    except (TypeError,ValueError):return 0.0
    return max(0.0,min(1.0,parsed))
