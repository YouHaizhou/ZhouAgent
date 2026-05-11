from __future__ import annotations
import argparse,json
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
VALID_CATEGORIES={"smoke","tools","memory","answer"};VALID_SESSION_MODES={"isolated"};VALID_MEMORY_MODES={"real"};VALID_MEMORY_SCOPES={"session","folder","global"};VALID_MEMORY_CLASSES={"episodic","semantic","procedural"}
class CaseValidationError(ValueError):pass
@dataclass(slots=True)
class FlowAssertions:expect_success:bool;expect_final_answer:bool;expect_turn_persisted:bool
@dataclass(slots=True)
class ToolAssertions:must_call:list[str];must_not_call:list[str];call_order_any_of:list[list[str]];argument_contains:dict[str,list[str]]
@dataclass(slots=True)
class MemoryAssertions:expect_search:bool;expect_write:bool;expected_scopes:list[str];expected_classes:list[str]
@dataclass(slots=True)
class AnswerAssertions:contains:list[str];not_contains:list[str];min_length:int
@dataclass(slots=True)
class CaseAssertions:flow:FlowAssertions;tools:ToolAssertions;memory:MemoryAssertions;answer:AnswerAssertions
@dataclass(slots=True)
class CaseEnvironment:cwd:str;session_mode:str;memory_mode:str
@dataclass(slots=True)
class CaseAnalysis:failure_tags:list[str];notes:str
@dataclass(slots=True)
class AgentCase:name:str;category:str;description:str;input:str;environment:CaseEnvironment;assertions:CaseAssertions;analysis:CaseAnalysis;path:Path
@dataclass(slots=True)
class CaseLoadResult:cases:list[AgentCase];errors:list[str]
@dataclass(slots=True)
class RunnerConfig:cases_root:Path;traces_root:Path;artifacts_root:Path;reports_root:Path;category_filter:list[str];max_cases:int|None
@dataclass(slots=True)
class PreparedCaseContext:case_name:str;run_id:str;started_at:str;cwd:Path;session_id:str;trace_path:Path;artifact_dir:Path
@dataclass(slots=True)
class CaseRunResult:case_name:str;category:str;status:str;phase:str;session_id:str;duration_ms:int;trace_path:str;artifact_dir:str;error:str|None=None

def discover_case_files(root:Path)->list[Path]:return sorted(root.rglob("*.json")) if root.exists() else []
def load_cases(root:Path)->CaseLoadResult:
    cases,errors=[],[]
    for path in discover_case_files(root):
        try:cases.append(load_case(path))
        except CaseValidationError as exc:errors.append(f"{path}: {exc}")
    return CaseLoadResult(cases,errors)
def load_case(path:Path)->AgentCase:
    try:payload=json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:raise CaseValidationError(f"invalid JSON: {exc.msg}") from exc
    if not isinstance(payload,dict):raise CaseValidationError("top-level JSON value must be an object")
    return AgentCase(name=_required_str(payload,"name"),category=_validated_category(payload),description=_required_str(payload,"description"),input=_required_str(payload,"input"),environment=_parse_environment(_required_dict(payload,"environment")),assertions=_parse_assertions(_required_dict(payload,"assertions")),analysis=_parse_analysis(_required_dict(payload,"analysis")),path=path)
def build_runner_config(cases_root:Path,category_filter:list[str],max_cases:int|None)->RunnerConfig:
    test_root=cases_root.parent if cases_root.name=="agent_cases" else cases_root.parent.parent
    artifacts_root=test_root/"artifacts"
    return RunnerConfig(cases_root,artifacts_root/"traces",artifacts_root,artifacts_root/"reports",category_filter,max_cases)
def run_cases_skeleton(config:RunnerConfig)->tuple[list[CaseRunResult],list[str]]:
    load_result=load_cases(config.cases_root);selected=_filter_cases(load_result.cases,config.category_filter,config.max_cases);results=[]
    for case in selected:
        started=datetime.now(timezone.utc)
        try:
            context=prepare_case_context(case,config);write_prepared_trace(case,context)
            results.append(CaseRunResult(case.name,case.category,"prepared","context_ready",context.session_id,_duration_ms(started),str(context.trace_path),str(context.artifact_dir)))
        except Exception as exc:
            results.append(CaseRunResult(case.name,case.category,"failed","prepare_context","",_duration_ms(started),"","",str(exc)))
    return results,load_result.errors
