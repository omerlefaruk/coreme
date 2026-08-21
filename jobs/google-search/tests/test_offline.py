"""Offline proof: parsing works without network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402

JOB_DIR = Path(__file__).resolve().parent.parent

SAMPLE = """
<div><h3>CoreMe automation kernel</h3><a href="/url?q=https://example.com/a&amp;sa=U"></a></div>
<div><h3><span>Second <b>result</b></span></h3><a href="/url?q=https://example.com/b&amp;sa=U"></a></div>
"""


def test_job_files_exist() -> None:
    assert (JOB_DIR / "JOB.toml").is_file()
    assert (JOB_DIR / "main.py").is_file()


def test_parse_extracts_titles_and_links() -> None:
    results = main.parse_results(SAMPLE)
    assert len(results) == 2
    assert results[0]["title"] == "CoreMe automation kernel"
    assert results[0]["url"] == "https://example.com/a"
    assert results[1]["title"] == "Second result"


def test_parse_empty_page() -> None:
    assert main.parse_results("<html><body>consent</body></html>") == []


DDG_SAMPLE = """
<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fx&amp;rut=abc">Core<b>Me</b> page</a>
<a class="result__a" href="https://direct.example.com/y">Direct link</a>
"""


def test_parse_ddg_extracts_and_decodes() -> None:
    results = main.parse_ddg_results(DDG_SAMPLE)
    assert len(results) == 2
    assert results[0]["title"] == "CoreMe page"
    assert results[0]["url"] == "https://example.com/x"
    assert results[1]["url"] == "https://direct.example.com/y"
