"""Resolve declared Job inputs and secrets before a Run starts."""

from __future__ import annotations

import os
from pathlib import Path

from coreme.manifest import JobManifest


class InputError(Exception):
    """A CLI input does not match the Job declaration."""


class SecretError(Exception):
    """A declared secret is missing or empty in the process environment."""


def resolve_inputs(manifest: JobManifest, cli_pairs: list[tuple[str, str]]) -> dict[str, str]:
    provided: dict[str, str] = {}
    for name, value in cli_pairs:
        if name in provided:
            raise InputError(f"Duplicate input: {name}")
        provided[name] = value

    if provided and not manifest.inputs:
        raise InputError("Job declares no inputs")
    unknown = set(provided) - set(manifest.inputs)
    if unknown:
        raise InputError(f"Unknown input: {', '.join(sorted(unknown))}")

    resolved: dict[str, str] = {}
    for name, spec in manifest.inputs.items():
        resolved_value = provided.get(name, spec.default)
        if resolved_value is None:
            if spec.required:
                raise InputError(f"Missing required input: {name}")
            continue
        if spec.type == "int":
            try:
                int(resolved_value, 10)
            except ValueError as error:
                raise InputError(f"Input '{name}' must be an integer: {resolved_value}") from error
        elif spec.type == "file":
            path = Path(resolved_value).expanduser().resolve()
            if not path.is_file():
                raise InputError(f"Input '{name}' file not found: {resolved_value}")
            resolved_value = str(path)
        resolved[name] = resolved_value
    return resolved


def resolve_secrets(manifest: JobManifest) -> list[str]:
    """Ensure each declared secret name is present and non-empty in ``os.environ``.

    Returns the declared names (declaration order) for evidence. Does not
    copy values into any structure the kernel serializes.
    """
    names = list(manifest.secrets)
    if not names:
        return []

    missing: list[str] = []
    for name in names:
        value = os.environ.get(name)
        if value is None or value == "":
            missing.append(name)
    if missing:
        raise SecretError(f"Missing secret(s): {', '.join(missing)}")
    return names
