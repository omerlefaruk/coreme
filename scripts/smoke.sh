#!/usr/bin/env bash
# Wheel smoke test: exercise all three entry points from the installed wheel,
# outside the repo checkout (no repo src/ on sys.path).
# Prerequisite: the coreme[hub] wheel is installed in the active environment
# (see the `smoke` job in .github/workflows/ci.yml).
set -euo pipefail

fail() {
  echo "smoke: FAIL $*" >&2
  exit 1
}

run() {
  echo "+ $*"
  "$@"
}

# All three entry points exist and parse.
run coreme --version
run coreme-agent --version
run coreme-hub --version

# The imported package must come from site-packages, never the repo tree.
coreme_file="$(python -c 'import coreme; print(coreme.__file__)')"
case "$coreme_file" in
*site-packages*) echo "ok: coreme imported from $coreme_file" ;;
*) fail "coreme resolved outside site-packages: $coreme_file" ;;
esac

# Bundled agent docs must travel inside the wheel: a pipx-only machine still
# gets AGENTS.md + skills via `coreme skills`.
run coreme skills
coreme skills | grep -q "skills/fleet/SKILL.md" ||
  fail "bundled docs missing the fleet skill"
run coreme skills show AGENTS >/dev/null

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"

# a. Scaffold a Job (--name is required).
run coreme init hello --name hello
[ -f hello/JOB.toml ] || fail "init did not create hello/JOB.toml"

# The scaffolded offline proof is `pytest -q`; a wheel-only install has no
# pytest. Swap in a stdlib-only proof so the smoke stays dependency-free.
sed -i 's|^offline = .*|offline = "python -m compileall -q main.py"|' hello/JOB.toml

# b-d. test/run/ship with an explicit path: bare names resolve ONLY against
# releases/, so they cannot be used before the first ship.
run coreme test ./hello
run coreme run ./hello
run coreme ship ./hello
[ -d releases/hello-0.1.0 ] || fail "ship did not create releases/hello-0.1.0"

# e. Bare-name resolution against releases/.
run coreme run hello

# f. Agent local queue end to end (enqueue -> once -> assert succeeded).
# --coreme pins the activated interpreter explicitly: on Windows,
# CreateProcess can resolve a bare `python` to a venv's BASE interpreter
# (trampoline launchers), which may not have coreme installed.
coreme_exe="$(python -c 'import sys; print(sys.executable)')"
run coreme-agent enqueue --release releases/hello-0.1.0
run coreme-agent once --workspace . --coreme "$coreme_exe -m coreme"
listing="$(coreme-agent list --status succeeded)"
echo "$listing"
echo "$listing" | grep -q "status=succeeded" ||
  fail "agent did not record a succeeded assignment"

# g. Hub entry point. `coreme-hub migrate` needs Postgres (COREME_HUB_DSN);
# that path is covered by the Postgres-backed integration suite in the verify
# job's service container. Here we only prove the CLI imports (psycopg comes
# from the [hub] extra) and parses arguments.
run coreme-hub --help >/dev/null

echo "smoke: OK"
