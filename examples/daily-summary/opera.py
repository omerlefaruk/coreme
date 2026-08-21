"""Opera Cloud browser download — stay-on-list, fail-fast, multi-tab.

Tier 1: open Manage Reports once per tab; search/download loop without re-home.
Tier 2: short timeouts when Download never starts (no 3‑minute hangs).
Tier 3: one Chromium context, N tabs (shared cookies); async parallel loops.

Deps live in this Job (playwright). Kernel never launches a browser.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable

from reports_catalog import ReportSpec

OPERA_URL = (
    "https://mtce2.oraclehospitality.eu-frankfurt-1.ocs.oraclecloud.com"
    "/ITOAS/operacloud"
)

# --- Fail-fast budgets (Tier 2) ---
DOWNLOAD_TIMEOUT_MS = 50_000  # was 180s — do not pad failed reports
DOWNLOAD_AS_TIMEOUT_MS = 12_000
XML_RADIO_TIMEOUT_MS = 12_000
ROW_TIMEOUT_MS = 25_000
SEARCH_SETTLE_MS = 1_200

# XPaths / CSS from harness + live discover (Opera 26.1 TMR).
XP_USERNAME = "//input[contains(@id, 'username') and contains(@type, 'text')]"
XP_PASSWORD = "//input[contains(@id, 'password') and contains(@type, 'password')]"
XP_SIGN_IN = (
    "//span[contains(@class,'oj-button-text') and "
    "(normalize-space(.)='Sign In' or normalize-space(.)='Oturum Aç')]"
)
XP_REPORTS_MENU = (
    "//div[(contains(@aria-haspopup,'menu') or @role='menuitem') "
    "and contains(@aria-label,'Reports')]"
)
CSS_REPORT_NAME = "input[id*='reportName'][id*='::content']"
XP_REPORT_NAME = "//input[contains(@id,'reportName') and contains(@id,'::content')]"
# Opera 26 uses teal buttons: "Download As...", "Preview / Download"
XP_DOWNLOAD_AS = (
    "//button[contains(normalize-space(.),'Download As')]"
    " | //span[normalize-space()='Download As...']"
    " | //a[contains(normalize-space(.),'Download As')]"
)
XP_XML = (
    "//div[@role='radiogroup']//label[normalize-space()='XML']"
    " | //label[normalize-space()='XML']"
    " | //input[@type='radio' and (@value='XML' or contains(@id,'XML'))]"
)
XP_DOWNLOAD = (
    "//button[normalize-space()='Download']"
    " | //a[contains(@class,'xr2')]//span[text()='Download']"
    " | //span[normalize-space()='Download']"
)
XP_EDIT = (
    "//a[contains(@class, 'xr2') and contains(@role, 'button') and "
    "span[contains(text(),'Edit')]]"
)
XP_LAST_YEAR = "//label[@class='x1lg' and contains(text(), 'Last Year')]"
XP_TAX = "//label[@class='x1lg' and contains(text(), 'Tax')]"
XP_DAYS = "//label[text()='Number of Days']/preceding-sibling::input[@type='text']"
XP_ROOM_TYPE = "//label[text()='Room Type']/preceding-sibling::input[@type='text']"
XP_VIPS = "//label[text()='VIPs']/preceding-sibling::input[@type='text']"
XP_VIP_ONLY = "//label[contains(@class,'x1lg') and normalize-space()='VIP Only']"
XP_REVENUE = "//label[contains(@class,'x1lg') and normalize-space()='Revenue']"
XP_PRINT_RATE = "//label[contains(@class,'x1lg') and normalize-space()='Print Rate']"
XP_FROM_DATE = (
    "//label[text()='From Date']/ancestor::span[contains(@id, 'odec_flem')]"
    "//input[@type='text']"
)
XP_TO_DATE = (
    "//label[text()='To Date']/ancestor::span[contains(@id, 'odec_flem')]"
    "//input[@type='text']"
)

SayFn = Callable[[str], None]


def _say(say: SayFn | None, msg: str) -> None:
    if say:
        say(msg)


def truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_workers(raw: str) -> int:
    try:
        n = int((raw or "3").strip() or "3")
    except ValueError:
        return 3
    return max(1, min(n, 4))  # cap tabs — ADF dislikes many concurrent UIs


def _chunk_specs(
    specs: tuple[ReportSpec, ...], n: int
) -> list[tuple[ReportSpec, ...]]:
    """Split reports across tabs (round-robin keeps heavy ones spread)."""
    n = max(1, min(n, len(specs)))
    buckets: list[list[ReportSpec]] = [[] for _ in range(n)]
    for i, spec in enumerate(specs):
        buckets[i % n].append(spec)
    return [tuple(b) for b in buckets if b]


def _internal_xpath(internal_name: str) -> str:
    safe = internal_name.replace("'", "")
    return f"//td//span[@title='Internal Report Name' and text()='{safe}']"


# ---------------------------------------------------------------------------
# Sync helpers (used by download_one_report sync path)
# ---------------------------------------------------------------------------


def _try_click(page: Any, xpath: str, timeout_ms: int = 5000) -> bool:
    try:
        loc = page.locator(f"xpath={xpath}").first
        loc.wait_for(state="visible", timeout=timeout_ms)
        loc.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


def _js_click(locator: Any) -> None:
    """Click via DOM (ADF menus/buttons often report as not visible)."""
    locator.evaluate("el => el.click()")


def dismiss_blocking_dialogs(page: Any, *, say: SayFn | None = None) -> None:
    for sel in (
        "xpath=//div[@role='dialog']//button[@aria-label='Close']",
        "xpath=//div[@role='dialog']//button[normalize-space()='Close']",
        "xpath=//div[@role='dialog']//a[@aria-label='Close']",
        "xpath=//button[contains(@aria-label,'Remind me later')]",
    ):
        try:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=2_000)
                page.wait_for_timeout(300)
                _say(say, "dismissed dialog")
        except Exception:
            continue
    try:
        page.get_by_role("button", name="Dismiss").click(timeout=800)
    except Exception:
        pass
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def wait_for_shell(page: Any, *, timeout_ms: int = 120_000, say: SayFn | None = None) -> None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        dismiss_blocking_dialogs(page, say=say)
        try:
            if page.get_by_text("Reports", exact=True).count():
                return
            if page.locator("xpath=//div[@aria-label='Reports']").count():
                return
            if page.get_by_text("Hello,", exact=False).count():
                return
        except Exception:
            pass
        page.wait_for_timeout(500)
    raise TimeoutError("Opera shell not ready (Reports menu)")


def login(page: Any, user: str, password: str, *, say: SayFn | None = None) -> None:
    _say(say, "navigate Opera Cloud…")
    page.goto(OPERA_URL, wait_until="domcontentloaded", timeout=120_000)
    try:
        page.locator(f"xpath={XP_USERNAME}").first.wait_for(state="visible", timeout=15_000)
        page.locator(f"xpath={XP_USERNAME}").first.fill(user)
        page.locator(f"xpath={XP_PASSWORD}").first.fill(password)
        if not _try_click(page, XP_SIGN_IN, timeout_ms=10_000):
            page.keyboard.press("Enter")
    except Exception:
        _say(say, "login form skipped (session or redirect)…")
    wait_for_shell(page, timeout_ms=240_000, say=say)
    _say(say, "login ok")


def manage_reports_ready(page: Any) -> bool:
    try:
        if page.locator(CSS_REPORT_NAME).count() and page.locator(CSS_REPORT_NAME).first.is_visible():
            return True
    except Exception:
        pass
    return False


def open_manage_reports(page: Any, *, say: SayFn | None = None) -> None:
    """Open Manage Reports if not already on the search form (Tier 1 entry)."""
    if manage_reports_ready(page):
        _say(say, "Manage Reports already open")
        return

    _say(say, "open Manage Reports…")
    dismiss_blocking_dialogs(page, say=say)
    page.wait_for_timeout(400)

    last_err: Exception | None = None
    for attempt in range(1, 4):
        dismiss_blocking_dialogs(page, say=say)
        try:
            # Prefer top-nav Reports (Opera 26) then dropdown item
            clicked_reports = False
            for open_reports in (
                lambda: page.get_by_text("Reports", exact=True).last.click(timeout=8_000),
                lambda: page.locator("xpath=//div[@aria-label='Reports']").first.click(
                    timeout=8_000
                ),
                lambda: page.locator(
                    "xpath=//a[contains(normalize-space(.),'Reports')]"
                ).first.click(timeout=8_000),
            ):
                try:
                    open_reports()
                    clicked_reports = True
                    break
                except Exception as exc:
                    last_err = exc
            if not clicked_reports:
                raise TimeoutError("Reports menu not clickable") from last_err

            page.wait_for_timeout(700)
            # ADF dropdown rows are often not "visible" — use DOM click
            manage = page.locator(
                "xpath=//tr[@role='menuitem' and contains(.,'Manage Reports')]"
            ).first
            try:
                _js_click(manage)
            except Exception:
                page.get_by_text("Manage Reports", exact=True).first.evaluate(
                    "el => el.click()"
                )

            deadline = time.time() + 45
            while time.time() < deadline:
                if manage_reports_ready(page):
                    try:
                        page.get_by_text("Show Internal", exact=False).first.click(
                            timeout=2_000
                        )
                    except Exception:
                        pass
                    _say(say, "Manage Reports ready")
                    return
                page.wait_for_timeout(400)
            raise TimeoutError("Manage Reports form did not appear")
        except Exception as exc:
            last_err = exc
            _say(say, f"Manage Reports attempt {attempt}/3: {exc}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(1000)

    raise TimeoutError(
        f"could not open Manage Reports from Reports menu: {last_err}"
    ) from last_err


def return_to_manage_list(page: Any, *, say: SayFn | None = None) -> None:
    """Leave report detail / dialogs and land back on Manage Reports search (Tier 1)."""
    dismiss_blocking_dialogs(page, say=say)
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
        except Exception:
            break

    if manage_reports_ready(page):
        return

    # Preferred: breadcrumb on Report Parameters page
    for clicker in (
        lambda: page.get_by_text("Back to Manage Reports", exact=False).first.click(
            timeout=4_000
        ),
        lambda: page.locator("xpath=//a[contains(.,'Back to Manage Reports')]").first.click(
            timeout=4_000
        ),
        lambda: page.locator("xpath=//a[contains(.,'Manage Reports')]").first.click(
            timeout=3_000
        ),
    ):
        try:
            clicker()
            page.wait_for_timeout(900)
            if manage_reports_ready(page):
                return
        except Exception:
            continue

    try:
        open_manage_reports(page, say=say)
    except Exception as exc:
        _say(say, f"return_to_list warn: {exc}")


def apply_options(
    page: Any,
    spec: ReportSpec,
    *,
    today: date,
    say: SayFn | None = None,
) -> None:
    # Skip Edit when already on Report Parameters
    try:
        if page.get_by_text("Download As", exact=False).count() == 0:
            _try_click(page, XP_EDIT, timeout_ms=4_000)
            page.wait_for_timeout(350)
    except Exception:
        pass

    if spec.last_year:
        _try_click(page, XP_LAST_YEAR, timeout_ms=5_000)
    if spec.tax:
        _try_click(page, XP_TAX, timeout_ms=5_000)
    if spec.number_of_days is not None:
        try:
            if page.locator(f"xpath={XP_DAYS}").count():
                page.locator(f"xpath={XP_DAYS}").first.fill(
                    str(spec.number_of_days), timeout=5_000
                )
        except Exception:
            pass
    if spec.room_type:
        try:
            page.locator(f"xpath={XP_ROOM_TYPE}").first.fill(spec.room_type, timeout=5_000)
        except Exception:
            pass
    if spec.vips:
        try:
            if page.locator(f"xpath={XP_VIPS}").count():
                page.locator(f"xpath={XP_VIPS}").first.fill(spec.vips, timeout=5_000)
        except Exception:
            pass
    if spec.vip_only:
        _try_click(page, XP_VIP_ONLY, timeout_ms=4_000)
    if spec.revenue:
        _try_click(page, XP_REVENUE, timeout_ms=4_000)
    if spec.print_rate:
        _try_click(page, XP_PRINT_RATE, timeout_ms=4_000)
    if spec.set_from_to_date:
        date_text = today.strftime("%d.%m.%Y")
        for xp in (XP_FROM_DATE, XP_TO_DATE):
            try:
                if page.locator(f"xpath={xp}").count():
                    loc = page.locator(f"xpath={xp}").first
                    loc.fill("")
                    loc.fill(date_text)
            except Exception:
                pass
    _say(say, f"options {spec.key}")


def _fill_report_name(page: Any, text: str) -> None:
    if page.locator(CSS_REPORT_NAME).count():
        page.locator(CSS_REPORT_NAME).first.fill(text)
        return
    try:
        page.get_by_label("Report Name").fill(text)
        return
    except Exception:
        pass
    page.locator(f"xpath={XP_REPORT_NAME}").first.fill(text, timeout=10_000)


def _click_search(page: Any) -> None:
    for clicker in (
        lambda: page.get_by_role("button", name="Search").click(timeout=6_000),
        lambda: page.locator("xpath=//button[normalize-space()='Search']").first.click(
            timeout=6_000
        ),
        lambda: page.locator(
            "xpath=//a[contains(@class,'xr2') and .//span[text()='Search']]"
        ).first.click(timeout=6_000),
    ):
        try:
            clicker()
            return
        except Exception:
            continue
    raise TimeoutError("Search button not found")


def download_one_report(
    page: Any,
    spec: ReportSpec,
    dest_dir: Path,
    *,
    today: date,
    say: SayFn | None = None,
    already_on_list: bool = False,
) -> Path:
    """Search → open → options → XML download. Caller keeps us on Manage Reports."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out_path = dest_dir / spec.out_name
    _say(say, f"download {spec.key} ({spec.internal_name})…")

    try:
        if not already_on_list and not manage_reports_ready(page):
            open_manage_reports(page, say=say)
        elif not manage_reports_ready(page):
            return_to_manage_list(page, say=say)
            if not manage_reports_ready(page):
                open_manage_reports(page, say=say)

        _fill_report_name(page, spec.search_text)
        _click_search(page)
        page.wait_for_timeout(SEARCH_SETTLE_MS)

        xp_row = _internal_xpath(spec.internal_name)
        row = page.locator(f"xpath={xp_row}").first
        row.wait_for(state="visible", timeout=ROW_TIMEOUT_MS)
        row.click()
        page.wait_for_timeout(800)

        apply_options(page, spec, today=today, say=say)

        # Proven path (first green manager run): Download As → XML → Download
        page.wait_for_timeout(500)
        if not _try_click(page, XP_DOWNLOAD_AS, timeout_ms=DOWNLOAD_AS_TIMEOUT_MS):
            if not _try_click(
                page,
                "//*[contains(normalize-space(.),'Download As')]",
                timeout_ms=8_000,
            ):
                page.get_by_text("Download As", exact=False).first.click(
                    timeout=DOWNLOAD_AS_TIMEOUT_MS
                )
        page.wait_for_timeout(500)

        xml_ok = False
        for xp in (
            "//div[@role='radiogroup']//label[normalize-space()='XML']",
            "//label[normalize-space()='XML']",
            "//*[normalize-space()='XML' and (self::label or self::span)]",
        ):
            if _try_click(page, xp, timeout_ms=XML_RADIO_TIMEOUT_MS):
                xml_ok = True
                break
        if not xml_ok:
            page.get_by_text("XML", exact=True).first.click(timeout=XML_RADIO_TIMEOUT_MS)
        page.wait_for_timeout(400)

        with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as dl_info:
            if not _try_click(page, XP_DOWNLOAD, timeout_ms=10_000):
                if not _try_click(
                    page,
                    "//button[normalize-space()='Download']",
                    timeout_ms=8_000,
                ):
                    page.get_by_text("Download", exact=True).first.click(timeout=10_000)
        download = dl_info.value
        tmp = dest_dir / f".tmp_{spec.key}_{download.suggested_filename}"
        download.save_as(str(tmp))
        if out_path.exists():
            out_path.unlink()
        shutil.move(str(tmp), str(out_path))
        _say(say, f"saved {out_path.name} ({out_path.stat().st_size} bytes)")
        return out_path
    except Exception:
        shot = dest_dir / f"fail_{spec.key}.png"
        try:
            page.screenshot(path=str(shot), full_page=True)
            _say(say, f"screenshot {shot.name}")
        except Exception:
            pass
        raise
    finally:
        # Tier 1: always try to sit back on the list for the next report
        try:
            return_to_manage_list(page, say=say)
        except Exception:
            pass


