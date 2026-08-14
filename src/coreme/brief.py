"""Assemble a repair brief from a Run folder (fail.json + log + events + run.json).

Used by ``coreme brief``, ``coreme repair``, and auto-repair after a failed Run.
No secret values: inputs keys/values (non-secret), secret **names** only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from coreme.events import fail_path, read_events, read_fail_summary

DEFAULT_LOG_LINES = 80

# Crash-ish lines to lift into a short "smoking gun" for agents.
_CRASH_LINE = re.compile(
    r"(?i)("
    r"traceback \(most recent call last\)|"
    r"^\s*file \".+\", line \d+|"
    r"\w*(?:error|exception|timeout|failed|failure)\s*:|"
    r"timeout(?:error)?\b|"
    r"winerror\s*\d+|"
    r"permissionerror|"
    r"locator\.(?:click|fill|goto)|"
    r"waiting for locator|"
    r"systemexit|"
    r"assert(?:ion)?error"
    r")"
)


def assemble_brief(
    run_path: str | Path,
    *,
    log_lines: int = DEFAULT_LOG_LINES,
    source_path: str | Path | None = None,
) -> str:
    """Build markdown brief for a Run. Works for failed and non-failed Runs."""
    root = Path(run_path).resolve()
    if not root.is_dir():
        raise BriefError(f"not a Run directory: {run_path}")

    run = _load_json(root / "run.json")
    fail = read_fail_summary(root)
    events = read_events(root)
    full_log = _read_log(root / "log.txt")
    log_tail = _tail_text(full_log, log_lines)
    crash = extract_crash_signature(full_log)
    fail_png = _find_fail_png(root)

    job = (run or {}).get("job") or (fail or {}).get("job") or "?"
    version = (run or {}).get("version") or (fail or {}).get("version") or "?"
    status = (run or {}).get("status") or (fail or {}).get("status") or "?"
    exit_code = (run or {}).get("exit_code")
    if exit_code is None and fail is not None:
        exit_code = fail.get("exit_code")
    is_fail = (
        bool(fail)
        or status not in {"succeeded", "success"}
        or (exit_code is not None and int(exit_code) != 0)
    )

    lines: list[str] = []
    lines.append("# coreme repair brief")
    lines.append("")
    if is_fail:
        lines.append("**Status:** FAILED Run — repair the **source** Job, not a release.")
    else:
        lines.append("**Status:** non-failure / success Run — no automatic Codex repair expected.")
    lines.append("")
    lines.append("## Header")
    lines.append("")
    lines.append(f"- **job:** `{job}`")
    lines.append(f"- **version:** `{version}`")
    lines.append(f"- **status:** `{status}`")
    lines.append(f"- **exit_code:** `{exit_code}`")
    lines.append(f"- **run_path:** `{root}`")
    if fail is not None:
        lines.append(f"- **fail.kind:** `{fail.get('kind', '?')}`")
        lines.append(f"- **fail.message:** {fail.get('message', '')}")
    lines.append("")

    lines.append("## Crash signature (smoking gun)")
    lines.append("")
    if crash:
        lines.append("```text")
        lines.append(crash)
        lines.append("```")
    else:
        lines.append("_No clear traceback/error block extracted from log.txt._")
    if fail_png is not None:
        lines.append("")
        lines.append(f"- **fail screenshot:** `{fail_png}`")
    lines.append("")

    lines.append("## Failed step")
    lines.append("")
    if fail and isinstance(fail.get("failed_step"), dict) and fail["failed_step"]:
        fs = fail["failed_step"]
        lines.append(f"- step: `{fs.get('step', '?')}`")
        if fs.get("name"):
            lines.append(f"- name: `{fs['name']}`")
        if fs.get("message"):
            lines.append(f"- message: {fs['message']}")
    else:
        lines.append("_No `step.fail` recorded (or not a process fail)._")
    if fail and isinstance(fail.get("last_step"), dict) and fail["last_step"]:
        ls = fail["last_step"]
        lines.append(
            f"- last_step: `{ls.get('event', '?')}` "
            f"step={ls.get('step', '?')} name={ls.get('name', '')}"
        )
    lines.append("")

    lines.append("## Job / release")
    lines.append("")
    if run:
        lines.append(f"- **job_path:** `{run.get('job_path', '')}`")
        lines.append(f"- **release:** `{run.get('release', False)}`")
        if run.get("content_hash"):
            lines.append(f"- **content_hash:** `{run['content_hash']}`")
    else:
        lines.append("_run.json missing_")
    lines.append("")

    lines.append("## Source path (edit here only)")
    lines.append("")
    if source_path is not None:
        lines.append(f"- **Resolved source:** `{Path(source_path).resolve()}`")
        lines.append("- Patch files under this directory. **Never** edit `releases/`.")
    else:
        lines.append(
            "- **STOP: no source resolved.** Do not guess. Do not patch under `releases/`."
        )
        if run and run.get("release"):
            lines.append(
                f"- This was a **release** run (`job_path` = `{run.get('job_path', '')}`). "
                "Find the matching source Job folder with the same `name` in JOB.toml."
            )
        elif run:
            lines.append(f"- job_path from run.json: `{run.get('job_path', '')}`")
    lines.append("")

    lines.append("## Inputs (not secrets)")
    lines.append("")
    inputs = (run or {}).get("inputs") or {}
    if isinstance(inputs, dict) and inputs:
        for key, value in sorted(inputs.items()):
            lines.append(f"- `{key}` = `{value}`")
    else:
        lines.append("_none_")
    lines.append("")

    lines.append("## Secret names (values never in this brief)")
    lines.append("")
    secrets = (run or {}).get("secrets") or []
    if secrets:
        for name in secrets:
            lines.append(f"- `{name}` (process env only; do not print or paste values)")
    else:
        lines.append("_none declared_")
    lines.append("")

    lines.append("## Evidence paths (absolute)")
    lines.append("")
    lines.append(f"- run.json: `{root / 'run.json'}`")
    lines.append(f"- log.txt: `{root / 'log.txt'}`")
    lines.append(f"- events.jsonl: `{root / 'events.jsonl'}`")
    fp = fail_path(root)
    if fp.is_file():
        lines.append(f"- fail.json: `{fp}`")
    art = root / "artifacts"
    if art.is_dir():
        lines.append(f"- artifacts/: `{art}`")
    if fail_png is not None:
        lines.append(f"- fail.png: `{fail_png}`")
    lines.append("")

    lines.append(f"## Log tail (last {log_lines} lines)")
    lines.append("")
    lines.append("```text")
    lines.append(log_tail if log_tail else "(empty log)")
    lines.append("```")
    lines.append("")

    lines.append("## Events tail (step.* + run.end / timeout / error)")
    lines.append("")
    event_lines = _events_tail(events)
    if event_lines:
        lines.append("```text")
        lines.extend(event_lines)
        lines.append("```")
    else:
        lines.append("_no matching events_")
    lines.append("")

    lines.append("## Instructions")
    lines.append("")
    lines.append("1. Trust the **Crash signature** first; then `fail.json`, log, events.")
    lines.append("2. Edit the **source** Job only. Never write into `releases/`.")
    lines.append(
        "3. Do **not** add, enable, or reuse Job-owned runtime Codex / LLM. "
        "Repair is a post-fail coordinator, not the Job's runtime-AI path."
    )
    lines.append("4. One focused fix; do not refactor unrelated code.")
    lines.append(
        "5. Read only: this brief, fail.json, log tail, and source files named in the traceback."
    )
    lines.append("6. Do **not** load extra monorepo skills/docs unless the crash is still unclear.")
    lines.append(
        "7. After a patch: offline first — `coreme test <source>` then offline `coreme run` if useful."
    )
    lines.append(
        "8. Live browser re-proof only when the host allows it; sandbox limits are not root causes."
    )
    lines.append(
        "9. **Do not ship** unless a human explicitly asked to ship / bump / freeze / release."
    )
    lines.append("10. Never put secret **values** in code, git, briefs, or evidence. Names only.")
    lines.append("")
    lines.append("## Done when")
    lines.append("")
    lines.append("1. Offline proof is green: `coreme test <source>`.")
    lines.append("2. The crash signature no longer applies for the same offline path.")
    lines.append("3. You report: files changed + one-line root cause (no secret values).")
    lines.append("")
    return "\n".join(lines)


def extract_crash_signature(log_text: str, *, max_lines: int = 30) -> str:
    """Lift a short traceback / error block from a Job log for agent prompts."""
    if not log_text or not log_text.strip():
        return ""
    lines = log_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # Prefer last Traceback block through the final error line.
    tb_idx = None
    for i, line in enumerate(lines):
        if "traceback (most recent call last)" in line.lower():
            tb_idx = i
    if tb_idx is not None:
        block = lines[tb_idx : tb_idx + max_lines]
        # Trim trailing blank lines.
        while block and not block[-1].strip():
            block.pop()
        return "\n".join(block).strip()

    # Else: collect recent crash-ish lines (and one context line before each).
    hits: list[str] = []
    for i, line in enumerate(lines):
        if _CRASH_LINE.search(line):
            # Keep immediate context once.
            if (
                i > 0
                and lines[i - 1].strip()
                and lines[i - 1] not in hits
                and (not hits or hits[-1] != lines[i - 1])
            ):
                hits.append(lines[i - 1])
            hits.append(line)
    if not hits:
        # Last non-empty lines as weak signal.
        nonempty = [ln for ln in lines if ln.strip()]
        return "\n".join(nonempty[-min(8, len(nonempty)) :]).strip()
    if len(hits) > max_lines:
        hits = hits[-max_lines:]
    return "\n".join(hits).strip()


def find_fail_png(run_path: str | Path) -> Path | None:
    """Return artifacts/fail.png if present."""
    return _find_fail_png(Path(run_path).resolve())


class BriefError(Exception):
    """Brief assembly failed (missing Run path, etc.)."""


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_log(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tail_text(text: str, n: int) -> str:
    if not text or n <= 0:
        return ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # Preserve trailing empty only if original ended that way? strip end blanks for tail.
    if len(lines) <= n:
        return text.rstrip("\n")
    return "\n".join(lines[-n:])


def _find_fail_png(root: Path) -> Path | None:
    candidate = root / "artifacts" / "fail.png"
    return candidate if candidate.is_file() else None


def _events_tail(events: list[dict[str, Any]]) -> list[str]:
    keep = {
        "step.start",
        "step.ok",
        "step.skip",
        "step.fail",
        "run.end",
        "run.timeout",
        "run.error",
        "idle",
    }
    out: list[str] = []
    for row in events:
        if row.get("event") not in keep:
            continue
        parts = [str(row.get("ts", ""))[:19], str(row.get("event", ""))]
        if "step" in row:
            parts.append(f"step={row['step']}")
        if row.get("name"):
            parts.append(str(row["name"]))
        if row.get("status"):
            parts.append(f"status={row['status']}")
        if row.get("exit_code") is not None and row.get("event") != "run.start":
            parts.append(f"exit={row['exit_code']}")
        if row.get("message"):
            parts.append(str(row["message"]))
        out.append(" ".join(parts))
    # Cap to last ~40 matching lines for prompt size.
    if len(out) > 40:
        out = out[-40:]
    return out
