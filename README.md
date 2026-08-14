# CoreMe

CoreMe runs durable Python automation Jobs.

A Job is a folder with a manifest, an entry script, and optional offline tests.
Each run writes logs, structured events, inputs, and artifacts. A release is an
immutable Job copy with a content hash.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Use

```powershell
coreme init jobs/hello --name hello
coreme test jobs/hello
coreme run jobs/hello
coreme ship jobs/hello
coreme run hello
```

Normal runs do not need an AI service. Inputs come from the Job manifest.
Secret values come from the process environment and must not enter Git or run
evidence.

## Development

```powershell
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
python -m pytest -q
```

License: MIT.