def _run_tab_sync(
    page: Any,
    specs: tuple[ReportSpec, ...],
    dest_dir: Path,
    today: date,
    tab_id: int,
    say: SayFn | None,
) -> dict[str, str]:
    """One tab: open Manage Reports once, then stay-on-list loop."""
    results: dict[str, str] = {}
    try:
        open_manage_reports(page, say=say)
        on_list = True
    except Exception as exc:
        _say(say, f"initial Manage Reports open failed: {exc}")
        on_list = False

    for i, spec in enumerate(specs, start=1):
        t0 = time.perf_counter()
        _say(say, f"[tab{tab_id} {i}/{len(specs)}] start {spec.key}")
        try:
            download_one_report(
                page,
                spec,
                dest_dir,
                today=today,
                say=say,
                already_on_list=on_list,
            )
            sec = time.perf_counter() - t0
            results[spec.key] = f"ok:{sec:.1f}s"
            on_list = True
            _say(say, f"[tab{tab_id} {i}/{len(specs)}] ok {spec.key} in {sec:.1f}s")
        except Exception as exc:  # noqa: BLE001
            sec = time.perf_counter() - t0
            results[spec.key] = f"{type(exc).__name__}: {exc}"
            on_list = False
            _say(
                say,
                f"[tab{tab_id} {i}/{len(specs)}] FAIL {spec.key} after {sec:.1f}s",
            )
            try:
                return_to_manage_list(page, say=say)
                if not manage_reports_ready(page):
                    open_manage_reports(page, say=say)
                on_list = manage_reports_ready(page)
            except Exception as rec:
                _say(say, f"recover warn: {rec}")
    return results


