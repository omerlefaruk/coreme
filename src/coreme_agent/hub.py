"""HTTP client for the hub claim loop, blob pull, and evidence upload."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from coreme_agent.store import Assignment


class HubClientError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"hub {status}: {message}")


@dataclass(frozen=True)
class ClaimedWork:
    id: str
    content_hash: str
    blob_url: str
    size_bytes: int | None
    inputs: dict[str, str]
    secret_names: list[str]
    batch_id: str | None
    lease_seconds: int
    attempt_id: str

    def as_assignment(self, release_path: str) -> Assignment:
        return Assignment(
            id=self.id,
            release_path=release_path,
            inputs=self.inputs,
            status="running",
            created_at="",
            batch_id=self.batch_id,
            attempt_id=self.attempt_id,
        )


class HubClient:
    def __init__(self, base_url: str, token: str, machine_id: str) -> None:
        self.base = base_url.rstrip("/")
        self.token = token
        self.machine_id = machine_id

    def heartbeat(
        self,
        *,
        tags: list[str],
        status: str = "idle",
        agent_version: str | None = None,
        running_assignment_id: str | None = None,
    ) -> None:
        self._request(
            "POST",
            "/v1/machines/heartbeat",
            {
                "machine_id": self.machine_id,
                "tags": tags,
                "status": status,
                "agent_version": agent_version,
                "running_assignment_id": running_assignment_id,
            },
        )

    def claim(self) -> ClaimedWork | None:
        status, body = self._request("POST", "/v1/assignments/claim", {})
        if status == 204 or body is None:
            return None
        if not isinstance(body, dict):
            raise HubClientError(status, "claim did not return an object")
        release = body.get("release")
        if not isinstance(release, dict):
            raise HubClientError(status, "claim is missing release")
        content_hash = str(release.get("content_hash") or "")
        blob_url = str(release.get("blob_url") or "")
        if not content_hash or not blob_url:
            raise HubClientError(status, "claim is missing release hash or blob_url")
        inputs = body.get("inputs") or {}
        if not isinstance(inputs, dict):
            raise HubClientError(status, "inputs must be an object")
        secrets = body.get("secret_names") or []
        if not isinstance(secrets, list):
            raise HubClientError(status, "secret_names must be a list")
        attempt_id = str(body["attempt_id"]) if body.get("attempt_id") else ""
        if not attempt_id:
            raise HubClientError(status, "claim is missing attempt_id")
        size = release.get("size_bytes")
        return ClaimedWork(
            id=str(body["id"]),
            content_hash=content_hash,
            blob_url=blob_url,
            size_bytes=int(size) if isinstance(size, int) else None,
            inputs={str(k): str(v) for k, v in inputs.items()},
            secret_names=[str(s) for s in secrets],
            batch_id=str(body["batch_id"]) if body.get("batch_id") else None,
            lease_seconds=int(body.get("lease_seconds") or 900),
            attempt_id=attempt_id,
        )

    def renew(self, assignment_id: str, *, attempt_id: str) -> dict[str, Any]:
        _, body = self._request(
            "POST",
            f"/v1/assignments/{assignment_id}/renew",
            {"attempt_id": attempt_id},
        )
        if not isinstance(body, dict):
            return {}
        return body

    def complete(
        self,
        assignment_id: str,
        *,
        attempt_id: str,
        status: str,
        run_id: str | None = None,
        exit_code: int | None = None,
        summary: dict[str, Any] | None = None,
        fail: dict[str, Any] | None = None,
        log_tail: str | None = None,
    ) -> dict[str, Any]:
        _, body = self._request(
            "POST",
            f"/v1/assignments/{assignment_id}/complete",
            {
                "attempt_id": attempt_id,
                "status": status,
                "run_id": run_id,
                "exit_code": exit_code,
                "summary": summary,
                "fail": fail,
                "log_tail": log_tail,
            },
        )
        if not isinstance(body, dict):
            return {}
        return body

    def download(self, blob_url: str) -> bytes:
        url = blob_url
        if not url.startswith("http://") and not url.startswith("https://"):
            url = self.base + "/" + url.lstrip("/")
        return self._request_bytes("GET", url, absolute=True)

    def put_evidence(
        self,
        assignment_id: str,
        *,
        attempt_id: str,
        payload: bytes,
    ) -> dict[str, Any]:
        path = f"/v1/assignments/{assignment_id}/evidence?attempt_id={quote(attempt_id)}"
        status, body = self._request_bytes_json(
            "POST",
            path,
            payload,
            content_type="application/zip",
        )
        if not isinstance(body, dict):
            return {"status": status}
        return body

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                code = resp.status
                if code == 204 or not raw:
                    return code, None
                return code, json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message = raw
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("error"):
                    message = str(parsed["error"])
            except json.JSONDecodeError:
                pass
            raise HubClientError(exc.code, message) from exc

    def _request_bytes(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        *,
        content_type: str = "application/zip",
        absolute: bool = False,
    ) -> bytes:
        url = path if absolute else self.base + path
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/zip, application/json",
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message = raw
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("error"):
                    message = str(parsed["error"])
            except json.JSONDecodeError:
                pass
            raise HubClientError(exc.code, message) from exc

    def _request_bytes_json(
        self,
        method: str,
        path: str,
        data: bytes,
        *,
        content_type: str,
    ) -> tuple[int, Any]:
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": content_type,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                if not raw:
                    return resp.status, None
                return resp.status, json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            message = raw
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("error"):
                    message = str(parsed["error"])
            except json.JSONDecodeError:
                pass
            raise HubClientError(exc.code, message) from exc
