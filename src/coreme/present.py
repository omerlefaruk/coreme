"""CLI presentation: Rich TTY paint with plain fallback.

Three surfaces stay separate:

- Kernel CLI: notes, run footer, errors (this module).
- Live Job echo: optional **role colors** when the operator TTY is real; the
  Run ``log.txt`` still stores plain bytes (runner captures raw lines).
- Job code never needs Rich for basic step/fail readability.
"""

from __future__ import annotations

import json
import os
import re
import sys
from contextlib import suppress
from typing import TYPE_CHECKING, TextIO

from coreme.util import env_flag

if TYPE_CHECKING:
    from rich.console import Console

    from coreme.runner import RunRecord

_PLAIN_ENV = "COREME_PLAIN"

# The agent gives the CLI one inherited anonymous-pipe endpoint.  The CLI
# removes the endpoint locator from its environment and duplicates it as a
# non-inheritable descriptor before starting Job code.  Thus this contract is
# out-of-band: footer text remains for people and has no machine authority.
RESULT_SCHEMA = "coreme.run-result"
RESULT_VERSION = 1
RESULT_ENV = "COREME_RESULT_CHANNEL"
RESULT_MAX_BYTES = 64 * 1024
_STEP_LINE = re.compile(r"^(\d+)/(\d+)\s+(.*)$")
_live_console: Console | None = None
_live_console_stream: TextIO | None = None


def is_plain(*, plain_flag: bool = False) -> bool:
    """True when color/panels must be off."""
    if plain_flag or env_flag(_PLAIN_ENV):
        return True
    return not _stdout_is_tty()


def _stdout_is_tty() -> bool:
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def print_note(message: str, *, plain_flag: bool = False) -> None:
    """Resolution / informational note before a command body."""
    if not message:
        return
    if is_plain(plain_flag=plain_flag):
        print(message)
        return
    try:
        from rich.console import Console

        console = Console(stderr=False, highlight=False)
        console.print(f"[dim]{message}[/dim]")
    except Exception:
        print(message)


def echo_job_line(stream: TextIO, line: str) -> None:
    """Write one Job stdout line to the operator terminal.

    Applies light role colors on a real TTY (steps cyan, FAIL red, details dim).
    Callers must append the **raw** line to ``log.txt`` themselves — this never
    mutates the evidence stream.
    """
    if not line:
        return
    if is_plain() or not _stream_is_tty(stream):
        stream.write(line)
        stream.flush()
        return
    try:
        console = _get_live_console(stream)
        raw = line.rstrip("\n")
        # Preserve blank lines
        if not raw:
            stream.write(line)
            stream.flush()
            return
        console.print(_style_job_line(raw), highlight=False, soft_wrap=True)
    except Exception:
        with suppress(Exception):
            stream.write(line)
            stream.flush()


def _get_live_console(stream: TextIO) -> Console:
    global _live_console, _live_console_stream
    if _live_console is not None and _live_console_stream is stream:
        return _live_console
    from rich.console import Console

    _live_console = Console(
        file=stream,
        force_terminal=True,
        highlight=False,
        soft_wrap=True,
        emoji=True,
    )
    _live_console_stream = stream
    return _live_console


def _style_job_line(raw: str) -> object:
    from rich.text import Text

    stripped = raw.lstrip()
    if (
        stripped.startswith("✗ FAIL")
        or stripped.startswith("❌ FAIL")
        or stripped.startswith("FAIL ")
        or stripped.startswith("error:")
    ):
        return Text(raw, style="bold red")
    if raw.startswith("──") and "FAIL" in raw:
        return Text(raw, style="bold red")
    if raw.startswith("──"):
        return Text(raw, style="bold")
    if "ÖZET" in raw:
        return Text(raw, style="bold")
    # Card fields from summary_lines / say_fail: "key: value"
    if ":" in raw and not raw.startswith("  ·") and not raw.startswith("http"):
        key, _, val = raw.partition(":")
        key_s = key.strip()
        if key_s in {"step", "what", "reason", "evidence", "status", "mode", "message"} or (
            key_s and " " not in key_s and len(key_s) < 24
        ):
            text = Text()
            key_style = "bold red" if key_s == "reason" else "bold"
            text.append(f"{key}:", style=key_style)
            text.append(val, style="red" if key_s == "reason" else "")
            return text
    if raw.startswith("  ·") or raw.startswith("  reason:") or raw.startswith("  evidence:"):
        style = "bold red" if "reason:" in raw else "dim"
        return Text(raw, style=style)
    match = _STEP_LINE.match(raw)
    if match:
        text = Text()
        text.append(f"{match.group(1)}/{match.group(2)}", style="bold cyan")
        rest = match.group(3)
        if rest:
            text.append(f" {rest}")
        return text
    return Text(raw)


