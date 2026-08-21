# MAKE-AI-NATIVE — execute this brief

**What this is:** a self-contained mission prompt. Paste this whole file into a coding agent (Grok, Codex, Claude, Cursor). The agent must improve **how humans and AIs build this repo**, not the product ladder.

**Repo:** coreme (`C:\Users\Rau\Desktop\coreme` or the workspace root).
**Date the brief was written:** 2026-08-12.
**Product focus (do not steal):** Fleet F1 done; next product day is Fleet F2 only when GOAL says so. This brief is **devex / agent-ex**, not F2.

---

## 0. Who you are

You are a senior AI-native engineer. You make this repository **faster for agents to index, navigate, implement, prove, and debug**. You do not grow the kernel. You do not invent platform.

Read these skills **before you edit**, in this order:

1. `GOAL.md` — current focus and non-goals (hard wall)
2. `WHY.md` — product model
3. `AGENTS.md` — hard rules for coding agents
4. User skill `writing-for-agents` (`~/.agents/skills/writing-for-agents/SKILL.md` + `SKILL-MECHANICS.md`)
5. User skill `ponytail` (full) — laziest solution that works
6. User skill `codebase-design` — module / interface / depth / seam / locality
7. User skill `skill-design-principles` — one home per fact; no no-ops; no bandaids
8. User skill `coding-standards` — **principles only** (readability, KISS, DRY, YAGNI). Ignore its TypeScript / React / Next.js examples. This repo is Python 3.11.
9. In-repo `skills/build-job/SKILL.md` — Job authoring already exists; do not rewrite it unless a pointer is stale
10. `docs/AGENT_DRILL.md` — cold-agent proof for the Job loop

Also available when a wave needs them: `diagnosing-bugs`, `tdd`, `ponytail-audit`, `improve-codebase-architecture`, `implement`.

**Talk to the human in ASD-STE100 Simplified Technical English.** Short sentences. One idea per sentence. Active voice.

---

## 1. Mission

Make coreme a **high-signal, low-noise workplace for coding agents** so that:

| Outcome | Meaning |
|---------|---------|
| **Faster index** | Embeddings and greps hit source + skills, not `runs/`, `__pycache__`, screenshots, or XML dumps |
| **Faster find** | A cold agent opens maps, not a 20-file grep tour |
| **Faster implement** | One verify command; thin rules; skills load only when needed |
| **Faster debug** | Failed work has a red loop in seconds; Run evidence is the brief |
| **Less drift** | Each fact has one home; AGENTS.md is pointers + traps, not a second GOAL.md |
| **Machine-checkable style** | Lint / format / types catch what used to live as prose |

**Done when** every acceptance box in §12 is true, and you have **not** implemented Fleet F2, Doctor, vault, UI, schedule, or any `docs/LATER.md` row.

---

## 2. Hard walls (do not cross)

These are product law. A “helpful” violation is a fail.

- **Feature filter.** Kernel change only if **every** Job needs it to produce, prove, freeze, re-run, or repair. Otherwise: skill, map, lint, or Job code.
- **Job process never calls an LLM.** Default `coreme run` never spawns Codex.
- **Do not implement** `docs/LATER.md` or Fleet F2+ unless GOAL names it. This brief does not name it.
- **Do not preserve backward compatibility** with obsolete agent files. Delete `.cursorrules`, duplicate `CLAUDE.md`, or stale copies. Do not add compatibility shims.
- **Root stays lean:** `README.md`, `GOAL.md`, `WHY.md`, `AGENTS.md`. A root `_index.md` is the **one** extra file this brief may add (agent map, not product README). Everything else under `docs/` or `skills/`.
- **No new runtime dependencies** for this work. Dev-only tools are allowed only if they earn their keep (see Wave C).
- **No secrets vault, `.env` loader, CLI secret helper, Doctor, heal-until-green, Control Room, chatbot.**
- **Do not bump Job versions or `coreme ship`.**
- **Do not edit `releases/`.**
- **Do not grow a combinatorial test matrix.** Prefer one example + thin e2e.
- **Ponytail.** Delete before you add. Stdlib / existing tools first. No speculative skill pack.

