"""Report catalog for Opera Cloud daily summary downloads.

All downloads share the same UI path (Reports → Manage Reports → search →
open → options → Download As… XML). Only *options* and *internal name* differ.

Discover/live default is ``manager`` only; add keys once that path is proven.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReportSpec:
    """One Opera export to download and (later) parse."""

    key: str
    """Stable id used in ``reports`` input and output filename stem."""

    internal_name: str
    """Internal Report Name column value in Manage Reports."""

    search_text: str
    """Text typed into the reportName search box (usually == internal_name)."""

    out_name: str
    """Filename written under input_dir (e.g. manager.xml)."""

    download_glob: str
    """Glob of browser download basenames before rename (manager*.XML)."""

    # Shared option toggles applied after Edit on the report form
    last_year: bool = False
    number_of_days: int | None = None
    tax: bool = False  # manager gross
    # Guest / arrivals filters (applied when non-empty / True)
    room_type: str = ""
    vips: str = ""
    vip_only: bool = False
    revenue: bool = False
    print_rate: bool = False
    set_from_to_date: bool = False  # use today for From/To Date
    extra: dict[str, Any] = field(default_factory=dict)


# Primary discovery target — same UI as every other report.
MANAGER = ReportSpec(
    key="manager",
    internal_name="manager_report",
    search_text="manager_report",
    out_name="manager.xml",
    download_glob="manager*.XML",
    last_year=True,
    number_of_days=8,
)

# Same internal report, different options (Tax) — scaffold after manager works.
MANAGER_GROSS = ReportSpec(
    key="manager_gross",
    internal_name="manager_report",
    search_text="manager_report",
    out_name="manager_gross.xml",
    download_glob="manager*.XML",
    last_year=True,
    number_of_days=8,
    tax=True,
)

RESENTEREDON = ReportSpec(
    key="resenteredon",
    internal_name="resenteredon",
    search_text="resenteredon",
    out_name="resenteredon.xml",
    download_glob="resenteredon*.XML",
)

COUNTRY_DAY = ReportSpec(
    key="countrybyday",
    internal_name="stat_countrybyday",
    search_text="stat_countrybyday",
    out_name="countrybyday.xml",
    download_glob="stat_countrybyday*.XML",
)

COUNTRY_MON = ReportSpec(
    key="countrybymon",
    internal_name="stat_countrybymon",
    search_text="stat_countrybymon",
    out_name="countrybymon.xml",
    download_glob="stat_countrybymon*.XML",
)

GIBYROOM_SUT = ReportSpec(
    key="gibyroom_SUT",
    internal_name="gibyroom",
    search_text="gibyroom",
    out_name="gibyroom_SUT.xml",
    download_glob="gibyroom*.XML",
    room_type="",  # fill when known from ops
    revenue=True,
)

GIBYROOM_VIP = ReportSpec(
    key="gibyroom_VIP",
    internal_name="gibyroom",
    search_text="gibyroom",
    out_name="gibyroom_VIP.xml",
    download_glob="gibyroom*.XML",
    vip_only=True,
    revenue=True,
)

ARRIVALS_GROUP = ReportSpec(
    key="arrivals_group",
    internal_name="res_detail",
    search_text="res_detail",
    out_name="arrivals_group.xml",
    download_glob="res_detail*.XML",
    print_rate=True,
    set_from_to_date=True,
)

ARRIVALS_VIP = ReportSpec(
    key="arrivals_VIP",
    internal_name="res_detail",
    search_text="res_detail",
    out_name="arrivals_VIP.xml",
    download_glob="res_detail*.XML",
    vip_only=True,
    print_rate=True,
    set_from_to_date=True,
)

GROUP_IN_HOUSE = ReportSpec(
    key="group_in_house",
    internal_name="grpinhousebyroom",
    search_text="grpinhousebyroom",
    out_name="group_in_house.xml",
    download_glob="grpinhousebyroom*.XML",
)

CATALOG: dict[str, ReportSpec] = {
    r.key: r
    for r in (
        MANAGER,
        MANAGER_GROSS,
        RESENTEREDON,
        COUNTRY_DAY,
        COUNTRY_MON,
        GIBYROOM_SUT,
        GIBYROOM_VIP,
        ARRIVALS_GROUP,
        ARRIVALS_VIP,
        GROUP_IN_HOUSE,
    )
}

# Safe live default until multi-report options are verified on site.
DEFAULT_LIVE_REPORTS = ("manager",)


def resolve_reports(raw: str) -> tuple[ReportSpec, ...]:
    """Parse comma list or ``all`` into ReportSpec tuple (catalog order)."""
    text = (raw or "").strip().lower()
    if not text or text == "default":
        keys = list(DEFAULT_LIVE_REPORTS)
    elif text == "all":
        keys = list(CATALOG.keys())
    else:
        keys = [p.strip() for p in text.split(",") if p.strip()]
    out: list[ReportSpec] = []
    unknown: list[str] = []
    for key in keys:
        spec = CATALOG.get(key)
        if spec is None:
            unknown.append(key)
        else:
            out.append(spec)
    if unknown:
        raise ValueError(f"unknown report key(s): {', '.join(unknown)}")
    if not out:
        raise ValueError("reports selection is empty")
    # stable catalog order
    order = {k: i for i, k in enumerate(CATALOG)}
    out.sort(key=lambda s: order[s.key])
    return tuple(out)
