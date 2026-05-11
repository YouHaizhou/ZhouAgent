from __future__ import annotations
import argparse, json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4
from .core.errors import ZhouError
from .main import _bootstrap, _handle_turn
from .session import TurnRecord, load_turn_records
from .testcases import AgentCase, build_runner_config, load_cases

@dataclass(slots=True)
class AssertionSummary:
    flow: str
    tools: str
    memory: str
    answer: str

@dataclass(slots=True)
class MemoryEvidence:
    search_called: bool = False
    write_called: bool = False
    observed_scopes: set[str] = field(default_factory=set)
    observed_classes: set[str] = field(default_factory=set)

@dataclass(slots=True)
class RealRunResult:
    case_name: str
    category: str
    status: str
    phase: str
    session_id: str
    duration_ms: int
    trace_path: str
    assertions: AssertionSummary
    error: str | None = None

@dataclass(slots=True)
class RealRunContext:
    run_id: str
    cwd: Path
    session_id: str
    trace_path: Path

@dataclass(slots=True)
class SuiteReport:
    generated_at: str
    total_cases: int
    passed: int
    failed: int
    validation_errors: int
    flow_failed: int
    tools_failed: int
    memory_failed: int
    answer_failed: int
    results: list[dict[str, Any]]

class MemoryRecorder:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.evidence = MemoryEvidence()
    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)
    def search_all_scopes(self, query: str, *, cwd: str, session_id: str, limit_per_scope: int = 4):
        self.evidence.search_called = True
        result = self.inner.search_all_scopes(query, cwd=cwd, session_id=session_id, limit_per_scope=limit_per_scope)
        for scope_name, scope_result in result.items():
            self._collect_search(str(scope_name), scope_result)
        return result
    def search_memory(self, query: str, **kwargs: Any):
        self.evidence.search_called = True
        result = self.inner.search_memory(query, **kwargs)
        scope = kwargs.get('scope')
        self._collect_search(str(getattr(scope, 'value', scope) or ''), result)
        return result
    def write_memory(self, record: Any) -> None:
        self.evidence.write_called = True
        self._collect_record(record)
        return self.inner.write_memory(record)
    def write_versioned_memory(self, record: Any, *, memory_key: str, revision: int) -> None:
        self.evidence.write_called = True
        self._collect_record(record)
        return self.inner.write_versioned_memory(record, memory_key=memory_key, revision=revision)
    def write_session_turn(self, *, cwd: str, turn: TurnRecord) -> None:
        self.evidence.write_called = True
        self.evidence.observed_scopes.add('session')
        self.evidence.observed_classes.add('episodic')
        return self.inner.write_session_turn(cwd=cwd, turn=turn)
    def write_global_knowledge(self, *, content: str, source: str = 'knowledge_base') -> None:
        self.evidence.write_called = True
        self.evidence.observed_scopes.add('global')
        self.evidence.observed_classes.add('semantic')
        return self.inner.write_global_knowledge(content=content, source=source)
    def _collect_search(self, scope_name: str, result: Any) -> None:
        if scope_name and getattr(result, 'hits', None):
            self.evidence.observed_scopes.add(scope_name)
        for hit in getattr(result, 'hits', []):
            memory_class = getattr(getattr(hit, 'record', None), 'memory_class', None)
            class_name = getattr(memory_class, 'value', memory_class)
            if class_name:
                self.evidence.observed_classes.add(str(class_name))
    def _collect_record(self, record: Any) -> None:
        scope = getattr(getattr(record, 'scope', None), 'value', getattr(record, 'scope', None))
        memory_class = getattr(getattr(record, 'memory_class', None), 'value', getattr(record, 'memory_class', None))
        if scope:
            self.evidence.observed_scopes.add(str(scope))
        if memory_class:
            self.evidence.observed_classes.add(str(memory_class))

def prepare_run_context(case: AgentCase, traces_root: Path) -> RealRunContext:
    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%S')}_{case.name}"
    cwd = Path.cwd() if case.environment.cwd == 'project_root' else Path(case.environment.cwd).resolve()
    session_id = uuid4().hex
    traces_root.mkdir(parents=True, exist_ok=True)
    return RealRunContext(run_id, cwd, session_id, traces_root / f"{run_id}.json")