---

## 3. Starting facts (already true — do not re-discover blindly)

Verify these. Treat them as the audit seed, not as scripture.

### Product

- Days 1–7 complete. Fleet F1 = sibling package `src/coreme_agent/` + CLI `coreme-agent`.
- Kernel: small `src/coreme/` (stdlib + Rich only).
- Job skill pack: `skills/build-job/` (SKILL + clarify, phases, operator-report, run-events, repair, browser, OPS, shortcut, JOB-TEMPLATE).
- Cold Job drill: `docs/AGENT_DRILL.md`.
- Proof style: real Job under `examples/` + thin e2e in `tests/test_examples.py`.

### Agent surface (gaps)

| Gap | Evidence |
|-----|----------|
| **AGENTS.md is a cache of GOAL** | Restates Days 1–7, Fleet, secrets, phases, repair. High context load every turn. writing-for-agents wants **hard traps + pointers**, not a second product spec. |
| **No agent maps** | No root `_index.md` (path / concept / task). `implement` and `writing-for-agents` expect them. Cold kernel work starts with blind grep. |
| **No module AGENTS** | `src/coreme/` and `src/coreme_agent/` have no local rules. Different packages, same global dump. |
| **No kernel skill** | Only Job-authoring skill exists. Kernel implement / debug / verify have no invokable workflow. |
| **Lint is thin** | `pyproject.toml` ruff select = `E4, E7, E9, F, B` only. No format config. No `I` (imports), `UP`, `SIM`, `RUF`, `PTH` (this repo is path-heavy and Windows-first). |
| **Types have escape hatches** | mypy disables `attr-defined` on `coreme._process`, `coreme.cli`, `coreme_agent.executor`. |
| **No CI** | No `.github/`. Agents and humans have no shared gate. |
| **No one-command verify** | AGENTS says `ruff check src tests` and `mypy src`. No `ruff format`, no script, no `just`/`make` target. |
| **Index poison** | Workspace holds large `runs/` (PNG, XML, logs) and `releases/`. Gitignored, but **editors still embed them** unless `.cursorignore` / tool ignores exist. |
| **`.gitignore` lists `examples/`** | Examples are the product teaching surface. Confirm whether they are tracked. If ignored, agents on a fresh clone lose the answer key. |
| **Stale bytecode** | `__pycache__` has `models.cpython-311.pyc` and `secrets.cpython-311.pyc` with **no matching `.py`**. Dead index noise. |
| **Wrong shared coding-standards** | User `coding-standards` skill is TypeScript/React. Do not paste it into this repo. Write a **thin Python/coreme** standard or encode it in ruff. |
| **No CONTEXT.md / ADRs** | Domain terms live in GOAL/WHY. Fine for now. Do **not** invent a docs platform. A short concept map row is enough. |
| **2026 layer mix is missing** | Portable `AGENTS.md` exists but is bloated. No glob-scoped Cursor rules. No ignore files for embeddings. Skills are not split ambient vs invokable for **kernel** work. |

### 2026 defaults this brief assumes (cite, then adapt)

- **Layered agent context:** `AGENTS.md` = ambient “how we code”; Skills = invokable “how we ship this kind of change”; MCP = live data. They are layers, not competitors.
- **Cursor (and cousins) read `AGENTS.md` natively**, including nested files. Prefer one portable `AGENTS.md` over a parallel `.cursorrules`. Use `.cursor/rules/*.mdc` **only** for glob-scoped extras that AGENTS cannot express. Never duplicate the same rule in both.
- **Rules stay short.** Point at canonical files. Put style in the linter. Add a rule only after the agent repeats a mistake.
- **Plan before large edits.** Wave A–B are design; wait for human “go” before rewriting AGENTS.md.
- **Verifiable goals.** Agents iterate against ruff / types / pytest, not vibes.
- **Python 2026 toolchain to evaluate, not blindly adopt:** `uv` + Ruff (lint+format) + `ty` (Astral type checker, ~10–60× mypy). **Do not replace mypy in this pass** unless you prove `ty` matches current checks and the human agrees. You may add `ty` as a **shadow** command in the verify script.

