"""Two-phase Job: prepare then report, with only/skip selection and seed."""

from __future__ import annotations

import os
from pathlib import Path

PHASE_ORDER = ("prepare", "report")
PREPARED_BODY = "prepared: phased-demo\n"
PREPARED_NAME = "prepared.txt"
REPORT_NAME = "report.txt"


def selected_phases(only: str, skip: str) -> tuple[str, ...]:
    """Return phases to run in PHASE_ORDER order, or raise ValueError."""
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


def format_report(prepared_text: str) -> str:
    """Return the durable report body for prepared text."""
    return f"report:\n{prepared_text}"


def phase_prepare(artifacts: Path) -> None:
    (artifacts / PREPARED_NAME).write_text(PREPARED_BODY, encoding="utf-8")


def phase_report(artifacts: Path, seed: str | None) -> None:
    prepared = artifacts / PREPARED_NAME
    if not prepared.is_file():
        if not seed:
            raise ValueError("report requires seed when prepare is not selected")
        prepared.write_text(Path(seed).read_text(encoding="utf-8"), encoding="utf-8")
    body = prepared.read_text(encoding="utf-8")
    (artifacts / REPORT_NAME).write_text(format_report(body), encoding="utf-8")


PHASE_FN = {
    "prepare": phase_prepare,
    "report": phase_report,
}


def input_value(name: str) -> str:
    return os.environ.get(f"COREME_INPUT_{name}", "")


def main() -> None:
    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])
    try:
        selected = selected_phases(input_value("only"), input_value("skip"))
    except ValueError as error:
        raise SystemExit(str(error)) from error

    seed = os.environ.get("COREME_INPUT_seed")
    for name in selected:
        print(f"[phase] {name} start")
        try:
            if name == "prepare":
                PHASE_FN[name](artifacts)
            else:
                PHASE_FN[name](artifacts, seed)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        print(f"[phase] {name} done")


if __name__ == "__main__":
    main()
