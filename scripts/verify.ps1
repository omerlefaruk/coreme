# Full gate: lint, format, types, tests (referenced from AGENTS.md).
$ErrorActionPreference = 'Stop'

python scripts\sync_agentdocs.py --check
if ($LASTEXITCODE -ne 0) { Write-Host 'run: python scripts\sync_agentdocs.py'; exit 1 }
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
python -m mypy src
python -m pytest -q