---

## 4. Operating principles

Use these **leading words**. Repeat the token, not a paragraph.

| Token | Meaning here |
|-------|----------------|
| **pointer** | One line that names a doc and the branches that should open it |
| **map** | `_index.md` path / concept / task rows — navigate before grep |
| **trap** | A hard rule that prevents a repeated, expensive mistake |
| **ambient** | Always-loaded (AGENTS.md). Pay tokens every turn. Earn it. |
| **invokable** | Skill loaded only when the branch fires |
| **verify** | One command: lint + format check + types + tests |
| **tight** | Fast, deterministic, red-capable feedback loop |
| **sediment** | Stale restated prose. Delete or disclose. |
| **one home** | Each fact lives in one file; others point |
| **source-first** | Edit Job source; ship only on explicit ask |
| **feature filter** | Kernel only if every Job needs it |

**Positive over negation.** Write “open `fail.json` then `log.txt`” not a long “do not invent root cause” sermon. A prohibition earns a line only as a trap you cannot phrase as a target.

**Environment over cache.** Do not restate `pyproject.toml` scripts or `--help` in AGENTS.md. Cache only the gotcha the config does not confess.

**Prune as you add.** Every new AGENTS line, skill paragraph, or map row must retire at least as much restated text elsewhere, or justify why the new fact had no home.

---

## 5. How to run this brief

### 5.1 Mode

1. **Audit first** (Wave 0). Write findings. Do not rewrite AGENTS.md yet.
2. **Grill the human** on the decisions in §6. Batch questions. Recommend defaults.
3. After answers (or if the human says “use your defaults”), execute **Wave A → E in order**. Stop after any wave if the human says stop.
4. After each wave: run **verify**. Paste the command and exit codes.
5. Do not start a second large refactor in the same turn as a map rewrite.

### 5.2 Defaults if the human is silent

Use these. Do not stall.

| Decision | Default |
|----------|---------|
| Root `_index.md` | **Add it.** Agent map, not a product README. Keep GOAL/WHY as product truth. |
| Nested `AGENTS.md` | Add `src/coreme/AGENTS.md` and `src/coreme_agent/AGENTS.md` only if each has **≥3 traps** that do not belong globally. Otherwise one root file + map rows. |
| `.cursor/rules` | Skip unless you have a real glob split (e.g. Job `main.py` vs kernel). Prefer AGENTS.md. |
| Ruff expand | Yes: `I`, `UP`, `SIM`, `RUF`, `PTH`, keep `B`. Autofix safe rules. Do not enable a noisy nursery set. |
| Ruff format | Yes. Match existing line length (measure first; do not invent 88 vs 100 as a debate — pick the current median). |
| mypy vs ty | Keep mypy as gate. Optional: document `ty check src` as shadow. Do not drop mypy this pass. |
| uv | **Do not migrate the package manager** unless the human asks. pip + `pip install -e ".[dev]"` stays. |
| CI | Add a **minimal** GitHub Actions workflow: ruff + mypy + pytest on pull_request/push. Windows latest **or** ubuntu — pick one runner first (ubuntu is cheaper; add windows only if path tests need it). Prefer proving path tests already pass on the existing suite. |
| examples/ in gitignore | If examples are tracked: remove `examples/` from `.gitignore`. If they are intentionally local-only: say so in the map and stop. **Recommended:** examples are product — they belong in git. |
| New skills | Add **at most three** in-repo skills (see Wave D). User-global skills stay in `~/.agents/skills`. Do not copy TS coding-standards into the repo. |
| CONTEXT.md / ADR tree | **Do not create.** Concept map rows replace them for now. |
| ponytail-audit | Run it as a **read-only** pass in Wave 0. Apply only deletions that are obviously safe (dead pyc, ignore files). Deeper architecture → list, do not execute. |

