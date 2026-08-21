"""Google search automation: fetch results for a query, save JSON evidence."""

from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_H3_RE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_LINK_RE = re.compile(r'href="/url\?q=(https?://[^&"]+)', re.IGNORECASE)


def fetch_html(query: str) -> str:
    # gbv=1 requests the basic-HTML result page (no JS wall);
    # the CONSENT cookie skips the EU consent interstitial.
    url = "https://www.google.com/search?" + urllib.parse.urlencode(
        {"q": query, "num": "10", "gbv": "1", "hl": "en"}
    )
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Cookie": "CONSENT=YES+cb.20240101-00-p0.en+FX+000",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def fetch_ddg_html(query: str) -> str:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


_DDG_LINK_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _decode_ddg_url(href: str) -> str:
    if "uddg=" in href:
        match = re.search(r"uddg=([^&]+)", href)
        if match:
            return urllib.parse.unquote(match.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href


def parse_ddg_results(html: str) -> list[dict[str, str]]:
    results = []
    for href, raw_title in _DDG_LINK_RE.findall(html):
        title = _TAG_RE.sub("", raw_title).strip()
        if title:
            results.append({"title": title, "url": _decode_ddg_url(href)})
    return results


def parse_results(html: str) -> list[dict[str, str]]:
    titles = [_TAG_RE.sub("", t).strip() for t in _H3_RE.findall(html)]
    links = [link.replace("&amp;", "&") for link in _LINK_RE.findall(html)]
    results: list[dict[str, str]] = []
    for index, title in enumerate(titles):
        if not title:
            continue
        results.append(
            {"title": title, "url": links[index] if index < len(links) else ""}
        )
    return results


def main() -> None:
    query = os.environ["COREME_INPUT_query"]
    print(f"searching for: {query}")

    artifacts = Path(os.environ["COREME_ARTIFACTS_DIR"])
    source_used = "google"

    html = fetch_html(query)
    (artifacts / "google.html").write_text(html, encoding="utf-8")
    results = parse_results(html)

    if not results:
        # Google serves a JS wall to non-browser clients; fall back.
        print("google returned no parseable results; falling back to duckduckgo")
        source_used = "duckduckgo"
        ddg_html = fetch_ddg_html(query)
        (artifacts / "duckduckgo.html").write_text(ddg_html, encoding="utf-8")
        results = parse_ddg_results(ddg_html)

    payload = {
        "query": query,
        "source": source_used,
        "result_count": len(results),
        "results": results,
    }
    (artifacts / "results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"source used: {source_used}")
    print(f"results found: {len(results)}")
    for item in results[:3]:
        print(f"- {item['title']} -> {item['url']}")
    if not results:
        print("note: zero parsed results from all sources")


if __name__ == "__main__":
    main()