def download_reports(
    specs: tuple[ReportSpec, ...],
    dest_dir: Path,
    *,
    user: str,
    password: str,
    today: date,
    headless: bool = True,
    workers: int = 3,
    say: SayFn | None = None,
) -> dict[str, str]:
    """Login once; 1 tab sequential or N tabs same context (Tier 3).

    Returns map key → ``ok:12.3s`` or error message.
    """
    from playwright.sync_api import sync_playwright

    dest_dir.mkdir(parents=True, exist_ok=True)
    if not specs:
        return {}

    n_tabs = 1 if len(specs) == 1 else parse_workers(str(workers))
    n_tabs = min(n_tabs, len(specs))
    t_all = time.perf_counter()

    if n_tabs <= 1:
        _say(say, "mode=sequential stay-on-list (1 tab)")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-popup-blocking", "--disable-notifications"],
            )
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            login(page, user, password, say=say)
            results = _run_tab_sync(page, specs, dest_dir, today, 1, say)
            context.close()
            browser.close()
        total = time.perf_counter() - t_all
        _say(say, f"download phase total {total:.1f}s for {len(specs)} report(s)")
        return results

    # Tier 3: multi-tab same context via asyncio; fall back to 1-tab on crash
    _say(say, f"mode=multi-tab stay-on-list ({n_tabs} tabs, shared session)")
    try:
        results = asyncio.run(
            _download_reports_async(
                specs,
                dest_dir,
                user=user,
                password=password,
                today=today,
                headless=headless,
                n_tabs=n_tabs,
                say=say,
            )
        )
    except Exception as multi_exc:
        _say(say, f"multi-tab failed ({multi_exc}); falling back to 1-tab sequential…")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-popup-blocking", "--disable-notifications"],
            )
            context = browser.new_context(accept_downloads=True)
            page = context.new_page()
            login(page, user, password, say=say)
            results = _run_tab_sync(page, specs, dest_dir, today, 1, say)
            context.close()
            browser.close()
    total = time.perf_counter() - t_all
    _say(say, f"download phase total {total:.1f}s for {len(specs)} report(s)")
    return results