### 5.3 Proof after every wave

```powershell
python -m pip install -e ".[dev]"   # only if env is missing tools
ruff check src tests
ruff format --check src tests
mypy src
pytest -q
```

After Wave C, these must be the **same** commands the verify script runs. After agent-facing edits, also walk `docs/AGENT_DRILL.md` mentally: would a cold Job-author still pass? If you changed skill pointers, say how.

---

## 6. Grill the human (batch — once)

Ask only if they did not already say “use defaults”. One message. Recommended default in each option.

1. **Maps vs lean root.** Add root `_index.md` (recommended) or keep maps under `docs/agent-map.md` and pointer from AGENTS?
2. **CI OS.** ubuntu-only (recommended first) or windows-latest (matches this machine)?
3. **Ruff aggressiveness.** Safe set in §5.2 (recommended) or also `N` (naming) / `ANN` (annotations)?
4. **ty.** Shadow only (recommended) or try as mypy replacement in a follow-up?
5. **Skills location.** In-repo `skills/devex/` (recommended, next to `skills/build-job/`) or only user-global `~/.agents/skills`?
6. **Scope cap.** All waves A–E (recommended) or stop after A+B (index + AGENTS + maps) this session?

Then proceed.

---

## 7. Wave 0 — Audit (read-only)

**Done when** you have a scorecard the human can scan in one screen.

Measure:

