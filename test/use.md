$env:PYTHONPATH=".\src"

python -m zhou.test_runner ".\test\agent_cases" --category smoke --max-cases 1
python -m zhou.test_runner ".\test\agent_cases" --category answer --max-cases 1
python -m zhou.test_runner ".\test\agent_cases" --category memory --max-cases 1
python -m zhou.test_runner ".\test\agent_cases" --category tools --max-cases 1