# ---------------------------------------------------------------------------
# Async multi-tab (Tier 3) — same BrowserContext, parallel pages
# ---------------------------------------------------------------------------


async def _adismiss(page: Any) -> None:
    for sel in (
        "xpath=//div[@role='dialog']//button[@aria-label='Close']",
        "xpath=//div[@role='dialog']//button[normalize-space()='Close']",
        "xpath=//button[contains(@aria-label,'Remind me later')]",
    ):
        try:
            loc = page.locator(sel)
            if await loc.count() and await loc.first.is_visible():
                await loc.first.click(timeout=2_000)
                await page.wait_for_timeout(200)
        except Exception:
            continue
    try:
        await page.get_by_role("button", name="Dismiss").click(timeout=800)
    except Exception:
        pass
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _await_shell(page: Any, timeout_ms: int = 180_000) -> None:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        await _adismiss(page)
        try:
            if await page.get_by_text("Reports", exact=True).count():
                return
            if await page.locator("xpath=//div[@aria-label='Reports']").count():
                return
            if await page.get_by_text("Hello,", exact=False).count():
                return
        except Exception:
            pass
        await page.wait_for_timeout(500)
    raise TimeoutError("Opera shell not ready")


async def _alogin(page: Any, user: str, password: str, say: SayFn | None) -> None:
    _say(say, "navigate Opera Cloud…")
    await page.goto(OPERA_URL, wait_until="domcontentloaded", timeout=120_000)
    try:
        await page.locator(f"xpath={XP_USERNAME}").first.wait_for(
            state="visible", timeout=15_000
        )
        await page.locator(f"xpath={XP_USERNAME}").first.fill(user)
        await page.locator(f"xpath={XP_PASSWORD}").first.fill(password)
        try:
            await page.locator(f"xpath={XP_SIGN_IN}").first.click(timeout=10_000)
        except Exception:
            await page.keyboard.press("Enter")
    except Exception:
        _say(say, "login form skipped…")
    await _await_shell(page, 240_000)
    _say(say, "login ok")