def latest_turn(session: Any) -> TurnRecord | None:
    turns = load_turn_records(session.turns_path())
    return turns[-1] if turns else None

def is_subsequence(expected: list[str], actual: list[str]) -> bool:
    idx = 0
    for item in actual:
        if idx < len(expected) and item == expected[idx]:
            idx += 1
    return idx == len(expected)

def assert_flow(case: AgentCase, turn: TurnRecord | None, error: str | None) -> tuple[str, list[str]]:
    reasons = []
    if case.assertions.flow.expect_success and error is not None:
        reasons.append(f'execution error: {error}')
    if case.assertions.flow.expect_final_answer and (turn is None or not turn.assistant.strip()):
        reasons.append('final answer is empty')
    if case.assertions.flow.expect_turn_persisted and turn is None:
        reasons.append('turn not persisted')
    return ('passed' if not reasons else 'failed', reasons)

def assert_tools(case: AgentCase, turn: TurnRecord | None) -> tuple[str, list[str], list[str]]:
    calls = [] if turn is None else [{'name': c.name, 'arguments': c.arguments} for c in turn.tool_calls]
    tool_names = [c['name'] for c in calls]
    reasons = []
    for name in case.assertions.tools.must_call:
        if name not in tool_names:
            reasons.append(f'required tool not called: {name}')
    for name in case.assertions.tools.must_not_call:
        if name in tool_names:
            reasons.append(f'forbidden tool called: {name}')
    for name, parts in case.assertions.tools.argument_contains.items():
        matched = [c for c in calls if c['name'] == name]
        if not matched:
            reasons.append(f'tool missing for argument check: {name}')
            continue
        arg_texts = [str(c['arguments']) for c in matched]
        for part in parts:
            if not any(part in text for text in arg_texts):
                reasons.append(f'tool argument missing: {name} -> {part}')
    orders = case.assertions.tools.call_order_any_of
    if orders and not any(is_subsequence(order, tool_names) for order in orders):
        reasons.append('tool call order mismatch')
    return ('passed' if not reasons else 'failed', reasons, tool_names)

def assert_memory(case: AgentCase, evidence: MemoryEvidence) -> tuple[str, list[str], dict[str, Any]]:
    reasons = []
    if case.assertions.memory.expect_search and not evidence.search_called:
        reasons.append('memory search not observed')
    if case.assertions.memory.expect_write and not evidence.write_called:
        reasons.append('memory write not observed')
    for scope in case.assertions.memory.expected_scopes:
        if scope not in evidence.observed_scopes:
            reasons.append(f'expected memory scope not observed: {scope}')
    for memory_class in case.assertions.memory.expected_classes:
        if memory_class not in evidence.observed_classes:
            reasons.append(f'expected memory class not observed: {memory_class}')
    payload = {'search_called': evidence.search_called, 'write_called': evidence.write_called, 'observed_scopes': sorted(evidence.observed_scopes), 'observed_classes': sorted(evidence.observed_classes)}
    return ('passed' if not reasons else 'failed', reasons, payload)

def assert_answer(case: AgentCase, turn: TurnRecord | None) -> tuple[str, list[str]]:
    if turn is None:
        return 'failed', ['missing turn record']
    answer = turn.assistant or ''
    lowered = answer.lower()
    reasons = []
    for item in case.assertions.answer.contains:
        if item.lower() not in lowered:
            reasons.append(f'missing keyword: {item}')
    for item in case.assertions.answer.not_contains:
        if item.lower() in lowered:
            reasons.append(f'forbidden keyword present: {item}')
    if len(answer.strip()) < case.assertions.answer.min_length:
        reasons.append(f'answer shorter than min_length={case.assertions.answer.min_length}')
    return ('passed' if not reasons else 'failed', reasons)