def prepare_case_context(case:AgentCase,config:RunnerConfig)->PreparedCaseContext:
    now=datetime.now(timezone.utc);run_id=f"{now.strftime('%Y%m%dT%H%M%S')}_{case.name}";cwd=Path.cwd() if case.environment.cwd=="project_root" else Path(case.environment.cwd).resolve();session_id=uuid4().hex if case.environment.session_mode=="isolated" else "default"
    for root in (config.traces_root,config.artifacts_root,config.reports_root):root.mkdir(parents=True,exist_ok=True)
    artifact_dir=config.artifacts_root/run_id;artifact_dir.mkdir(parents=True,exist_ok=True)
    return PreparedCaseContext(case.name,run_id,now.isoformat(),cwd,session_id,config.traces_root/f"{run_id}.json",artifact_dir)
def write_prepared_trace(case:AgentCase,context:PreparedCaseContext)->None:
    payload={"trace_id":context.run_id,"case_name":case.name,"category":case.category,"status":"prepared","phase":"context_ready","started_at":context.started_at,"cwd":str(context.cwd),"session_id":context.session_id,"case_path":str(case.path),"input":case.input,"assertions":{"flow":asdict(case.assertions.flow),"tools":asdict(case.assertions.tools),"memory":asdict(case.assertions.memory),"answer":asdict(case.assertions.answer)}}
    context.trace_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
def _filter_cases(cases:list[AgentCase],category_filter:list[str],max_cases:int|None)->list[AgentCase]:
    selected=[case for case in cases if not category_filter or case.category in category_filter]
    return selected[:max_cases] if max_cases is not None else selected
def _validated_category(payload:dict[str,Any])->str:
    value=_required_str(payload,"category");_ensure_in("category",value,VALID_CATEGORIES);return value
def _parse_environment(raw:dict[str,Any])->CaseEnvironment:
    cwd=_required_str(raw,"cwd");session_mode=_required_str(raw,"session_mode");memory_mode=_required_str(raw,"memory_mode");_ensure_in("session_mode",session_mode,VALID_SESSION_MODES);_ensure_in("memory_mode",memory_mode,VALID_MEMORY_MODES);return CaseEnvironment(cwd,session_mode,memory_mode)
def _parse_assertions(raw:dict[str,Any])->CaseAssertions:return CaseAssertions(flow=_parse_flow_assertions(_required_dict(raw,"flow")),tools=_parse_tool_assertions(_required_dict(raw,"tools")),memory=_parse_memory_assertions(_required_dict(raw,"memory")),answer=_parse_answer_assertions(_required_dict(raw,"answer")))
def _parse_flow_assertions(raw:dict[str,Any])->FlowAssertions:return FlowAssertions(_required_bool(raw,"expect_success"),_required_bool(raw,"expect_final_answer"),_required_bool(raw,"expect_turn_persisted"))
def _parse_tool_assertions(raw:dict[str,Any])->ToolAssertions:
    call_orders=[]
    for idx,entry in enumerate(_required_list(raw,"call_order_any_of")):
        if not isinstance(entry,list):raise CaseValidationError(f"call_order_any_of[{idx}] must be a list")
        call_orders.append(_string_list(entry,f"call_order_any_of[{idx}]"))
    arg_raw=_required_dict(raw,"argument_contains");arg_contains={}
    for key,value in arg_raw.items():
        if not isinstance(key,str):raise CaseValidationError("argument_contains keys must be strings")
        if not isinstance(value,list):raise CaseValidationError(f"argument_contains[{key!r}] must be a list")
        arg_contains[key]=_string_list(value,f"argument_contains[{key!r}]")
    return ToolAssertions(_string_list(_required_list(raw,"must_call"),"must_call"),_string_list(_required_list(raw,"must_not_call"),"must_not_call"),call_orders,arg_contains)