async def _amanage_ready(page: Any) -> bool:
    try:
        loc = page.locator(CSS_REPORT_NAME)
        if await loc.count() and await loc.first.is_visible():
            return True
    except Exception:
        pass
    return False


async def _aopen_manage(page: Any, say: SayFn | None) -> None:
    if await _amanage_ready(page):
        return
    _say(say, "open Manage Reports…")
    await _adismiss(page)
    opened = False
    for opener in (
        lambda: page.locator("xpath=//div[@aria-label='Reports']").first.click(
            timeout=8_000
        ),
        lambda: page.get_by_text("Reports", exact=True).last.click(timeout=8_000),
    ):
        try:
            await opener()
            await page.wait_for_timeout(500)
            await page.locator(
                "xpath=//*[normalize-space()='Manage Reports']"
            ).first.click(timeout=8_000)
            opened = True
            break
        except Exception:
            continue
    if not opened:
        raise TimeoutError("could not open Manage Reports")
    deadline = time.time() + 60
    while time.time() < deadline:
        if await _amanage_ready(page):
            break
        await page.wait_for_timeout(400)
    else:
        raise TimeoutError("Manage Reports form did not appear")
    try:
        await page.get_by_text("Show Internal", exact=False).first.click(timeout=2_500)
    except Exception:
        pass