def wait_for_memory_evidence(case: AgentCase, recorder: MemoryRecorder | None, timeout_s: float = 3.0, interval_s: float = 0.2) -> MemoryEvidence:
    evidence = recorder.evidence if recorder is not None else MemoryEvidence()
    if not (case.assertions.memory.expect_write or case.assertions.memory.expected_scopes or case.assertions.memory.expected_classes):
        return evidence
    deadline = datetime.now(timezone.utc).timestamp() + timeout_s
    while datetime.now(timezone.utc).timestamp() < deadline:
        if evidence.write_called:
            return evidence
        if case.assertions.memory.expected_scopes and all(scope in evidence.observed_scopes for scope in case.assertions.memory.expected_scopes):
            return evidence
        if case.assertions.memory.expected_classes and all(item in evidence.observed_classes for item in case.assertions.memory.expected_classes):
            return evidence
        __import__('time').sleep(interval_s)
    return evidence

def build_isolated_session(base_session: Any, context: RealRunContext) -> Any:
    session = base_session.__class__(cwd=context.cwd, session_id=context.session_id)
    session.available_skills = list(getattr(base_session, 'available_skills', []))
    session.tool_registry = getattr(base_session, 'tool_registry', session.tool_registry)
    return session

def write_run_trace(case: AgentCase, context: RealRunContext, status: str, phase: str, assertions: AssertionSummary, turn: TurnRecord | None, tool_names: list[str], memory_payload: dict[str, Any], error: str | None = None, flow_reasons: list[str] | None = None, tool_reasons: list[str] | None = None, memory_reasons: list[str] | None = None, answer_reasons: list[str] | None = None) -> None:
    payload = {'trace_id': context.run_id, 'case_name': case.name, 'category': case.category, 'status': status, 'phase': phase, 'session_id': context.session_id, 'cwd': str(context.cwd), 'input': case.input, 'error': error, 'assertions': {'flow': assertions.flow, 'tools': assertions.tools, 'memory': assertions.memory, 'answer': assertions.answer, 'flow_reasons': flow_reasons or [], 'tool_reasons': tool_reasons or [], 'memory_reasons': memory_reasons or [], 'answer_reasons': answer_reasons or [], 'actual_tools': tool_names, 'memory_evidence': memory_payload}, 'turn': None if turn is None else {'timestamp': turn.timestamp, 'user': turn.user, 'assistant': turn.assistant, 'reasoning_summary': turn.reasoning_summary, 'tool_calls': [{'name': c.name, 'arguments': c.arguments} for c in turn.tool_calls]}}
    context.trace_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

def execute_case(case: AgentCase, traces_root: Path) -> RealRunResult:
    started = datetime.now(timezone.utc)
    context = prepare_run_context(case, traces_root)
    client = archive_writer = session = worker = None
    memory = recorder = None
    turn = None
    runtime_error = None
    try:
        _, _, client, memory, archive_writer, loaded_session, worker = _bootstrap()
        recorder = MemoryRecorder(memory)
        session = build_isolated_session(loaded_session, context)
        session.ensure_storage()
        worker.start()
        _handle_turn(case.input, session=session, client=client, memory=recorder, archive_writer=archive_writer, worker=worker)
        turn = latest_turn(session)
        if worker is not None:
            worker.shutdown()
            worker = None
        flow_status, flow_reasons = assert_flow(case, turn, None)
        tools_status, tool_reasons, tool_names = assert_tools(case, turn)
        evidence = wait_for_memory_evidence(case, recorder)
        memory_status, memory_reasons, memory_payload = assert_memory(case, evidence)
        answer_status, answer_reasons = assert_answer(case, turn)
        final_status = 'passed' if all(status == 'passed' for status in (flow_status, tools_status, memory_status, answer_status)) else 'failed'
        summary = AssertionSummary(flow_status, tools_status, memory_status, answer_status)
        write_run_trace(case, context, final_status, 'asserted', summary, turn, tool_names, memory_payload, None, flow_reasons, tool_reasons, memory_reasons, answer_reasons)
        return RealRunResult(case.name, case.category, final_status, 'asserted', session.session_id, duration_ms(started), str(context.trace_path), summary)
    except ZhouError as exc:
        runtime_error = str(exc)
    except Exception as exc:
        runtime_error = str(exc)
    finally:
        if session is not None and turn is None:
            turn = latest_turn(session)
        if worker is not None:
            worker.shutdown()
        if session is not None:
            session.save()
        if client is not None:
            client.close()
    evidence = wait_for_memory_evidence(case, recorder)
    flow_status, flow_reasons = assert_flow(case, turn, runtime_error)
    tools_status, tool_reasons, tool_names = assert_tools(case, turn)
    memory_status, memory_reasons, memory_payload = assert_memory(case, evidence)
    answer_status, answer_reasons = assert_answer(case, turn)
    summary = AssertionSummary(flow_status, tools_status, memory_status, answer_status)
    write_run_trace(case, context, 'failed', 'runtime_error', summary, turn, tool_names, memory_payload, runtime_error, flow_reasons, tool_reasons, memory_reasons, answer_reasons)
    return RealRunResult(case.name, case.category, 'failed', 'runtime_error', context.session_id, duration_ms(started), str(context.trace_path), summary, runtime_error)

