"""Disk-first complete + evidence outbox. Delete only after the hub accepts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from coreme_agent.hub import CompletePayload, HubClient, HubClientError


@dataclass
class OutboxItem:
    attempt_id: str
    assignment_id: str
    complete: CompletePayload
    complete_sent: bool
    evidence_path: Path | None
    root: Path


def item_dir(outbox_root: str | Path, attempt_id: str) -> Path:
    return Path(outbox_root) / attempt_id


def write_outbox(
    outbox_root: str | Path,
    *,
    assignment_id: str,
    attempt_id: str,
    complete: CompletePayload,
    evidence: bytes | None = None,
) -> OutboxItem:
    root = item_dir(outbox_root, attempt_id)
    root.mkdir(parents=True, exist_ok=True)
    ev_path: Path | None = None
    if evidence:
        ev_path = root / "evidence.zip"
        ev_path.write_bytes(evidence)
    payload = {
        "assignment_id": assignment_id,
        "attempt_id": attempt_id,
        "complete": complete.to_dict(),
        "complete_sent": False,
        "has_evidence": ev_path is not None,
    }
    (root / "payload.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return OutboxItem(
        attempt_id=attempt_id,
        assignment_id=assignment_id,
        complete=complete,
        complete_sent=False,
        evidence_path=ev_path,
        root=root,
    )


def load_pending(outbox_root: str | Path) -> list[OutboxItem]:
    base = Path(outbox_root)
    if not base.is_dir():
        return []
    items: list[OutboxItem] = []
    for child in sorted(base.iterdir()):
        payload_path = child / "payload.json"
        if not payload_path.is_file():
            continue
        raw = json.loads(payload_path.read_text(encoding="utf-8"))
        ev = child / "evidence.zip"
        items.append(
            OutboxItem(
                attempt_id=str(raw["attempt_id"]),
                assignment_id=str(raw["assignment_id"]),
                complete=CompletePayload.from_dict(dict(raw["complete"])),
                complete_sent=bool(raw.get("complete_sent")),
                evidence_path=ev if ev.is_file() else None,
                root=child,
            )
        )
    return items


def delete_outbox(item: OutboxItem) -> None:
    payload = item.root / "payload.json"
    if payload.is_file():
        payload.unlink()
    if item.evidence_path is not None and item.evidence_path.is_file():
        item.evidence_path.unlink()
    if item.root.is_dir():
        for leftover in item.root.iterdir():
            leftover.unlink()
        item.root.rmdir()


def mark_complete_sent(item: OutboxItem) -> None:
    path = item.root / "payload.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["complete_sent"] = True
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    item.complete_sent = True


def flush_item(client: HubClient, item: OutboxItem) -> None:
    try:
        if not item.complete_sent:
            client.complete(
                item.assignment_id,
                attempt_id=item.attempt_id,
                status=item.complete.status,
                run_id=item.complete.run_id,
                exit_code=item.complete.exit_code,
                summary=item.complete.summary,
                fail=item.complete.fail,
                log_tail=item.complete.log_tail,
            )
            mark_complete_sent(item)
        if item.evidence_path is not None:
            client.put_evidence(
                item.assignment_id,
                attempt_id=item.attempt_id,
                payload=item.evidence_path.read_bytes(),
            )
        delete_outbox(item)
    except HubClientError as exc:
        if exc.status == 409:
            delete_outbox(item)
            return
        raise


def flush_outbox(client: HubClient, outbox_root: str | Path) -> None:
    for item in load_pending(outbox_root):
        flush_item(client, item)