async def _areturn_list(page: Any) -> None:
    await _adismiss(page)
    for _ in range(3):
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(150)
        except Exception:
            break
    if await _amanage_ready(page):
        return
    for clicker in (
        lambda: page.get_by_text("Manage Reports", exact=True).first.click(timeout=3_000),
        lambda: page.locator("xpath=//a[contains(.,'Manage Reports')]").first.click(
            timeout=3_000
        ),
    ):
        try:
            await clicker()
            await page.wait_for_timeout(600)
            if await _amanage_ready(page):
                return
        except Exception:
            continue
    await _aopen_manage(page, None)


async def _atry_click(page: Any, xpath: str, timeout_ms: int) -> bool:
    try:
        loc = page.locator(f"xpath={xpath}").first
        await loc.wait_for(state="visible", timeout=timeout_ms)
        await loc.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


async def _aapply_options(page: Any, spec: ReportSpec, today: date) -> None:
    await _atry_click(page, XP_EDIT, 5_000)
    await page.wait_for_timeout(350)
    if spec.last_year:
        await _atry_click(page, XP_LAST_YEAR, 5_000)
    if spec.tax:
        await _atry_click(page, XP_TAX, 5_000)
    if spec.number_of_days is not None:
        try:
            if await page.locator(f"xpath={XP_DAYS}").count():
                await page.locator(f"xpath={XP_DAYS}").first.fill(
                    str(spec.number_of_days), timeout=5_000
                )
        except Exception:
            pass
    if spec.room_type:
        try:
            await page.locator(f"xpath={XP_ROOM_TYPE}").first.fill(
                spec.room_type, timeout=5_000
            )
        except Exception:
            pass
    if spec.vips:
        try:
            if await page.locator(f"xpath={XP_VIPS}").count():
                await page.locator(f"xpath={XP_VIPS}").first.fill(
                    spec.vips, timeout=5_000
                )
        except Exception:
            pass
    if spec.vip_only:
        await _atry_click(page, XP_VIP_ONLY, 4_000)
    if spec.revenue:
        await _atry_click(page, XP_REVENUE, 4_000)
    if spec.print_rate:
        await _atry_click(page, XP_PRINT_RATE, 4_000)
    if spec.set_from_to_date:
        date_text = today.strftime("%d.%m.%Y")
        for xp in (XP_FROM_DATE, XP_TO_DATE):
            try:
                if await page.locator(f"xpath={xp}").count():
                    loc = page.locator(f"xpath={xp}").first
                    await loc.fill("")
                    await loc.fill(date_text)
            except Exception:
                pass