def _stream_is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def print_run_footer(
    record: RunRecord,
    *,
    plain_flag: bool = False,
    repair: object | None = None,
) -> None:
    """After ``coreme run``: status + run path (pretty panel or key=value).

    Call this **before** auto-repair so the operator always sees the outcome
    immediately; use :func:`print_repair_footer` after Codex finishes.
    """
    fail_info = _fail_footer_info(record)
    repair_status, repair_file = _repair_footer_bits(repair)
    if is_plain(plain_flag=plain_flag):
        print(f"status={record.status} exit_code={record.exit_code}")
        print(f"run_path={record.run_path}")
        if fail_info.path is not None:
            print(f"fail_path={fail_info.path}")
        if fail_info.message:
            print(f"fail_message={fail_info.message}")
        if fail_info.step_line:
            print(f"failed_step={fail_info.step_line}")
        if fail_info.screenshot:
            print(f"fail_screenshot={fail_info.screenshot}")
        if repair_status is not None:
            print(f"repair_status={repair_status}")
        if repair_file is not None:
            print(f"repair_path={repair_file}")
        return
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        ok = record.status == "succeeded"
        icon = "✅" if ok else "❌"
        style = "bold green" if ok else "bold red"
        body = Text()
        body.append(f"{icon} {record.status}", style=style)
        body.append(f"  ·  exit {record.exit_code}\n", style="dim")
        label = f"{record.job}-{record.version}"
        if record.release and record.content_hash:
            label += f"  ·  {record.content_hash[:12]}"
        body.append(f"📦 {label}\n", style="cyan")
        body.append(f"📁 {record.run_path}", style="dim")
        if not ok:
            if fail_info.step_line:
                body.append(f"\n⛔ {fail_info.step_line}", style="bold red")
            if fail_info.message:
                short = (
                    fail_info.message
                    if len(fail_info.message) <= 160
                    else fail_info.message[:157] + "..."
                )
                body.append(f"\n{short}", style="red")
            if fail_info.screenshot_rel:
                body.append(f"\n🖼  {fail_info.screenshot_rel}", style="dim")
            if fail_info.path_rel:
                body.append(f"\n📎 {fail_info.path_rel}", style="dim")
        if repair_status is not None:
            body.append(f"\n🔧 repair={repair_status}", style="dim")
            if repair_file is not None:
                body.append(f"\n{repair_file}", style="dim")
        console = Console(stderr=False, highlight=False)
        # Blank line separates Job stream from the kernel panel.
        console.print()
        console.print(
            Panel(
                body,
                title="[bold]coreme[/bold]",
                border_style="green" if ok else "red",
                padding=(0, 1),
            )
        )
        console.file.flush()
    except Exception:
        print(f"status={record.status} exit_code={record.exit_code}")
        print(f"run_path={record.run_path}")
        if fail_info.path is not None:
            print(f"fail_path={fail_info.path}")
        if fail_info.message:
            print(f"fail_message={fail_info.message}")
        if fail_info.step_line:
            print(f"failed_step={fail_info.step_line}")
        if repair_status is not None:
            print(f"repair_status={repair_status}")
        if repair_file is not None:
            print(f"repair_path={repair_file}")


def build_result_payload(record: RunRecord) -> dict[str, object]:
    """Machine-result contract body for one finished Run (additive, versioned).

    Consumers (coreme-agent) treat this file as authoritative for status /
    exit_code / run_path and failure fields; the --plain footer text stays
    unchanged for human operators and older consumers.
    """
    fail_info = _fail_footer_info(record)
    payload: dict[str, object] = {
        "schema": RESULT_SCHEMA,
        "version": RESULT_VERSION,
        "status": record.status,
        "exit_code": record.exit_code,
        "run_path": record.run_path,
        "job": record.job,
        "job_version": record.version,
    }
    for key in ("started_at", "finished_at"):
        value = getattr(record, key, None)
        if value:
            payload[key] = value
    if fail_info.path is not None:
        payload["fail_path"] = fail_info.path
    if fail_info.message:
        payload["fail_message"] = fail_info.message
    if fail_info.step_line:
        payload["failed_step"] = fail_info.step_line
    return payload


