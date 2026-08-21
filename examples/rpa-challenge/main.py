"""RPA Challenge — fill https://www.rpachallenge.com/ from CSV rows.

- **offline** (default): load CSV, write fill plan + result; no browser/network.
- **live**: Playwright Chromium opens the site, clicks Start, fills each row
  via stable ``ng-reflect-name`` selectors, captures congratulations text.

Job never calls an LLM. Browser dep is Job-owned (see requirements.txt).
Use this Job to exercise live browser runs and Day 7 Codex repair on fail.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from challenge import (
    CHALLENGE_URL,
    FIELD_SELECTORS,
    fill_plan,
    format_result,
    load_rows,
    normalize_mode,
    parse_max_rows,
    truthy,
)

try:
    from coreme.joblog import (
        configure_stdio,
        emit,
        say,
        say_detail,
        say_fail,
        say_step,
        short_error,
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
        print(f"  · {msg}", flush=True)

    def say_step(n: int, total: int, msg: str, name: str = "") -> None:
        print(f"{n}/{total} {msg}", flush=True)

    def short_error(exc: BaseException, *, limit: int = 220) -> str:
        text = str(exc).strip().splitlines()
        first = text[0] if text else type(exc).__name__
        return first[:limit]

    def say_fail(
        n: int,
        total: int,
        message: str,
        *,
        name: str | None = None,
        reason: str | None = None,
        evidence: str | None = None,
    ) -> str:
        reason_text = (reason or message).strip()
        print(f"✗ FAIL {n}/{total} {message}", flush=True)
        print(f"  reason: {reason_text}", flush=True)
        if evidence:
            print(f"  evidence: {evidence}", flush=True)
        return reason_text

    def write_result_txt(body: str) -> None:
        art = os.environ.get("COREME_ARTIFACTS_DIR")
        if art:
            Path(art).joinpath("result.txt").write_text(body, encoding="utf-8")

    def emit(*_a: Any, **_k: Any) -> None:
        return None


JOB_DIR = Path(__file__).resolve().parent
DEFAULT_FIXTURE = JOB_DIR / "fixtures" / "challenge.csv"
TOTAL_STEPS = 4


def resolve_data_path() -> Path:
    env = os.environ.get("COREME_INPUT_data_file", "").strip()
    if env:
        return Path(env)
    return DEFAULT_FIXTURE


def run_offline(rows: list[dict[str, str]], max_rows: int, artifacts: Path) -> str:
    plan = fill_plan(rows, max_rows)
    (artifacts / "fill_plan.json").write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    say_detail(f"wrote fill_plan.json ({len(plan)} row(s))")
    return format_result(mode="offline", rows_filled=len(plan), message="dry-run plan only")


def run_live(
    rows: list[dict[str, str]],
    max_rows: int,
    *,
    headless: bool,
    artifacts: Path,
) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "playwright not installed — pip install -r examples/rpa-challenge/requirements.txt "
            "&& playwright install chromium"
        ) from exc

    batch = rows[:max_rows]
    say_detail(f"launch chromium headless={int(headless)}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        try:
            page.goto(CHALLENGE_URL, wait_until="domcontentloaded", timeout=60_000)
            # INTENTIONAL BREAK for fail-UX / Codex repair drill (wrong button text).
            # Correct: page.get_by_role("button", name="Start", exact=True)
            page.locator("button:has-text('StartChallenge')").click(timeout=15_000)
            say_detail("Start clicked")

            t0 = time.perf_counter()
            for i, row in enumerate(batch, start=1):
                for col, selector in FIELD_SELECTORS.items():
                    page.locator(selector).fill(row[col], timeout=10_000)
                page.locator('input[type="submit"]').click(timeout=10_000)
                say_detail(f"submitted row {i}/{len(batch)}")
            elapsed_ms = int((time.perf_counter() - t0) * 1000)

            # Site shows e.g. "Congratulations! ... in XXX milliseconds"
            body_text = page.locator("body").inner_text(timeout=10_000)
            congrats = ""
            for line in body_text.splitlines():
                if "congratulat" in line.lower() or "millisecond" in line.lower():
                    congrats = line.strip()
                    break
            if not congrats:
                # Fallback: first non-empty line with a number + ms
                m = re.search(
                    r".{0,80}\d+\s*milliseconds?.{0,40}",
                    body_text,
                    flags=re.I | re.S,
                )
                congrats = m.group(0).strip() if m else "form submissions complete"

            page.screenshot(path=str(artifacts / "result.png"), full_page=True)
            say_detail("screenshot → result.png")
            return format_result(
                mode="live",
                rows_filled=len(batch),
                message=congrats[:200],
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            shot = ""
            try:
                page.screenshot(path=str(artifacts / "fail.png"), full_page=True)
                shot = "artifacts/fail.png"
                say_detail("screenshot → fail.png")
            except Exception:
                pass
            # Clean operator reason — no Playwright traceback wall on stdout.
            raise LiveFillError(short_error(exc), evidence=shot) from None
        finally:
            context.close()
            browser.close()


class LiveFillError(Exception):
    """Live browser step failed with an operator-facing reason."""

    def __init__(self, reason: str, *, evidence: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.evidence = evidence


def main() -> None:
    configure_stdio()
    mode = normalize_mode(os.environ.get("COREME_INPUT_mode"))
    headless = truthy(os.environ.get("COREME_INPUT_headless", "1"))
    max_rows = parse_max_rows(os.environ.get("COREME_INPUT_max_rows"))
    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])
    data_path = resolve_data_path()

    say("rpa-challenge — form fill for rpachallenge.com")
    say_step(1, TOTAL_STEPS, "Loading data…", name="load")
    if not data_path.is_file():
        raise SystemExit(f"data file not found: {data_path}")
    rows = load_rows(data_path)
    say_detail(f"{data_path.name}: {len(rows)} row(s); max_rows={max_rows}")
    emit("step.ok", step=1, name="load", detail={"rows": len(rows)})

    say_step(2, TOTAL_STEPS, f"Mode={mode}…", name="mode")
    emit("step.ok", step=2, name="mode", detail={"mode": mode})

    say_step(3, TOTAL_STEPS, "Filling forms…", name="fill")
    try:
        if mode == "offline":
            body = run_offline(rows, max_rows, artifacts)
            emit(
                "step.ok",
                step=3,
                name="fill",
                detail={"rows_filled": min(len(rows), max_rows)},
            )
        else:
            body = run_live(rows, max_rows, headless=headless, artifacts=artifacts)
            emit("step.ok", step=3, name="fill")
    except LiveFillError as exc:
        say_fail(
            3,
            TOTAL_STEPS,
            "Filling forms…",
            name="fill",
            reason=exc.reason,
            evidence=exc.evidence or None,
        )
        raise SystemExit(1) from None
    except Exception as exc:
        reason = short_error(exc)
        say_fail(
            3,
            TOTAL_STEPS,
            "Filling forms…",
            name="fill",
            reason=reason,
        )
        raise SystemExit(1) from None

    write_result_txt(body)
    print(body, end="", flush=True)

    say_step(4, TOTAL_STEPS, "Done", name="finish")
    emit("step.ok", step=4, name="finish")


if __name__ == "__main__":
    main()