1. **Token / file inventory** (approx). Count lines and role of: `AGENTS.md`, `GOAL.md`, `WHY.md`, `skills/build-job/*`, `src/coreme/*.py`, `src/coreme_agent/*.py`. Note duplication (same meaning in two files).
2. **Index surface.** List folders an editor will embed if no extra ignore exists (`runs/`, `releases/`, `.venv/`, `__pycache__/`, `*.egg-info`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.review-state/`, large fixtures).
3. **Hot files.** `git log --oneline -30` — where edits actually land.
4. **Lint baseline.** Run current `ruff check src tests` and `mypy src`. Record counts. Preview what a wider select would flag (do not fix yet).
5. **Ponytail-audit (read-only).** Rank delete / simplify / stdlib. Do not apply except Wave A hygiene.
6. **Skill inventory.** In-repo vs user-global. Which are ambient (always tempting) vs invokable. Which are dead (TS standards for a Python kernel).
7. **Sediment hunt.** Lines in AGENTS.md that only repeat GOAL/WHY/DAY plans.

Output a table:

| Area | Now | Cost | Wave |
|------|-----|------|------|
| … | … | high/med/low | A–E |

Do not edit product code in Wave 0.

---

## 8. Wave A — Faster index (do this first; smallest risk)

**Goal:** embeddings and search skip junk. Agents see source + docs + skills.

**Done when:**

- [ ] `.cursorignore` exists and excludes at least: `runs/`, `releases/`, `.venv/`, `**/__pycache__/`, `*.egg-info/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.review-state/`, `.coreme-seed/`, `**/*.pyc`
- [ ] Same patterns mirrored where cheap: `.ignore` or `.repomixignore` (for Repomix / GitIngest packs). Do **not** create five nearly-identical files if one `.cursorignore` + gitignore is enough — prefer **one extra ignore file** plus a pointer. If you add `.repomixignore`, it is a thin copy of the cursor ignore.
- [ ] `.gitignore` still ignores `runs/` and `releases/`. Decision on `examples/` recorded and applied (default: **un-ignore** `examples/` so the teaching surface is in git).
- [ ] Stale `__pycache__` without source is deleted (local only; they should already be gitignored).
- [ ] Optional `repomix.config.json` **only if** you also add a one-line pointer. Profiles worth having: `kernel` (`src/coreme`), `agent` (`src/coreme_agent`), `job-skill` (`skills/build-job`). Skip if you would only write a config nobody runs.

**Why this is first:** a polluted index makes every later wave slower. `runs/` on this machine already holds many PNG/XML dumps.

**Do not** add a pack-the-repo CI job. That is platform.

---

## 9. Wave B — AGENTS.md, maps, nested rules

**Goal:** a cold agent finds the right file in one hop.

### 9.1 Rewrite root `AGENTS.md`

Target shape (writing-for-agents):

1. **Hard traps** (short, checkable) — examples that belong:
   - Job code never calls an LLM
   - Default `coreme run` does not spawn Codex
   - Source-first: `coreme run ./<job>`; bare name is ops after ship
   - Feature filter + do not implement LATER / un-named Fleet stages
   - Never edit `releases/`
   - Secrets: names in Job, values in process env, never in structured evidence
   - Fail: read `fail.json` then log/events; do not invent root cause
   - Never dual-write TTY + CONOUT$
   - Verify command (pointer to script or the four commands — not both)
2. **Discovery protocol** — numbered: GOAL → (day plan if named) → WHY → this file → `_index.md` → owning module → skill
3. **Pointers with leading words and branches** — one trigger per branch. Example:
   - **Job** author / change / prove / ship → `skills/build-job/SKILL.md`
   - **Repair** failed Run / brief / auto-repair → `skills/build-job/repair.md`
   - **Phases** / seed-from-fail → `skills/build-job/phases.md`
   - **Kernel implement** → `skills/devex/implement-kernel.md` (after Wave D)
   - **Debug kernel / test red** → `skills/devex/debug-kernel.md`
   - **Maps** → `_index.md`
4. **Style one-liner** that points at the linter: “Python 3.11, stdlib first, Windows paths; `ruff` + `mypy` are the style guide.”

**Delete** restated Day 1–7 narrative, Fleet essays, and operator-report dumps from AGENTS.md. Those live in GOAL / day plans / skills.

**Budget:** aim **≤ 80 lines**. If you need more, you failed to disclose.

### 9.2 Add root `_index.md`

Keep ~40–60 lines. Sections:

- **Status** — one line: Days 1–7 done; Fleet F1 done; F2 next when GOAL says; this repo is a Job kernel + sibling agent package
- **Path map** — `src/coreme/`, `src/coreme_agent/`, `skills/build-job/`, `examples/`, `tests/`, `docs/`
- **Concept map** (product language → owning module → start file). Required rows at least:

  | Concept | Owner | Start |
  |---------|-------|-------|
  | Job / JOB.toml | kernel | `src/coreme/manifest.py` |
  | Run / evidence | kernel | `src/coreme/runner.py` |
  | Release / hash | kernel | `src/coreme/ship.py` |
  | Resolve name vs path | kernel | `src/coreme/resolve.py` |
  | Secrets names | kernel | `src/coreme/inputs.py` or the real module you find |
  | Events / fail.json | kernel | `src/coreme/events.py` |
  | Repair / brief | kernel | `src/coreme/brief.py`, `repair.py` |
  | Operator TTY | kernel | `src/coreme/present.py`, `joblog.py` |
  | Fleet local queue | agent pkg | `src/coreme_agent/store.py` |
  | Job authoring | skill | `skills/build-job/SKILL.md` |

- **Task map** — class of work → read first:

  | Task | Open first |
  |------|------------|
  | Change Job contract / CLI parse | `manifest.py`, `inputs.py` |
  | Change run lifecycle | `runner.py`, `events.py` |
  | Change ship / hash | `ship.py` |
  | Change repair | `brief.py`, `repair.py`, `skills/build-job/repair.md` |
  | Write a Job | `skills/build-job/SKILL.md` |
  | Change local agent queue | `src/coreme_agent/` + `docs/days/FLEET.md` (do not implement F2) |
  | Change agent-facing docs | this brief + `docs/AGENT_DRILL.md` |

Update `docs/README.md` with one row for `_index.md`. Do not duplicate the maps there.

### 9.3 Nested AGENTS.md

Only if the grill default in §5.2 says so **and** you found real local traps (e.g. agent package: SQLite queue, never import from `coreme` internals the wrong way — **verify** the actual import rule before writing it).

### 9.4 Same-change maintenance rule

Add one trap: if you add/rename/move a public module, CLI command, or product concept, you update `_index.md` in the **same change**. Phantom map names are defects.

**Done when:** a stranger can answer “where does resolve live?” from `_index.md` without grep; AGENTS.md no longer restates GOAL; `docs/README.md` points at the map.

---

## 10. Wave C — Lint, format, types, verify, CI

**Goal:** the machine is the coding standard. Prose shrinks.

### 10.1 Ruff

In `pyproject.toml`:

- Keep `target-version = "py311"`.
- Enable lint: existing + `I`, `UP`, `SIM`, `RUF`, `PTH` (pathlib — this codebase is Windows-path sensitive). Keep `B`.
- Set `ruff.format` explicitly (quote style, line length measured from current files).
- Autofix what is safe. Do not reformat `examples/` unless they are first-class and tests still pass.
- If a rule fights a hard product choice (e.g. a deliberate `print(..., flush=True)`), configure that rule — do not scatter `# noqa` without a comment naming why.

### 10.2 mypy

- Keep current strict-ish flags.
- **Remove** `attr-defined` overrides by fixing the types, or shrink the override to the exact symbol. Escape hatches are sediment.
- Do not turn on `disallow_untyped_defs` for the whole tree in this pass unless the fix is small. Note it as follow-up.

### 10.3 Verify script (Windows-first)

Add **one** script the agent can run. Prefer PowerShell because this machine is Windows:

`scripts/verify.ps1`

It must:

1. `ruff check src tests`
2. `ruff format --check src tests`
3. `mypy src`
4. `pytest -q`

Exit nonzero on first failure. No extra framework. No Makefile required (ponytail: one script).

Point AGENTS.md at this script. Do not also paste the four commands unless the script does not exist yet.

Optional second script `scripts/fix.ps1` = `ruff check --fix` + `ruff format`. Nice; not required.

### 10.4 CI

Minimal GitHub Actions:

- Trigger: `push` + `pull_request`
- `pip install -e ".[dev]"` then the same four steps as the script
- No deploy, no codecov, no matrix of Python versions unless you have a reason (3.11 only is enough)

### 10.5 ty (shadow)

If you mention ty in AGENTS or README, label it **optional / shadow**. Do not add it as a hard gate without human OK.

**Done when:** verify script is green locally; CI file exists; ruff select is expanded; mypy overrides are gone or justified in one comment; AGENTS style section is a pointer to the tools.

---

## 11. Wave D — Skills (few, sharp)

**Goal:** invokable workflows for kernel work. Do not clone `build-job`. Do not write a 400-line style guide.

Create `skills/devex/` (or the location the human chose). Each skill: frontmatter + short steps with **Done:** lines. Follow `skill-design-principles` and `SKILL-MECHANICS.md`.

### 11.1 Must add (max three)

**1. `skills/devex/implement-kernel.md`** (model-invoked if you can write a tight description; else user-invoked)

Branches: change kernel CLI, runner, ship, resolve, events, repair coordinator, agent package **behavior**.

Steps:

1. Read GOAL + feature filter. Stop if this is a Job-only or LATER item.
2. Open `_index.md` → owning module → local AGENTS if any.
3. Plan: files, seam, tests (example + thin e2e or unit at the public interface).
4. Implement smallest path. No compatibility layer.
5. Run `scripts/verify.ps1`. Update maps if structure changed.
6. If agent-facing: note AGENT_DRILL impact.

**2. `skills/devex/debug-kernel.md`** (or `debug-from-evidence.md`)

Branches: test red, CLI unexpected exit, failed Run, flaky path, “it works in chat but proof fails”.

Steps adapted from `diagnosing-bugs`, **coreme-shaped**:

1. Build a **tight** loop first (`pytest -q tests/test_X.py::test_Y` or `coreme run ./examples/...`).
2. If a Run exists: `fail.json` → `coreme brief` → `events.jsonl` → `log.txt`. Do not invent cause.
3. 3–5 falsifiable hypotheses. Change one variable.
4. Fix at the shared function, not one caller.
5. Leave one regression test at the public seam.
6. Remove debug tags.

**3. `skills/devex/SKILL.md` (router, user-invoked)**

Human index only: when to use implement-kernel vs debug-kernel vs `build-job` vs ponytail-audit vs AGENT_DRILL. It must not restate those files.

### 11.2 Do not add in this pass

- A pasted TypeScript coding-standards skill
- Doctor / heal / grind-until-green hook as a product
- CONTEXT.md writer / ADR factory
- “75 skills” pack
- Duplicate `build-job` as “build-kernel”

### 11.3 Optional user-global (only if you already maintain `~/.agents/skills`)

A **Python** coding-standards skill that replaces the TS one **for this user** is out of scope unless the human asks. Encode style in ruff first.

### 11.4 Pointers

Wire the new skills from root AGENTS.md (one line each) and `_index.md` task map. Update `docs/README.md` with one row.

**Done when:** three files exist; each has checkable Done lines; no duplicated build-job content; descriptions (if model-invoked) list real trigger branches only.

---

## 12. Wave E — Faster implement + debug (docs and loops, not platform)

**Goal:** the daily loop is obvious and short.

### 12.1 Document the implement loop (in implement-kernel + one AGENTS pointer)

```text
map → smallest test or example → code → scripts/verify.ps1 → update map if structure moved
```

TDD when a seam already exists (`tests/` for kernel contracts). Prefer `examples/` + `tests/test_examples.py` for new **product** behavior.

### 12.2 Document the debug loop (in debug-kernel)

```text
tight red command → evidence (fail.json / brief / events) → hypotheses → one-variable probe → fix at shared seam → regression → verify
```

### 12.3 AGENT_DRILL stay green

If you changed skill pointers or AGENTS discovery, add **one optional stretch row** to `docs/AGENT_DRILL.md` only if it is about **finding** the skill, not a new kernel feature. Do not grow a drill platform.

### 12.4 README

One short “Develop” subsection: install `.[dev]`, run `scripts/verify.ps1`. Do not turn README into AGENTS.md.

### 12.5 Ideas you may implement if still cheap after A–D

Only if each is < ~20 minutes and ponytail-clean:

| Idea | Do if |
|------|--------|
| `ruff` pre-commit config | You already wanted CI; pre-commit is optional duplicate — **skip** if CI + verify script exist |
| EditorConfig | Skip unless mixed newline issues appear |
| `pytest` markers `unit` / `e2e` | Only if the suite is slow enough to hurt the tight loop |
| `scripts/pack-kernel.ps1` wrapping Repomix/GitIngest for kernel-only dump | Only if you use chat models without repo tools |
| Delete dead comments / unused imports found by ruff | Yes, as part of Wave C |

**Done when:** implement and debug loops are written once; README has verify; AGENT_DRILL still coherent; no new daemon, hook grind, or MCP server.

---

## 13. Acceptance (all must be true)

- [ ] Wave 0 scorecard was produced
- [ ] Index ignores exist; `runs/` / pycache / venv are not default embed fodder
- [ ] `examples/` gitignore decision applied
- [ ] Root `AGENTS.md` is traps + pointers, not a GOAL clone; roughly ≤ 80 lines
- [ ] Root `_index.md` has path, concept, and task maps; concept rows use product words (Job, Run, Release, …)
- [ ] `docs/README.md` updated; no second copy of the maps
- [ ] Ruff expanded + format check; mypy still gate; verify script green
- [ ] CI runs the same checks
- [ ] ≤ 3 new devex skills; build-job not rewritten
- [ ] `scripts/verify.ps1` + `pytest -q` + `ruff check` + `mypy src` all green
- [ ] No LATER / F2 / Doctor / vault / UI code
- [ ] No new runtime dependency
- [ ] Phantom names: grep for old filenames you deleted; fix pointers
- [ ] Final report to the human: what changed, what was skipped, what to do next (one screen)

---

## 14. Ranked idea backlog (do **not** all implement)

After acceptance, list these as **next**, strongest first. Do not start them unless the human picks.

### High leverage

1. **Replace mypy with ty** after a shadow week (Astral; huge incrementals). Keep a recorded miss-list.
2. **Kernel coding standard as ruff only** — delete remaining style prose.
3. **Hot-spot deepening** (`cli.py`, `runner.py`, repair trio) via `improve-codebase-architecture` — design-it-twice, then one deepening. Not a rewrite.
4. **Fail the CI if `_index.md` concept names have no matching file** (tiny test, not a platform).
5. **Job-author vs kernel-author split in the first AGENTS pointer** so cold agents stop loading build-job when changing `resolve.py`.

### Medium

6. **uv lock** for reproducible agent installs (`uv sync --extra dev`) — only with human OK.
7. **Windows + ubuntu CI** once ubuntu is green.
8. **Repomix kernel profile** for pasting into web LLMs.
9. **`coreme` help text as source of truth** — AGENTS never lists flags.
10. **Example `JOB.md` quality pass** so maps can point at one canonical Job.
11. **Delete or quarantine huge local `runs/`** so even un-ignored tools stay fast.
12. **User-global Python standards skill** (replace TS coding-standards for this user).

### Lower / later

13. Cursor glob rules for `examples/**/main.py` (Job traps: flush, no LLM, `say_fail`) vs `src/coreme/**`.
14. `ty` + ruff as the only LSP (editor setting, not repo law).
15. Worktree policy for parallel agents (document one paragraph when you actually run two writers).
16. Debug Mode / evidence attach: `fail.png` already exists for Jobs; kernel tests should stay headless.
17. Hooks that re-run verify on stop — only after verify is boringly green; cap iterations.
18. Semantic-search hints in `_index.md` (synonyms: “freeze” → ship, “packet” → Job).
19. Measure index time before/after ignores (Cursor / tool logs) and record the number in the report.
20. Cold **kernel** drill (sibling of AGENT_DRILL): “add a flag that is rejected if unknown” without reading chat history.

### Reject (name them so future you does not build them)

- A second orchestrator for agents
- Generated always-on “repo digest” committed to git
- Copying 75 public agent skills into this repo
- Putting hub HTTP in the kernel to “help the AI”
- Enabling every ruff rule
- `disallow_any` / 100% annotation drive as a vanity metric
- Compatibility `CLAUDE.md` that duplicates AGENTS.md

---

## 15. Report format (end of mission)

```text
## AI-native pass

Index: …
AGENTS / maps: … (line counts before → after)
Lint / types / CI: …
Skills added: …
Verify: <paste>
Skipped (ponytail): …
Next (pick one): …
Did not touch: F2, LATER, Job versions, releases
```

If you had to choose between a clever map system and a green verify script, ship the script.

---

## 16. First action

Start at **Wave 0**. Do not rewrite AGENTS.md in the same breath as the audit. Show the scorecard, ask the grill (or apply defaults), then execute Wave A.