def write_result_channel(record: RunRecord, fd: int) -> None:
    """Write exactly one bounded, length-prefixed result to an owned pipe fd."""
    body = json.dumps(
        build_result_payload(record),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(body) > RESULT_MAX_BYTES:
        raise ValueError("machine result exceeds channel limit")
    data = len(body).to_bytes(4, "big") + body
    while data:
        written = os.write(fd, data)
        if written <= 0:
            raise OSError("machine result channel closed")
        data = data[written:]


def print_repair_footer(repair: object, *, plain_flag: bool = False) -> None:
    """After auto-repair / repair --exec: compact repair outcome panel."""
    repair_status, repair_file = _repair_footer_bits(repair)
    if repair_status is None:
        return
    message = str(getattr(repair, "message", "") or "")
    if is_plain(plain_flag=plain_flag):
        print(f"repair_status={repair_status}")
        if repair_file is not None:
            print(f"repair_path={repair_file}")
        if message:
            print(f"repair_message={message}")
        return
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        okish = repair_status in {"finished", "proved", "ok", "succeeded"}
        body = Text()
        body.append("🔧 repair=", style="dim")
        body.append(
            repair_status,
            style="bold green" if okish else "bold yellow",
        )
        if message:
            short = message if len(message) <= 120 else message[:117] + "..."
            body.append(f"\n{short}", style="dim")
        if repair_file is not None:
            body.append(f"\n{repair_file}", style="dim")
        console = Console(stderr=False, highlight=False)
        console.print()
        console.print(
            Panel(
                body,
                title="[bold]coreme repair[/bold]",
                border_style="green" if okish else "yellow",
                padding=(0, 1),
            )
        )
        console.file.flush()
    except Exception:
        print(f"repair_status={repair_status}")
        if repair_file is not None:
            print(f"repair_path={repair_file}")


class _FailFooterInfo:
    __slots__ = ("message", "path", "path_rel", "screenshot", "screenshot_rel", "step_line")

    def __init__(
        self,
        message: str | None = None,
        path: str | None = None,
        path_rel: str | None = None,
        step_line: str | None = None,
        screenshot: str | None = None,
        screenshot_rel: str | None = None,
    ) -> None:
        self.message = message
        self.path = path
        self.path_rel = path_rel
        self.step_line = step_line
        self.screenshot = screenshot
        self.screenshot_rel = screenshot_rel


def _repair_footer_bits(repair: object | None) -> tuple[str | None, str | None]:
    if repair is None:
        return None, None
    status = getattr(repair, "status", None)
    path = getattr(repair, "path", None)
    return (
        str(status) if status is not None else None,
        str(path) if path is not None else None,
    )


def _fail_footer_info(record: RunRecord) -> _FailFooterInfo:
    """Load fail.json (+ optional fail.png) for footer / plain keys."""
    if record.status == "succeeded" or record.exit_code == 0:
        return _FailFooterInfo()
    try:
        from pathlib import Path

        from coreme.events import fail_path, read_fail_summary

        path = fail_path(record.run_path)
        if not path.is_file():
            return _FailFooterInfo()
        summary = read_fail_summary(record.run_path) or {}
        message = summary.get("message")
        msg = str(message) if message else None
        step_line = _format_failed_step_line(summary.get("failed_step"))
        if step_line is None and summary.get("last_step"):
            step_line = _format_last_step_line(summary.get("last_step"))
        shot = Path(record.run_path) / "artifacts" / "fail.png"
        screenshot = str(shot.resolve()) if shot.is_file() else None
        return _FailFooterInfo(
            message=msg,
            path=str(path.resolve()),
            path_rel="fail.json",
            step_line=step_line,
            screenshot=screenshot,
            screenshot_rel="artifacts/fail.png" if shot.is_file() else None,
        )
    except Exception:
        return _FailFooterInfo()


def _format_failed_step_line(failed: object) -> str | None:
    if not isinstance(failed, dict) or not failed:
        return None
    step = failed.get("step", "?")
    name = failed.get("name") or ""
    total = failed.get("total")
    bit = f"step {step}/{total}" if total is not None else f"step {step}"
    if name:
        bit += f" · {name}"
    bit += " failed"
    return bit


def _format_last_step_line(last: object) -> str | None:
    if not isinstance(last, dict) or not last:
        return None
    event = last.get("event", "step")
    step = last.get("step")
    name = last.get("name") or ""
    parts = [str(event)]
    if step is not None:
        total = last.get("total")
        parts.append(f"{step}/{total}" if total is not None else str(step))
    if name:
        parts.append(str(name))
    return "last " + " ".join(parts)


def print_ship_footer(
    release_path: str,
    content_hash: str,
    *,
    plain_flag: bool = False,
) -> None:
    if is_plain(plain_flag=plain_flag):
        print(f"release_path={release_path}")
        print(f"content_hash={content_hash}")
        return
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.text import Text

        body = Text()
        body.append("✅ shipped\n", style="bold green")
        body.append(f"📦 {release_path}\n", style="cyan")
        body.append(f"🔏 {content_hash}", style="dim")
        console = Console(stderr=False, highlight=False)
        console.print(
            Panel(body, title="[bold]coreme[/bold]", border_style="green", padding=(0, 1))
        )
    except Exception:
        print(f"release_path={release_path}")
        print(f"content_hash={content_hash}")


def print_error(message: str, *, plain_flag: bool = False) -> None:
    """Kernel pre-run / CLI errors on stderr."""
    text = f"error: {message}"
    if is_plain(plain_flag=plain_flag) or not _stderr_is_tty():
        print(text, file=sys.stderr)
        return
    try:
        from rich.console import Console

        console = Console(stderr=True, highlight=False)
        console.print(f"[bold red]error:[/bold red] {message}")
    except Exception:
        print(text, file=sys.stderr)


def _stderr_is_tty() -> bool:
    try:
        return bool(sys.stderr.isatty())
    except Exception:
        return False


def format_events_text(rows: list[dict]) -> str:
    """Human-readable table of event lines (no color)."""
    if not rows:
        return "(no events)\n"
    lines = ["ts                  level  event"]
    lines.append("-" * 48)
    for row in rows:
        ts = str(row.get("ts", ""))[:19]
        level = str(row.get("level", ""))[:5].ljust(5)
        event = str(row.get("event", ""))
        extra_parts: list[str] = []
        if "step" in row:
            total = row.get("total")
            if total is not None:
                extra_parts.append(f"{row['step']}/{total}")
            else:
                extra_parts.append(str(row["step"]))
        if row.get("name"):
            extra_parts.append(str(row["name"]))
        if row.get("status"):
            extra_parts.append(str(row["status"]))
        if row.get("exit_code") is not None and row.get("event") != "run.start":
            extra_parts.append(f"exit={row['exit_code']}")
        if row.get("message"):
            extra_parts.append(str(row["message"]))
        extra = ("  " + " ".join(extra_parts)) if extra_parts else ""
        lines.append(f"{ts}  {level}  {event}{extra}")
    return "\n".join(lines) + "\n"


def format_fail_summary_text(summary: dict) -> str:
    """Short human block for a ``fail.json`` brief (no color)."""
    kind = summary.get("kind", "?")
    exit_code = summary.get("exit_code", "?")
    message = summary.get("message", "")
    job = summary.get("job", "?")
    version = summary.get("version", "?")
    lines = [
        f"FAIL  kind={kind}  exit={exit_code}  job={job}-{version}",
        f"  {message}" if message else "  (no message)",
    ]
    failed = summary.get("failed_step")
    if isinstance(failed, dict) and failed:
        step = failed.get("step", "?")
        total = failed.get("total")
        name = failed.get("name", "")
        detail = failed.get("message")
        bit = f"  failed_step: {step}/{total}" if total is not None else f"  failed_step: {step}"
        if name:
            bit += f" {name}"
        if detail:
            bit += f" — {detail}"
        lines.append(bit)
    last = summary.get("last_step")
    if isinstance(last, dict) and last:
        event = last.get("event", "?")
        step = last.get("step")
        name = last.get("name", "")
        bit = f"  last_step: {event}"
        if step is not None:
            bit += f" {step}"
        if name:
            bit += f" {name}"
        lines.append(bit)
    evidence = summary.get("evidence")
    if isinstance(evidence, dict) and evidence:
        parts = [f"{k}={v}" for k, v in evidence.items()]
        lines.append("  evidence: " + " ".join(parts))
    return "\n".join(lines) + "\n"
