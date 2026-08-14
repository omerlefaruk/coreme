# coreme

AI-native RPA kernel. Agent = developer. Job = program. Runner = dumb robot.

**Status:** public kernel plus F3 fleet siblings.

## Interface

- CLI `coreme`: `init`, `run`, `ship`, `brief`, `repair`
- Release identity: `tree_hash`, `parse_hash`, `zip_tree`, `unzip_tree`
- Freeze procedure: `ship_job`, `verify_release`

## File map

| File | Role |
|------|------|
| `release.py` | Tree hash, hash form, zip pack/unpack |
| `ship.py` | Freeze a proven Job as a Release |
| `runner.py` | Run one Job |
| `repair.py` | Failed Run → source → brief → spawn → repair.json |
| `repair_spawn.py` | Codex spawn adapter |
| `brief.py` | Assemble repair markdown |
| `cli.py` | Kernel console |

## Next

Sibling packages: `coreme_agent`, `coreme_hub`.
