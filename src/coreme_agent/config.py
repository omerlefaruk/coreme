"""Agent config: TOML file with env and CLI precedence for the resident daemon.

Precedence: CLI flag > env var > config file > default. The default path is
``~/.coreme/agent.toml``, overridable with ``--config`` or
``COREME_AGENT_CONFIG``.
"""

from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_POLL_INTERVAL_SEC = 15.0
DEFAULT_HEARTBEAT_INTERVAL_SEC = 30.0
DEFAULT_SLOTS = 1
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_CONFIG_NAME = "agent.toml"


@dataclass(frozen=True)
class AgentConfig:
    hub_url: str | None = None
    machine_id: str | None = None
    machine_token: str | None = None
    tags: tuple[str, ...] = ()
    workspace: str = "."
    poll_interval_sec: float = DEFAULT_POLL_INTERVAL_SEC
    heartbeat_interval_sec: float = DEFAULT_HEARTBEAT_INTERVAL_SEC
    slots: int = DEFAULT_SLOTS
    log_level: str = DEFAULT_LOG_LEVEL
    log_file: str | None = None
    config_path: str | None = None


class ConfigError(Exception):
    """Config file exists but cannot be parsed or has invalid values."""


def default_config_path(env: Mapping[str, str] | None = None) -> Path:
    environ = os.environ if env is None else env
    override = environ.get("COREME_AGENT_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".coreme" / DEFAULT_CONFIG_NAME


def load(
    *,
    path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    hub_url: str | None = None,
    machine_id: str | None = None,
    machine_token: str | None = None,
    tags: Sequence[str] | None = None,
    workspace: str | None = None,
    poll_interval_sec: float | None = None,
    heartbeat_interval_sec: float | None = None,
    slots: int | None = None,
    log_level: str | None = None,
    log_file: str | None = None,
) -> AgentConfig:
    """Load agent config. Explicit kwargs are CLI overrides (None = unset)."""
    environ = os.environ if env is None else env
    resolved = Path(path) if path else default_config_path(environ)
    raw = _read_toml(resolved)
    hub = _section(raw, "hub")
    agent = _section(raw, "agent")
    return AgentConfig(
        hub_url=_pick(hub_url, environ, "COREME_HUB_URL", hub.get("url")),
        machine_id=_pick(machine_id, environ, "COREME_MACHINE_ID", hub.get("machine_id")),
        machine_token=_pick(machine_token, environ, "COREME_MACHINE_TOKEN", hub.get("token")),
        tags=_clean_tags(tags if tags is not None else agent.get("tags")),
        workspace=str(workspace if workspace is not None else (agent.get("workspace") or ".")),
        poll_interval_sec=_positive_float(
            poll_interval_sec
            if poll_interval_sec is not None
            else agent.get("poll_interval_sec", DEFAULT_POLL_INTERVAL_SEC),
            "poll_interval_sec",
        ),
        heartbeat_interval_sec=_positive_float(
            heartbeat_interval_sec
            if heartbeat_interval_sec is not None
            else agent.get("heartbeat_interval_sec", DEFAULT_HEARTBEAT_INTERVAL_SEC),
            "heartbeat_interval_sec",
        ),
        slots=max(1, int(slots if slots is not None else agent.get("slots", DEFAULT_SLOTS))),
        log_level=str(log_level or agent.get("log_level") or DEFAULT_LOG_LEVEL).upper(),
        log_file=str(log_file or agent.get("log_file")) or None,
        config_path=str(resolved),
    )


def save(config: AgentConfig, path: str | Path) -> Path:
    """Write a minimal TOML config. Best-effort 0o600 on POSIX."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if config.hub_url or config.machine_id or config.machine_token:
        lines.append("[hub]")
        if config.hub_url:
            lines.append(f"url = {_toml_str(config.hub_url)}")
        if config.machine_id:
            lines.append(f"machine_id = {_toml_str(config.machine_id)}")
        if config.machine_token:
            lines.append(f"token = {_toml_str(config.machine_token)}")
        lines.append("")
    lines.append("[agent]")
    rendered_tags = ", ".join(_toml_str(t) for t in config.tags)
    lines.append(f"tags = [{rendered_tags}]")
    lines.append(f"workspace = {_toml_str(config.workspace)}")
    lines.append(f"poll_interval_sec = {config.poll_interval_sec}")
    lines.append(f"heartbeat_interval_sec = {config.heartbeat_interval_sec}")
    lines.append(f"slots = {config.slots}")
    lines.append(f"log_level = {_toml_str(config.log_level)}")
    if config.log_file:
        lines.append(f"log_file = {_toml_str(config.log_file)}")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        target.chmod(0o600)
    return target


def split_csv(value: str | None) -> list[str]:
    """Parse a comma-separated flag value into clean tags."""
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read agent config {path}: {exc}") from exc


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    value = raw.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _pick(cli: str | None, env: Mapping[str, str], key: str, file_value: Any) -> str | None:
    if cli is not None:
        return cli
    env_value = env.get(key)
    if env_value:
        return env_value
    if file_value is not None:
        return str(file_value)
    return None


def _clean_tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(split_csv(value))
    if isinstance(value, Sequence):
        return tuple(str(v).strip() for v in value if str(v).strip())
    raise ConfigError("tags must be a list")


def _positive_float(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be > 0")
    return number


def _toml_str(value: str) -> str:
    # A JSON basic string is a valid TOML basic string for our values.
    return json.dumps(value)
