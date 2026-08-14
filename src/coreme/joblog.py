"""Job-side progress and run-event helpers (stdlib-first).

Import-safe without Rich. Enforces a **single live surface** for operator lines:

- Plain path: print to stdout (coreme streams this to the terminal + log.txt).
- Fancy path: optional ``paint(console)`` on the real console only — do **not**
  also print the same line (under ``coreme run``, stdout is a pipe that the
  runner echoes; dual-write doubles every line).

Jobs may copy these functions instead of depending on coreme.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from coreme.events import append_event
from coreme.util import env_flag

# Plain transcript for evidence when live UI used Rich-only paint.
_operator_lines: list[str] = []

# Cached real-console Rich Console (CONOUT$ /dev/tty), if available.
_tty_console: Any = None
_tty_file: Any = None
_tty_probed = False


def configure_stdio() -> None:
    """Windows consoles often default to cp1252; non-ASCII must not crash prints."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        with suppress(Exception):
            reconfigure(encoding="utf-8", errors="replace")


def get_tty_console() -> Any:
    """Soft-import Rich on the real console, not the piped Job stdout.

    Under ``coreme run``, Job stdout is a pipe (``isatty()`` is false). Painting
    Rich to stdout either fails or puts ANSI into log.txt. Use CONOUT$ /dev/tty
    only via ``operator_show(..., paint=...)`` — never also print the same line.
    """
    global _tty_console, _tty_file, _tty_probed
    if _tty_probed:
        return _tty_console
    _tty_probed = True
    if env_flag("COREME_PLAIN"):
        return None
    try:
        from rich.console import Console
    except Exception:
        return None
    try:
        if sys.platform == "win32":
            # Device handle, not a filesystem path — Path.open is the wrong tool.
            _tty_file = open(  # noqa: PTH123, SIM115
                "CONOUT$", "w", encoding="utf-8", errors="replace"
            )
        else:
            # Device handle, not a filesystem path — Path.open is the wrong tool.
            _tty_file = open(  # noqa: PTH123, SIM115
                "/dev/tty", "w", encoding="utf-8", errors="replace"
            )
        _tty_console = Console(
            file=_tty_file,
            force_terminal=True,
            emoji=True,
            highlight=False,
            soft_wrap=True,
        )
    except Exception:
        _tty_console = None
        _tty_file = None
    return _tty_console


def reset_operator_transcript() -> None:
    """Clear recorded plain lines (tests / multi-run in one process)."""
    _operator_lines.clear()


def operator_show(
    plain: str,
    *,
    paint: Callable[[Any], None] | None = None,
) -> None:
    """Show one operator message on **exactly one** live surface.

    Always records *plain* for ``flush_operator_transcript``.

    - If *paint* is set and a real-console Rich Console is available: call
      ``paint(console)`` only (no stdout print for this line).
    - Else: print *plain* to stdout (live stream + log.txt under coreme).

    Never pass a paint function that also prints to stdout.
    """
    _operator_lines.append(plain)
    if paint is not None:
        console = get_tty_console()
        if console is not None:
            try:
                paint(console)
                return
            except Exception:
                pass
    print(plain, flush=True)


def say(message: str) -> None:
    """Operator-facing progress; single surface (plain stdout unless paint used)."""
    operator_show(message)


def say_step(n: int, total: int, message: str, *, name: str | None = None) -> None:
    """Print ``n/total …`` and emit ``step.start`` when a Run dir is set."""
    operator_show(f"{n}/{total} {message}")
    emit(
        "step.start",
        step=n,
        total=total,
        name=name or _step_name(message),
        message=message,
    )


def say_detail(message: str) -> None:
    """Indented detail line under the current step."""
    operator_show(f"  · {message}")


def short_error(exc: BaseException, *, limit: int = 220) -> str:
    """One-line operator reason from an exception (no traceback wall)."""
    name = type(exc).__name__
    text = str(exc).strip()
    first = text.splitlines()[0].strip() if text else ""
    if not first:
        return name
    # Playwright / locator timeouts: keep selector, drop call-log noise.
    lower = first.lower()
    if "timeout" in name.lower() or "timeout" in lower:
        for line in text.splitlines():
            stripped = line.strip()
            if "waiting for" in stripped.lower() or "locator(" in stripped.lower():
                first = stripped.lstrip("- ").strip()
                break
        body = first if first.lower().startswith("timeout") else f"Timeout — {first}"
    elif first.startswith(name):
        body = first
    else:
        body = f"{name}: {first}"
    if len(body) > limit:
        return body[: limit - 3] + "..."
    return body