async def _adownload_one(
    page: Any,
    spec: ReportSpec,
    dest_dir: Path,
    today: date,
    say: SayFn | None,
) -> Path:
    out_path = dest_dir / spec.out_name
    _say(say, f"download {spec.key}…")
    try:
        if not await _amanage_ready(page):
            await _aopen_manage(page, say)

        if await page.locator(CSS_REPORT_NAME).count():
            await page.locator(CSS_REPORT_NAME).first.fill(spec.search_text)
        else:
            await page.get_by_label("Report Name").fill(spec.search_text)

        try:
            await page.get_by_role("button", name="Search").click(timeout=6_000)
        except Exception:
            await page.locator(
                "xpath=//button[normalize-space()='Search']"
            ).first.click(timeout=6_000)
        await page.wait_for_timeout(SEARCH_SETTLE_MS)

        row = page.locator(f"xpath={_internal_xpath(spec.internal_name)}").first
        await row.wait_for(state="visible", timeout=ROW_TIMEOUT_MS)
        await row.click()
        await page.wait_for_timeout(700)
        await _aapply_options(page, spec, today)

        try:
            await page.get_by_role("button", name="Download As...").click(
                timeout=DOWNLOAD_AS_TIMEOUT_MS
            )
        except Exception:
            await page.locator("xpath=//button[contains(.,'Download As')]").first.click(
                timeout=DOWNLOAD_AS_TIMEOUT_MS
            )
        await page.wait_for_timeout(400)
        try:
            await page.get_by_text("XML", exact=True).first.click(
                timeout=XML_RADIO_TIMEOUT_MS
            )
        except Exception:
            await page.locator(f"xpath={XP_XML}").first.click(
                timeout=XML_RADIO_TIMEOUT_MS
            )
        await page.wait_for_timeout(300)

        async with page.expect_download(timeout=DOWNLOAD_TIMEOUT_MS) as dl_info:
            try:
                await page.get_by_role("button", name="Download").click(timeout=10_000)
            except Exception:
                await page.get_by_text("Download", exact=True).first.click(timeout=10_000)
        download = await dl_info.value
        tmp = dest_dir / f".tmp_{spec.key}_{download.suggested_filename}"
        await download.save_as(str(tmp))
        if out_path.exists():
            out_path.unlink()
        shutil.move(str(tmp), str(out_path))
        _say(say, f"saved {out_path.name} ({out_path.stat().st_size} bytes)")
        return out_path
    except Exception:
        try:
            await page.screenshot(
                path=str(dest_dir / f"fail_{spec.key}.png"), full_page=True
            )
        except Exception:
            pass
        raise
    finally:
        try:
            await _areturn_list(page)
        except Exception:
            pass


