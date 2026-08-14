"""Host Codex CLI discovery, cleaned env, and spawn for repair.

Defaults favor **repair authority** (danger-full-access, host env minus secrets,
quiet tee to the Run folder). Override via env / argv builders.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from coreme.util import env_flag

# Host Codex can take a long time; avoid infinite hang without a bound.
DEFAULT_CODEX_TIMEOUT_SEC = 3600

# Default sandbox for repair: full host access so Playwright / prove can run.
# Override: COREME_CODEX_SANDBOX=workspace-write|read-only|danger-full-access|bypass
DEFAULT_SANDBOX = "danger-full-access"
SANDBOX_ENV = "COREME_CODEX_SANDBOX"
PROFILE_ENV = "COREME_CODEX_PROFILE"
VERBOSE_ENV = "COREME_CODEX_VERBOSE"
INHERIT_ENV_FLAG = "COREME_CODEX_INHERIT_ENV"
FULL_HOST_ENV_FLAG = "COREME_CODEX_FULL_HOST_ENV"
IGNORE_USER_CONFIG_ENV = "COREME_CODEX_IGNORE_USER_CONFIG"

CODEX_LOG = "codex.log"
CODEX_SUMMARY = "repair-summary.md"

_VALID_SANDBOX = frozenset({"read-only", "workspace-write", "danger-full-access", "bypass"})

# Env keys we always keep for Codex auth / shell (plus PATH and CODEX_*).
_KEEP_ENV_EXACT = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "APPDATA",
        "LOCALAPPDATA",
        "USERNAME",
        "USER",
        "LOGNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
        "CODEX_HOME",
        "OPENAI_API_KEY",  # common Codex auth; values not put in brief
        "CHATGPT_ACCOUNT_ID",
        "VIRTUAL_ENV",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONUTF8",
        "PYTHONIOENCODING",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
    }
)


def find_codex() -> str | None:
    """Return path to host ``codex`` CLI, or None if missing."""
    for name in ("codex", "codex.cmd", "codex.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None


def resolve_sandbox(override: str | None = None) -> str:
    """Sandbox mode for repair spawn."""
    raw = (override if override is not None else os.environ.get(SANDBOX_ENV, "")).strip()
    if not raw:
        return DEFAULT_SANDBOX
    key = raw.lower().replace("_", "-")
    if key in {"full", "danger", "danger-full", "unrestricted"}:
        key = "danger-full-access"
    if key in {"none", "off", "unsandboxed", "yolo"}:
        key = "bypass"
    if key not in _VALID_SANDBOX:
        return DEFAULT_SANDBOX
    return key


def cleaned_codex_env(secret_names: list[str] | None = None) -> dict[str, str]:
    """Env for Codex child: keep shell/auth; drop declared Job secret names.

    Default **full host env** minus secrets (``COREME_CODEX_FULL_HOST_ENV`` off
    to use the strict keep-list only).
    """
    secrets = {n.upper() for n in (secret_names or [])}
    full_host = True
    if os.environ.get(FULL_HOST_ENV_FLAG, "").strip():
        full_host = env_flag(FULL_HOST_ENV_FLAG)
    # Default on unless explicitly set to 0/false/no.
    if FULL_HOST_ENV_FLAG not in os.environ:
        full_host = True

    out: dict[str, str] = {}
    for key, value in os.environ.items():
        ku = key.upper()
        if ku in secrets:
            continue
        if ku.startswith("COREME_"):
            # Never pass Job runtime / auto-repair knobs into the child by default.
            continue
        if ku.endswith(("_TOKEN", "_SECRET", "_PASSWORD", "_PASS", "_KEY", "_API_KEY")):
            if ku == "OPENAI_API_KEY":
                out[key] = value
            continue
        if full_host:
            out[key] = value
            continue
        if ku in _KEEP_ENV_EXACT or ku.startswith("CODEX_"):
            out[key] = value

    if "PATH" not in out and "Path" not in out:
        path_val = os.environ.get("PATH") or os.environ.get("Path")  # noqa: SIM112 — Windows stores PATH as Path
        if path_val:
            out["PATH"] = path_val
    return out


def codex_argv(
    codex: str,
    source: Path,
    prompt: str,
    *,
    sandbox: str | None = None,
    profile: str | None = None,
    add_dirs: list[Path] | None = None,
    images: list[Path] | None = None,
    inherit_env: bool | None = None,
    ignore_user_config: bool | None = None,
    output_last_message: Path | None = None,
) -> list[str]:
    """Build ``codex exec`` argv for one repair spawn."""
    mode = resolve_sandbox(sandbox)
    argv: list[str] = [codex, "exec", "--skip-git-repo-check", "-C", str(source)]

    if mode == "bypass":
        argv.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        argv.extend(["-s", mode])

    prof = profile if profile is not None else os.environ.get(PROFILE_ENV, "").strip()
    if prof:
        argv.extend(["-p", prof])

    if ignore_user_config is None:
        ignore_user_config = env_flag(IGNORE_USER_CONFIG_ENV)
    if ignore_user_config:
        argv.append("--ignore-user-config")

    for d in add_dirs or []:
        argv.extend(["--add-dir", str(Path(d).resolve())])

    for img in images or []:
        p = Path(img)
        if p.is_file():
            argv.extend(["-i", str(p.resolve())])

    # Default: let Codex child shells inherit host env (venv, PATH extras).
    if inherit_env is None:
        inherit_env = env_flag(INHERIT_ENV_FLAG) if INHERIT_ENV_FLAG in os.environ else True
    if inherit_env:
        argv.extend(["-c", "shell_environment_policy.inherit=all"])

    if output_last_message is not None:
        argv.extend(["-o", str(Path(output_last_message).resolve())])

    argv.append(prompt)
    return argv


def codex_prompt(
    brief_path: Path,
    source: Path,
    run_path: Path,
    *,
    crash_signature: str = "",
    fail_png: Path | None = None,
) -> str:
    """Tight repair prompt: smoking gun first, bounded scope, offline acceptance."""
    parts: list[str] = [
        "You are repairing a coreme Job after a failed Run.",
        f"Brief (read this file): {brief_path.resolve()}",
        f"Source Job (edit only here): {source.resolve()}",
        f"Failed Run evidence: {run_path.resolve()}",
    ]
    if crash_signature.strip():
        parts.append("CRASH SIGNATURE (fix this first):\n" + crash_signature.strip())
    if fail_png is not None and Path(fail_png).is_file():
        parts.append(f"Fail screenshot attached/path: {Path(fail_png).resolve()}")
    parts.extend(
        [
            "Rules:",
            "- Edit source only; never edit releases/.",
            "- Do not add, enable, or reuse Job-owned runtime Codex / LLM for this repair.",
            "- Day 7 repair is a post-fail coordinator, not the Job's runtime-AI path.",
            "- One focused fix; no drive-by refactors.",
            "- Read only the brief, fail.json, log tail, and files named in the traceback.",
            "- Do not load extra monorepo skills/docs unless the crash is still unclear.",
            "- Prove offline first: `coreme test` on the source path.",
            "- Do not treat sandbox/Playwright host limits as the original root cause.",
            "- Do not ship / bump / freeze unless a human explicitly asked.",
            "- Never print or paste secret values.",
            "Done when: offline proof green + short report (files changed + one-line root cause).",
        ]
    )
    return "\n".join(parts)


def default_spawn(
    argv: list[str],
    *,
    cwd: str,
    env: dict[str, str],
    timeout_sec: int | None,
    log_path: Path | str | None = None,
    quiet: bool | None = None,
) -> int:
    """Spawn Codex.

    Default **quiet**: stream child stdout/stderr into *log_path* (Run folder
    ``codex.log``) and print only a short pointer on the operator TTY.
    Set ``COREME_CODEX_VERBOSE=1`` or *quiet=False* to inherit stdio (old behavior).
    """
    if quiet is None:
        quiet = not env_flag(VERBOSE_ENV)

    if not quiet or log_path is None:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout_sec,
            check=False,
        )
        return int(completed.returncode)

    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"repair: Codex session → {path}", flush=True)
    with path.open("w", encoding="utf-8", errors="replace") as log_fh:
        # Banner for audit.
        log_fh.write("# coreme codex repair log\n")
        log_fh.write(f"# cwd={cwd}\n")
        log_fh.write(f"# argv={argv!r}\n\n")
        log_fh.flush()
        completed = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            timeout=timeout_sec,
            check=False,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
        )
    # Surface a tiny tail so ops see something without full agent monologue.
    _print_log_tail(path, max_lines=12)
    return int(completed.returncode)


def run_prove(source: Path) -> dict[str, Any]:
    from coreme.proof import test_job

    code = test_job(source)
    return {
        "exit_code": code,
        "status": "passed" if code == 0 else "failed",
        "command": f"coreme test {source}",
    }


def _print_log_tail(path: Path, *, max_lines: int) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines:
        print("repair: (codex log empty)", flush=True)
        return
    tail = lines[-max_lines:]
    print("repair: --- codex tail ---", flush=True)
    for ln in tail:
        # Avoid flooding if a single line is huge (JSON dumps).
        if len(ln) > 240:
            ln = ln[:237] + "..."
        print(ln, flush=True)
    print("repair: --- end tail ---", flush=True)
    print(f"repair: full log: {path}", flush=True)


def is_windows() -> bool:
    return sys.platform == "win32"