def _parse_memory_assertions(raw:dict[str,Any])->MemoryAssertions:
    scopes=_string_list(_required_list(raw,"expected_scopes"),"expected_scopes");classes=_string_list(_required_list(raw,"expected_classes"),"expected_classes")
    for scope in scopes:_ensure_in("expected_scopes",scope,VALID_MEMORY_SCOPES)
    for item in classes:_ensure_in("expected_classes",item,VALID_MEMORY_CLASSES)
    return MemoryAssertions(_required_bool(raw,"expect_search"),_required_bool(raw,"expect_write"),scopes,classes)
def _parse_answer_assertions(raw:dict[str,Any])->AnswerAssertions:
    min_length=raw.get("min_length")
    if not isinstance(min_length,int) or isinstance(min_length,bool) or min_length<0:raise CaseValidationError("min_length must be a non-negative integer")
    return AnswerAssertions(_string_list(_required_list(raw,"contains"),"contains"),_string_list(_required_list(raw,"not_contains"),"not_contains"),min_length)
def _parse_analysis(raw:dict[str,Any])->CaseAnalysis:return CaseAnalysis(_string_list(_required_list(raw,"failure_tags"),"failure_tags"),_required_str(raw,"notes"))
def _required_dict(raw:dict[str,Any],key:str)->dict[str,Any]:
    value=raw.get(key)
    if not isinstance(value,dict):raise CaseValidationError(f"{key} must be an object")
    return value
def _required_list(raw:dict[str,Any],key:str)->list[Any]:
    value=raw.get(key)
    if not isinstance(value,list):raise CaseValidationError(f"{key} must be a list")
    return value
def _required_str(raw:dict[str,Any],key:str)->str:
    value=raw.get(key)
    if not isinstance(value,str) or not value.strip():raise CaseValidationError(f"{key} must be a non-empty string")
    return value
def _required_bool(raw:dict[str,Any],key:str)->bool:
    value=raw.get(key)
    if not isinstance(value,bool):raise CaseValidationError(f"{key} must be a boolean")
    return value
def _string_list(values:list[Any],field_name:str)->list[str]:
    result=[]
    for idx,value in enumerate(values):
        if not isinstance(value,str) or not value.strip():raise CaseValidationError(f"{field_name}[{idx}] must be a non-empty string")
        result.append(value)
    return result
def _ensure_in(field_name:str,value:str,allowed:set[str])->None:
    if value not in allowed:raise CaseValidationError(f"{field_name} must be one of {sorted(allowed)}, got {value!r}")
def _duration_ms(started:datetime)->int:return int((datetime.now(timezone.utc)-started).total_seconds()*1000)
def build_arg_parser()->argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="zhou-case-loader",description="Load and validate Zhou agent regression case files.")
    parser.add_argument("cases_root",nargs="?",default="test/agent_cases",help="Root directory containing agent case JSON files.")
    parser.add_argument("--category",action="append",default=[],help="Only include selected categories.")
    parser.add_argument("--max-cases",type=int,default=None,help="Maximum number of cases to include.")
    parser.add_argument("--prepare-run",action="store_true",help="Prepare per-case run context and write skeleton traces.")
    return parser
def main(argv:list[str]|None=None)->int:
    parser=build_arg_parser();args=parser.parse_args(argv);root=Path(args.cases_root).resolve()
    if not root.exists():print(f"Case root not found: {root}");return 1
    config=build_runner_config(root,args.category,args.max_cases)
    if args.prepare_run:
        run_results,errors=run_cases_skeleton(config);print(f"Prepared runs: {len(run_results)}");print(f"Validation errors: {len(errors)}")
        for result in run_results:
            suffix=f" error={result.error}" if result.error else ""
            print(f"  [{result.status.upper()}] {result.category:<6} {result.case_name} phase={result.phase}{suffix}")
        for error in errors:print(f"  [ERR] {error}")
        return 0 if not errors and all(item.status=="prepared" for item in run_results) else 2
    result=load_cases(root);selected=_filter_cases(result.cases,args.category,args.max_cases);print(f"Scanned case root: {root}");print(f"Valid cases: {len(selected)}");print(f"Validation errors: {len(result.errors)}")
    for case in selected:print(f"  [OK] {case.category:<6} {case.name}")
    for error in result.errors:print(f"  [ERR] {error}")
    return 0 if not result.errors else 2
if __name__=="__main__":raise SystemExit(main())
