"""Daily Summary — Opera Cloud XML download + offline metrics.

Phases: prepare → download (live) → parse → report

- **offline** (default): skip download; parse fixtures under input_dir.
- **live**: login once, multi-worker download of catalog reports, then parse.

No mail. No dashboard. Secrets: OPERA_USER / OPERA_PASSWORD (process env only).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

from parsers import (
    GROSS_RULES,
    MANAGER_RULES,
    REPORT_FILES,
    discover_controls,
    extract_by_rules,
    extract_forecast_metrics,
    failed_controls,
    parse_forecast_rows,
    parse_master_rows,
    write_csv,
    write_metrics_lines,
)
from reports_catalog import resolve_reports

try:
    from coreme.joblog import (
        configure_stdio,
        emit,
        say,
        say_detail,
        say_step,
        say_summary,
        write_result_txt,
    )
except ImportError:  # bare pytest without install

    def configure_stdio() -> None:
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is None:
                continue
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    def say(msg: str) -> None:
        print(msg, flush=True)

    def say_detail(msg: str) -> None:
        print(f"  {msg}", flush=True)

    def say_step(n: int, total: int, msg: str, name: str = "") -> None:
        print(f"{n}/{total} {msg}", flush=True)

    def say_summary(pairs: list[tuple[str, Any]], title: str = "ÖZET") -> str:
        lines = [title] + [f"  {k}: {v}" for k, v in pairs]
        body = "\n".join(lines) + "\n"
        print(body, end="", flush=True)
        return body

    def write_result_txt(body: str) -> None:
        art = os.environ.get("COREME_ARTIFACTS_DIR")
        if art:
            Path(art).joinpath("result.txt").write_text(body, encoding="utf-8")

    def emit(*_a: Any, **_k: Any) -> None:
        return None


PHASE_ORDER = ("prepare", "download", "parse", "report")


def selected_phases(only: str, skip: str) -> tuple[str, ...]:
    only_names = tuple(name.strip() for name in only.split(",") if name.strip())
    skip_names = tuple(name.strip() for name in skip.split(",") if name.strip())
    if only_names and skip_names:
        raise ValueError("only and skip cannot both be set")
    names = only_names or skip_names
    if len(set(names)) != len(names):
        raise ValueError("phase name appears more than once")
    unknown = set(names) - set(PHASE_ORDER)
    if unknown:
        raise ValueError(f"unknown phase: {sorted(unknown)[0]}")
    selected = only_names or tuple(
        name for name in PHASE_ORDER if name not in skip_names
    )
    if not selected:
        raise ValueError("phase selection is empty")
    return tuple(name for name in PHASE_ORDER if name in selected)


def input_value(name: str) -> str:
    return os.environ.get(f"COREME_INPUT_{name}", "") or ""


def resolve_today(raw: str) -> str:
    text = (raw or "").strip()
    if text:
        return text
    return date.today().isoformat()


def resolve_mode(raw: str) -> str:
    m = (raw or "offline").strip().lower()
    if m in {"live", "prod", "online"}:
        return "live"
    return "offline"


def truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def phase_prepare(
    artifacts: Path,
    input_dir: Path,
    today: str,
    mode: str,
    reports_raw: str,
) -> dict[str, Any]:
    input_dir.mkdir(parents=True, exist_ok=True)
    controls = discover_controls(input_dir)
    missing = failed_controls(controls)
    try:
        specs = resolve_reports(reports_raw)
    except ValueError as error:
        raise ValueError(str(error)) from error
    state = {
        "today": today,
        "mode": mode,
        "input_dir": str(input_dir),
        "reports": [s.key for s in specs],
        "controls": controls,
        "missing_reports": missing,
        "download_results": {},
        "metrics": {},
        "parsed": [],
    }
    (artifacts / "prepare.json").write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    say_detail(f"today={today} mode={mode}")
    say_detail(f"reports={','.join(state['reports'])}")
    say_detail(f"input_dir={input_dir}")
    say_detail(f"xml on disk={sum(controls.values())}/{len(controls)}")
    return state


def _load_or_seed_state(artifacts: Path, seed: str | None) -> dict[str, Any]:
    prepared = artifacts / "prepare.json"
    if prepared.is_file():
        return json.loads(prepared.read_text(encoding="utf-8"))
    if not seed:
        raise ValueError("later phases need prepare.json or seed when prepare skipped")
    text = Path(seed).read_text(encoding="utf-8")
    prepared.write_text(text, encoding="utf-8")
    return json.loads(text)


def phase_download(artifacts: Path, state: dict[str, Any]) -> dict[str, Any]:
    mode = state.get("mode", "offline")
    if mode != "live":
        say_detail("mode=offline — skip browser download")
        state["download_results"] = {"_skipped": "offline"}
        (artifacts / "download.json").write_text(
            json.dumps(state["download_results"], indent=2) + "\n",
            encoding="utf-8",
        )
        return state

    user = os.environ.get("OPERA_USER") or ""
    password = os.environ.get("OPERA_PASSWORD") or ""
    if not user or not password:
        raise ValueError("live download requires OPERA_USER and OPERA_PASSWORD in env")

    from opera import download_reports, parse_workers, truthy as op_truthy

    specs = resolve_reports(input_value("reports") or ",".join(state.get("reports") or []))
    dest = Path(state["input_dir"])
    today_s = state.get("today") or date.today().isoformat()
    today_d = date.fromisoformat(today_s)
    headless = op_truthy(input_value("headless") or "1")
    workers = parse_workers(input_value("workers") or "3")

    say_detail(f"headless={int(headless)} workers={workers} dest={dest}")
    try:
        results = download_reports(
            specs,
            dest,
            user=user,
            password=password,
            today=today_d,
            headless=headless,
            workers=workers,
            say=say_detail,
        )
    except Exception as exc:
        # Best-effort screenshot path is handled inside workers; re-raise cleanly
        raise ValueError(f"download failed: {type(exc).__name__}: {exc}") from exc
    state["download_results"] = results
    state["controls"] = discover_controls(dest)
    state["missing_reports"] = failed_controls(state["controls"])
    (artifacts / "download.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    def _is_ok(status: str) -> bool:
        return status == "ok" or status.startswith("ok:")

    failed = {k: v for k, v in results.items() if not _is_ok(v)}
    if failed and not any(_is_ok(v) for v in results.values()):
        raise ValueError(f"all downloads failed: {failed}")
    if failed:
        say_detail(f"partial download failures: {list(failed)}")
    ok_n = sum(1 for v in results.values() if _is_ok(v))
    say_detail(f"download score {ok_n}/{len(results)}")
    return state


def phase_parse(artifacts: Path, state: dict[str, Any]) -> dict[str, Any]:
    input_dir = Path(state["input_dir"])
    metrics: dict[str, str] = {}
    parsed: list[str] = []

    manager = input_dir / "manager.xml"
    if manager.is_file():
        master_rows = parse_master_rows(manager)
        write_csv(
            artifacts / "manager_master.csv",
            master_rows,
            [
                "Description",
                "DAY",
                "MONTH",
                "YEAR",
                "DAY_PY",
                "MONTH_PY",
                "YEAR_PY",
            ],
        )
        metrics.update(extract_by_rules(master_rows, MANAGER_RULES))
        forecast_rows = parse_forecast_rows(manager)
        if forecast_rows:
            write_csv(
                artifacts / "manager_forecast.csv",
                forecast_rows,
                [
                    "Date",
                    "Day",
                    "Arr. Rooms",
                    "Dep. Rooms",
                    "Total Occ.",
                    "Occ. %",
                    "Adl. & Chl.",
                    "Average Room Rate",
                    "Room Revenue",
                    "Total Revenue",
                ],
            )
            metrics.update(extract_forecast_metrics(forecast_rows))
        parsed.append("manager")
        say_detail(f"manager.xml → master={len(master_rows)} forecast={len(forecast_rows)}")
    else:
        say_detail("manager.xml missing — skip manager parse")

    gross = input_dir / "manager_gross.xml"
    if gross.is_file():
        gross_rows = parse_master_rows(gross)
        write_csv(
            artifacts / "manager_gross.csv",
            gross_rows,
            ["Description", "DAY", "MONTH", "YEAR", "DAY_PY", "MONTH_PY", "YEAR_PY"],
        )
        metrics.update(
            extract_by_rules(gross_rows, GROSS_RULES, key_suffix=" GROSS")
        )
        parsed.append("manager_gross")
        say_detail(f"manager_gross.xml → rows={len(gross_rows)}")
    else:
        say_detail("manager_gross.xml missing — skip gross parse")

    # Presence-only notes for other XMLs (parsers later; same download path).
    for flag, filename in REPORT_FILES.items():
        if flag in {"manager_file", "manager_gross_file"}:
            continue
        path = input_dir / filename
        if path.is_file():
            parsed.append(filename.replace(".xml", ""))
            say_detail(f"present (parse not yet): {filename}")

    if not parsed:
        raise ValueError(
            "no parseable XML under input_dir "
            f"({input_dir}); need manager.xml and/or manager_gross.xml for metrics"
        )

    state["metrics"] = metrics
    state["parsed"] = parsed
    state["controls"] = discover_controls(input_dir)
    state["missing_reports"] = failed_controls(state["controls"])
    (artifacts / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_metrics_lines(artifacts / "metrics.txt", metrics)
    (artifacts / "parse.json").write_text(
        json.dumps(
            {"parsed": parsed, "metric_count": len(metrics)},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return state


def phase_report(artifacts: Path, state: dict[str, Any]) -> None:
    metrics = state.get("metrics") or {}
    if not metrics:
        metrics_path = artifacts / "metrics.json"
        if metrics_path.is_file():
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            state["metrics"] = metrics
        else:
            raise ValueError("report requires metrics from parse")

    missing = state.get("missing_reports") or []
    today = state.get("today", "")
    parsed = state.get("parsed") or []
    download_results = state.get("download_results") or {}
    status = "ok" if not missing else "partial"
    highlight = _highlight_metrics(metrics)
    pairs: list[tuple[str, Any]] = [
        ("status", status),
        ("today", today),
        ("mode", state.get("mode", "")),
        ("parsed", ",".join(parsed) if parsed else "-"),
        ("metrics", len(metrics)),
        ("missing_xml", len(missing)),
    ]
    if download_results and "_skipped" not in download_results:
        ok_n = sum(
            1
            for v in download_results.values()
            if v == "ok" or str(v).startswith("ok:")
        )
        pairs.append(("downloaded", f"{ok_n}/{len(download_results)}"))
        # Per-report timings (ok:12.3s) for speed board
        timed = [
            f"{k}={v.split(':',1)[1]}"
            for k, v in download_results.items()
            if str(v).startswith("ok:") and "s" in str(v)
        ]
        if timed:
            pairs.append(("times", "; ".join(timed[:6]) + ("…" if len(timed) > 6 else "")))
    pairs.extend(highlight)
    body = say_summary(pairs, title="ÖZET")
    write_result_txt(body)
    (artifacts / "summary.json").write_text(
        json.dumps(
            {
                "status": status,
                "today": today,
                "mode": state.get("mode"),
                "parsed": parsed,
                "metric_count": len(metrics),
                "missing_reports": missing,
                "download_results": download_results,
                "highlights": dict(highlight),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def _highlight_metrics(metrics: dict[str, str]) -> list[tuple[str, str]]:
    keys = [
        "Rooms Occupied B",
        "% Rooms Occupied B",
        "Room Revenue B",
        "Total Revenue B",
        "ADR GROSS B",
        "Arr. Rooms-2",
        "Total Occ.-2",
    ]
    out: list[tuple[str, str]] = []
    for k in keys:
        if k in metrics:
            out.append((k, metrics[k]))
    return out[:6]


def main() -> None:
    configure_stdio()
    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])
    mode = resolve_mode(input_value("mode"))
    today = resolve_today(input_value("today"))
    seed = os.environ.get("COREME_INPUT_seed")
    reports_raw = input_value("reports") or "manager"

    raw_dir = (input_value("input_dir") or "").strip()
    if raw_dir:
        input_dir = Path(raw_dir)
    else:
        # Live/offline default: write downloads next to run artifacts
        input_dir = artifacts / "input"

    only = input_value("only")
    skip = input_value("skip")
    # Offline auto-skips download unless user forced only=download
    if mode == "offline" and not only and not skip:
        skip = "download"

    try:
        selected = selected_phases(only, skip)
    except ValueError as error:
        raise SystemExit(str(error)) from error

    # Live download needs secrets; offline proof / parse does not declare empty env.
    # Kernel still requires secrets if listed — for offline, secret check is always
    # on. So offline runs must have secrets present OR we need secrets only for live.
    # Day 4: secrets checked if declared. For offline CI without Opera, use empty
    # names? Better: always declare secrets; e2e offline sets dummy env values.
    # (Documented in README.)

    total = len(selected)
    state: dict[str, Any] = {}
    say("daily-summary — Opera XML download + metrics")

    for i, name in enumerate(selected, start=1):
        print(f"[phase] {name} start", flush=True)
        say_step(i, total, f"{name}…", name=name)
        try:
            if name == "prepare":
                state = phase_prepare(
                    artifacts, input_dir, today, mode, reports_raw
                )
            elif name == "download":
                if not state:
                    state = _load_or_seed_state(artifacts, seed)
                state = phase_download(artifacts, state)
            elif name == "parse":
                if not state:
                    state = _load_or_seed_state(artifacts, seed)
                state = phase_parse(artifacts, state)
            else:
                if not state:
                    state = _load_or_seed_state(artifacts, seed)
                if not state.get("metrics"):
                    metrics_path = artifacts / "metrics.json"
                    if metrics_path.is_file():
                        state["metrics"] = json.loads(
                            metrics_path.read_text(encoding="utf-8")
                        )
                phase_report(artifacts, state)
        except ValueError as error:
            emit("step.fail", step=i, name=name, message=str(error))
            raise SystemExit(str(error)) from error
        emit("step.ok", step=i, name=name)
        print(f"[phase] {name} done", flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:  # pragma: no cover
        print(f"error: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from error