async def _atab_loop(
    page: Any,
    specs: tuple[ReportSpec, ...],
    dest_dir: Path,
    today: date,
    tab_id: int,
    say: SayFn | None,
) -> dict[str, str]:
    results: dict[str, str] = {}
    await _aopen_manage(page, say)
    for i, spec in enumerate(specs, start=1):
        t0 = time.perf_counter()
        _say(say, f"[tab{tab_id} {i}/{len(specs)}] start {spec.key}")
        try:
            await _adownload_one(page, spec, dest_dir, today, say)
            sec = time.perf_counter() - t0
            results[spec.key] = f"ok:{sec:.1f}s"
            _say(say, f"[tab{tab_id} {i}/{len(specs)}] ok {spec.key} in {sec:.1f}s")
        except Exception as exc:  # noqa: BLE001
            sec = time.perf_counter() - t0
            results[spec.key] = f"{type(exc).__name__}: {exc}"
            _say(say, f"[tab{tab_id} {i}/{len(specs)}] FAIL {spec.key} after {sec:.1f}s")
            try:
                await _areturn_list(page)
                if not await _amanage_ready(page):
                    await _aopen_manage(page, say)
            except Exception:
                pass
    return results


async def _download_reports_async(
    specs: tuple[ReportSpec, ...],
    dest_dir: Path,
    *,
    user: str,
    password: str,
    today: date,
    headless: bool,
    n_tabs: int,
    say: SayFn | None,
) -> dict[str, str]:
    from playwright.async_api import async_playwright

    chunks = _chunk_specs(specs, n_tabs)
    results: dict[str, str] = {}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-popup-blocking", "--disable-notifications"],
        )
        context = await browser.new_context(accept_downloads=True)
        # Tab 0: login
        page0 = await context.new_page()
        await _alogin(page0, user, password, say)

        pages = [page0]
        for i in range(1, len(chunks)):
            pg = await context.new_page()
            await pg.goto(OPERA_URL, wait_until="domcontentloaded", timeout=120_000)
            await _await_shell(pg, 120_000)
            pages.append(pg)
            _say(say, f"tab{i + 1} ready (shared session)")

        # Parallel stay-on-list loops
        tab_results = await asyncio.gather(
            *[
                _atab_loop(pages[i], chunks[i], dest_dir, today, i + 1, say)
                for i in range(len(chunks))
            ]
        )
        for part in tab_results:
            results.update(part)

        await context.close()
        await browser.close()

    return results
