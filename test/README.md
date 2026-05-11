# Test workspace layout

- `test/agent_cases/`: declarative regression input cases
- `test/artifacts/`: local runner outputs such as traces and reports
- `test/docs/`: testing notes and local usage docs
- `tests/integration/`: code-level mock/stub integration tests for CI

## Local run examples

```powershell
$env:PYTHONPATH=".\src"
python -m zhou.test_runner ".\test\agent_cases" --category smoke --max-cases 1
python -m zhou.test_runner ".\test\agent_cases" --category answer --max-cases 1
python -m zhou.test_runner ".\test\agent_cases" --category memory --max-cases 1
python -m zhou.test_runner ".\test\agent_cases" --category tools --max-cases 1
pytest .\tests\integration -q
```