def say_fail(
    n: int,
    total: int,
    message: str,
    *,
    name: str | None = None,
    reason: str | None = None,
    evidence: str | None = None,
) -> str:
    """Print a clear FAIL block (always plain stdout → log.txt) and emit step.fail.

    Returns the short reason string (for SystemExit / fail.json consumers).
    Prefer this over re-raising with a full traceback as the only operator signal.
    """
    step_name = name or _step_name(message)
    reason_text = (reason or message).strip() or "failed"
    if len(reason_text) > 300:
        reason_text = reason_text[:297] + "..."
    # Same shape as ÖZET so failures read as a labeled card, not a loose log dump.
    fields: list[tuple[str, Any]] = [
        ("step", f"{n}/{total} {step_name}".rstrip()),
        ("what", message.rstrip("…").rstrip(".").strip() or step_name),
        ("reason", reason_text),
    ]
    if evidence:
        fields.append(("evidence", evidence))
    lines = summary_lines(fields, title="FAIL")
    # Lead with a scannable marker; colorizer keys off "✗ FAIL" / "FAIL".
    block = f"✗ FAIL {n}/{total} {message}".rstrip() + "\n" + "\n".join(lines)
    operator_show(block)
    emit(
        "step.fail",
        step=n,
        total=total,
        name=step_name,
        message=reason_text,
        level="error",
    )
    return reason_text


def emit(event: str, *, level: str = "info", **fields: Any) -> None:
    """Append one JSONL event under ``COREME_RUN_DIR``; no-op if unset."""
    run_dir = os.environ.get("COREME_RUN_DIR")
    if not run_dir:
        return
    append_event(run_dir, event, level=level, **fields)


def summary_lines(
    fields: Sequence[tuple[str, Any]],
    *,
    title: str = "ÖZET",
) -> list[str]:
    """Build plain ÖZET / SUMMARY lines for print + ``result.txt``."""
    width = max(len(title) + 6, 12)
    bar = "─" * width
    lines = [f"── {title} ──"]
    for key, value in fields:
        lines.append(f"{key}: {value}")
    lines.append(bar)
    return lines


def say_summary(
    fields: Sequence[tuple[str, Any]],
    *,
    title: str = "ÖZET",
    paint: Callable[[Any], None] | None = None,
) -> str:
    """Show summary once (plain or paint); return body for artifacts."""
    lines = summary_lines(fields, title=title)
    body = "\n".join(lines) + "\n"
    operator_show(body.rstrip("\n"), paint=paint)
    return body


def write_result_txt(body: str, *, filename: str = "result.txt") -> Path | None:
    """Write durable summary under ``COREME_ARTIFACTS_DIR`` when set."""
    artifacts = os.environ.get("COREME_ARTIFACTS_DIR")
    if not artifacts:
        return None
    path = Path(artifacts) / filename
    path.write_text(body, encoding="utf-8")
    return path


def flush_operator_transcript(
    *,
    artifacts_dir: str | Path | None = None,
    filename: str = "operator.txt",
) -> str:
    """Write recorded plain lines to operator.txt (Run dir + optional artifacts).

    Call at end of main when using Rich paint so greppable evidence exists even
    though those lines never went to stdout / log.txt.
    """
    if not _operator_lines:
        return ""
    body = "\n".join(_operator_lines) + "\n"
    targets: list[Path] = []
    run_dir = os.environ.get("COREME_RUN_DIR")
    if run_dir:
        targets.append(Path(run_dir) / filename)
    art = artifacts_dir or os.environ.get("COREME_ARTIFACTS_DIR")
    if art:
        targets.append(Path(art) / filename)
    for path in targets:
        with suppress(OSError):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
    return body


def _step_name(message: str) -> str:
    text = message.strip().lower()
    for sep in ("…", "...", "—", "-"):
        if sep in text:
            text = text.split(sep, 1)[0]
    text = text.strip().replace(" ", "_")
    return text[:40] if text else "step"