def duration_ms(started: datetime) -> int:
    return int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

def build_suite_report(results: list[RealRunResult], validation_errors: list[str]) -> SuiteReport:
    return SuiteReport(datetime.now(timezone.utc).isoformat(), len(results), sum(1 for r in results if r.status == 'passed'), sum(1 for r in results if r.status != 'passed'), len(validation_errors), sum(1 for r in results if r.assertions.flow != 'passed'), sum(1 for r in results if r.assertions.tools != 'passed'), sum(1 for r in results if r.assertions.memory != 'passed'), sum(1 for r in results if r.assertions.answer != 'passed'), [{'case_name': r.case_name, 'category': r.category, 'status': r.status, 'phase': r.phase, 'session_id': r.session_id, 'duration_ms': r.duration_ms, 'trace_path': r.trace_path, 'assertions': asdict(r.assertions), 'error': r.error} for r in results])

def write_suite_report(report: SuiteReport, reports_root: Path) -> Path:
    reports_root.mkdir(parents=True, exist_ok=True)
    path = reports_root / f"suite_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}.json"
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding='utf-8')
    return path

def print_suite_summary(report: SuiteReport, report_path: Path) -> None:
    print(f'Suite report: {report_path}')
    print(f'Summary: total={report.total_cases} passed={report.passed} failed={report.failed} validation_errors={report.validation_errors}')
    print(f'Assertion failures: flow={report.flow_failed} tools={report.tools_failed} memory={report.memory_failed} answer={report.answer_failed}')

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='zhou-real-runner', description='Execute real single-turn regression cases.')
    parser.add_argument('cases_root', nargs='?', default='test/agent_cases', help='Root directory containing agent case JSON files.')
    parser.add_argument('--category', action='append', default=[], help='Only include selected categories.')
    parser.add_argument('--max-cases', type=int, default=None, help='Maximum number of cases to execute.')
    return parser

def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser(); args = parser.parse_args(argv); root = Path(args.cases_root).resolve()
    if not root.exists():
        print(f'Case root not found: {root}')
        return 1
    config = build_runner_config(root, args.category, args.max_cases)
    load_result = load_cases(config.cases_root)
    cases = [case for case in load_result.cases if not args.category or case.category in args.category]
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    print(f'Executing cases: {len(cases)}')
    print(f'Validation errors: {len(load_result.errors)}')
    results = [execute_case(case, config.traces_root) for case in cases]
    for result in results:
        suffix = f' error={result.error}' if result.error else ''
        print('  [%s] %-6s %s flow=%s tools=%s memory=%s answer=%s%s' % (result.status.upper(), result.category, result.case_name, result.assertions.flow, result.assertions.tools, result.assertions.memory, result.assertions.answer, suffix))
    for error in load_result.errors:
        print(f'  [ERR] {error}')
    report = build_suite_report(results, load_result.errors)
    report_path = write_suite_report(report, config.reports_root)
    print_suite_summary(report, report_path)
    return 0 if not load_result.errors and all(r.status == 'passed' for r in results) else 2
if __name__ == '__main__':
    raise SystemExit(main())

