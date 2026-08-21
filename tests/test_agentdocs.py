"""Tests for bundled agent docs (coreme skills)."""

from coreme import agentdocs


def test_bundled_docs_exist() -> None:
    docs = agentdocs.list_docs()
    assert "AGENTS.md" in docs
    assert "skills/build-job/SKILL.md" in docs
    assert "skills/fleet/SKILL.md" in docs
    assert all(path.is_file() for path in docs.values())


def test_read_doc_returns_content() -> None:
    text = agentdocs.read_doc("skills/fleet/SKILL.md")
    assert len(text) > 0


def test_read_doc_accepts_missing_extension() -> None:
    with_ext = agentdocs.read_doc("AGENTS.md")
    without_ext = agentdocs.read_doc("AGENTS")
    assert with_ext == without_ext


def test_unknown_slug_lists_known_docs() -> None:
    try:
        agentdocs.read_doc("nope")
    except agentdocs.AgentDocsError as error:
        assert "skills/fleet/SKILL.md" in str(error)
    else:
        raise AssertionError("expected AgentDocsError")


def test_install_copies_tree(tmp_path) -> None:  # type: ignore[no-untyped-def]
    written = agentdocs.install_docs(tmp_path)
    assert len(written) == len(agentdocs.list_docs())
    copied = tmp_path / "skills" / "build-job" / "SKILL.md"
    assert copied.is_file()


def test_cli_show_prints_doc(capfd) -> None:  # type: ignore[no-untyped-def]
    from coreme import cli

    exit_code = cli.main(["skills", "show", "AGENTS"])
    out = capfd.readouterr().out
    assert exit_code == 0
    assert "Job" in out


def test_cli_install_copies_docs(tmp_path, capfd) -> None:  # type: ignore[no-untyped-def]
    from coreme import cli

    target = tmp_path / "docs"
    exit_code = cli.main(["skills", "install", str(target)])
    assert exit_code == 0
    assert f"wrote {len(agentdocs.list_docs())}" in capfd.readouterr().out
    assert (target / "AGENTS.md").is_file()
