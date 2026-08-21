# Full gate: lint, format, types, tests (referenced from AGENTS.md).
$ErrorActionPreference = 'Stop'

python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
python -m pytest -q
