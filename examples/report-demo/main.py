"""Operator report + run events demo (stdlib joblog helpers).

Shows numbered steps, ÖZET summary, plain result.txt, and step.* / idle
events under COREME_RUN_DIR. No secrets, no browser — offline-safe.
"""

from __future__ import annotations

import os
import sys

from coreme.joblog import (
    configure_stdio,
    emit,
    say,
    say_detail,
    say_step,
    say_summary,
    write_result_txt,
)


def normalize_mode(value: str | None) -> str:
    raw = (value or "work").strip().lower()
    if raw in {"idle", "empty", "none", "clean"}:
        return "idle"
    return "work"


def main() -> None:
    configure_stdio()
    mode = normalize_mode(os.environ.get("COREME_INPUT_mode"))
    total = 3

    say("report-demo — operator report sample")
    say_step(1, total, "Preparing…", name="prepare")
    say_detail("inputs loaded")
    emit("step.ok", step=1, name="prepare")

    say_step(2, total, "Checking queue…", name="queue")
    if mode == "idle":
        say_detail("queue empty — idle success")
        emit("step.skip", step=2, name="queue", message="idle")
        emit(
            "idle",
            message="nothing to do — clean",
            detail={"documents": 4, "pending": 0},
        )
        body = say_summary(
            [
                ("status", "clean"),
                ("documents", 4),
                ("pending", 0),
            ],
            title="ÖZET",
        )
        write_result_txt(body)
        say_step(3, total, "Done — nothing to do / clean", name="finish")
        emit("step.ok", step=3, name="finish")
        return

    items = 2
    say_detail(f"found {items} item(s)")
    emit("step.ok", step=2, name="queue")
    emit("domain", detail={"documents": 4, "pending": items})

    say_step(3, total, f"Finishing {items} item(s)…", name="finish")
    emit("step.ok", step=3, name="finish")
    body = say_summary(
        [
            ("status", "ok"),
            ("documents", 4),
            ("pending", items),
        ],
        title="ÖZET",
    )
    write_result_txt(body)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # pragma: no cover - defensive
        print(f"error: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from error
