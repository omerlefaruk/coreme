"""Load and validate JOB.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_TOP_LEVEL = {"name", "version", "entry", "proof", "runtime", "inputs", "secrets"}
ALLOWED_INPUT_TYPES = {"string", "int", "file"}
ALLOWED_INPUT_KEYS = {"type", "required", "default"}
ALLOWED_SECRETS_KEYS = {"names"}
IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
INPUT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class InputSpec:
    type: str
    required: bool = False
    default: str | None = None


@dataclass(frozen=True)
class JobManifest:
    name: str
    version: str
    entry: str
    offline: str
    job_path: str
    timeout_sec: int = 60
    inputs: dict[str, InputSpec] = field(default_factory=dict)
    secrets: list[str] = field(default_factory=list)


class ManifestError(Exception):
    """The Job manifest is missing or invalid."""


def load_manifest(job_path: str | Path) -> JobManifest:
    root = Path(job_path).resolve()
    if not root.is_dir():
        raise ManifestError(f"Job path is not a directory: {root}")

    toml_path = root / "JOB.toml"
    if not toml_path.is_file():
        raise ManifestError(f"JOB.toml not found in {root}")

    try:
        with toml_path.open("rb") as manifest_file:
            data = tomllib.load(manifest_file)
    except tomllib.TOMLDecodeError as error:
        raise ManifestError(f"Invalid TOML in {toml_path}: {error}") from error
    except OSError as error:
        raise ManifestError(f"Cannot read {toml_path}: {error}") from error

    _reject_unknown(data, ALLOWED_TOP_LEVEL, "top-level key(s) in JOB.toml")
    name = _require_string(data, "name")
    if not IDENTIFIER.fullmatch(name):
        raise ManifestError("'name' must be an identifier: [A-Za-z][A-Za-z0-9_-]*")
    version = _require_string(data, "version")
    entry = _require_string(data, "entry")

    proof = _require_table(data, "proof")
    _reject_unknown(proof, {"offline"}, "key(s) in [proof]")
    offline = _require_string(proof, "offline")

    runtime = data.get("runtime", {})
    if not isinstance(runtime, dict):
        raise ManifestError("[runtime] must be a table if present")
    _reject_unknown(runtime, {"timeout_sec"}, "key(s) in [runtime]")
    timeout = runtime.get("timeout_sec", 60)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout < 1:
        raise ManifestError("[runtime].timeout_sec must be a positive integer")

    entry_path = (root / entry).resolve()
    if not entry_path.is_relative_to(root):
        raise ManifestError(f"Entry must be inside job folder: {entry}")
    if not entry_path.is_file():
        raise ManifestError(f"Entry file not found: {entry_path}")

    return JobManifest(
        name=name,
        version=version,
        entry=entry,
        offline=offline,
        timeout_sec=timeout,
        job_path=str(root),
        inputs=_parse_inputs(data.get("inputs")),
        secrets=_parse_secrets(data.get("secrets")),
    )


def _parse_secrets(raw_secrets: object) -> list[str]:
    if raw_secrets is None:
        return []
    if not isinstance(raw_secrets, dict):
        raise ManifestError("[secrets] must be a table if present")
    _reject_unknown(raw_secrets, ALLOWED_SECRETS_KEYS, "key(s) in [secrets]")
    if "names" not in raw_secrets:
        raise ManifestError("[secrets].names is required when [secrets] is present")
    raw_names = raw_secrets["names"]
    if not isinstance(raw_names, list):
        raise ManifestError("[secrets].names must be an array of strings")
    if not raw_names:
        raise ManifestError("[secrets].names must not be empty")

    names: list[str] = []
    seen_lower: set[str] = set()
    for item in raw_names:
        if not isinstance(item, str) or not item:
            raise ManifestError("[secrets].names entries must be non-empty strings")
        if not SECRET_NAME.fullmatch(item):
            raise ManifestError(
                f"Invalid secret name: {item} (must match ^[A-Za-z_][A-Za-z0-9_]*$)"
            )
        if item.upper().startswith("COREME_"):
            raise ManifestError(f"Secret name must not use COREME_ prefix: {item}")
        key = item.lower()
        if key in seen_lower:
            raise ManifestError(f"Duplicate secret name (case-insensitive): {item}")
        seen_lower.add(key)
        names.append(item)
    return names


def _parse_inputs(raw_inputs: object) -> dict[str, InputSpec]:
    if raw_inputs is None:
        return {}
    if not isinstance(raw_inputs, dict):
        raise ManifestError("[inputs] must be a table if present")

    inputs: dict[str, InputSpec] = {}
    for name, raw_spec in raw_inputs.items():
        if not INPUT_NAME.fullmatch(name):
            raise ManifestError(f"Invalid input name: {name}")
        if not isinstance(raw_spec, dict):
            raise ManifestError(f"[inputs.{name}] must be a table")
        _reject_unknown(raw_spec, ALLOWED_INPUT_KEYS, f"key(s) in [inputs.{name}]")
        input_type = raw_spec.get("type")
        if input_type not in ALLOWED_INPUT_TYPES:
            allowed = ", ".join(sorted(ALLOWED_INPUT_TYPES))
            raise ManifestError(f"[inputs.{name}].type must be one of {allowed}")
        required = raw_spec.get("required", False)
        if not isinstance(required, bool):
            raise ManifestError(f"[inputs.{name}].required must be a boolean")
        default = raw_spec.get("default")
        if default is not None and not isinstance(default, str):
            raise ManifestError(f"[inputs.{name}].default must be a string")
        inputs[name] = InputSpec(input_type, required, default)
    return inputs


def _require_table(data: dict[str, object], key: str) -> dict[str, object]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ManifestError(f"[{key}] table is required")
    return value


def _require_string(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ManifestError(f"'{key}' must be a non-empty string")
    return value.strip()


def _reject_unknown(data: dict[str, object], allowed: set[str], location: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ManifestError(f"Unknown {location}: {', '.join(sorted(unknown))}")
