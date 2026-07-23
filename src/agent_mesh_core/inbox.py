from __future__ import annotations

import argparse
import json
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_mesh_core.coordinator import AgentMeshCoordinator
from agent_mesh_core.names import validate_claim_id, validate_name

MAX_CLAIM_BATCH_SIZE = 50
MAX_CLAIM_ID_COLLISION_RETRIES = 10


@dataclass
class ClaimedMessage:
    claim_id: str
    claim_token: str
    filename: str
    message: dict[str, Any]


@dataclass
class InboxScanResult:
    claimed: list[ClaimedMessage] = field(default_factory=list)
    skipped: list[dict[str, str]] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    orphaned: list[dict[str, str]] = field(default_factory=list)
    ack_results: list[dict[str, str]] = field(default_factory=list)


def _processing_dir(mesh_root: Path, agent_id: str) -> Path:
    return mesh_root / "agents" / validate_name(agent_id) / "inbox" / ".processing"


def _inbox_dir(mesh_root: Path, agent_id: str) -> Path:
    return mesh_root / "agents" / validate_name(agent_id) / "inbox"


def _new_claim_id() -> str:
    return uuid.uuid4().hex


def _validate_max_messages(max_messages: int) -> None:
    if not isinstance(max_messages, int) or isinstance(max_messages, bool):
        raise ValueError("max_messages must be an integer")
    if max_messages < 1 or max_messages > MAX_CLAIM_BATCH_SIZE:
        raise ValueError(f"max_messages must be between 1 and {MAX_CLAIM_BATCH_SIZE}")


def claim_inbox_messages(
    mesh_root: str | Path,
    agent_id: str,
    max_messages: int = MAX_CLAIM_BATCH_SIZE,
    coordinator: AgentMeshCoordinator | None = None,
) -> InboxScanResult:
    _validate_max_messages(max_messages)
    mesh_root = Path(mesh_root)
    agent_id = validate_name(agent_id)
    inbox = _inbox_dir(mesh_root, agent_id)
    processing = inbox / ".processing"
    invalid = inbox / ".invalid"
    processing.mkdir(parents=True, exist_ok=True)
    invalid.mkdir(parents=True, exist_ok=True)
    writer = coordinator or AgentMeshCoordinator(mesh_root, agent_id)
    result = InboxScanResult()

    eligible = []
    for path in sorted(inbox.iterdir(), key=lambda p: p.name):
        if path.name in {".processing", ".invalid"}:
            continue
        if path.name.startswith(".tmp_") or path.name.startswith("."):
            result.ignored.append(path.name)
            continue
        if not path.is_file():
            result.ignored.append(path.name)
            continue
        eligible.append(path)

    for source in eligible[:max_messages]:
        try:
            message = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(message, dict):
                raise ValueError("message JSON is not an object")
        except Exception as exc:
            dest = invalid / source.name
            if dest.exists():
                raise FileExistsError(f"invalid-message destination exists: {dest}") from exc
            try:
                os.rename(source, dest)
            except FileNotFoundError:
                continue
            result.skipped.append({"filename": source.name, "reason": "malformed"})
            continue

        claim_dir = _create_claim_dir(processing)
        dest = claim_dir / source.name
        try:
            os.rename(source, dest)
        except FileNotFoundError:
            try:
                os.rmdir(claim_dir)
            except OSError:
                pass
            continue

        claim_token = secrets.token_hex(16)
        sidecar = dest.with_name(dest.name + ".claim.json")
        sidecar_payload = {
            "claimant_agent_id": agent_id,
            "claimed_at": writer.clock.time(),
            "claim_token": claim_token,
        }
        try:
            writer.atomic_write_json(sidecar, sidecar_payload)
        except Exception:
            result.orphaned.append(
                {
                    "claim_id": claim_dir.name,
                    "filename": source.name,
                    "reason": "sidecar-write-failed",
                }
            )
            continue
        result.claimed.append(
            ClaimedMessage(
                claim_id=claim_dir.name,
                claim_token=claim_token,
                filename=source.name,
                message=message,
            )
        )
    return result


def _create_claim_dir(processing: Path) -> Path:
    for _ in range(MAX_CLAIM_ID_COLLISION_RETRIES):
        claim_id = _new_claim_id()
        try:
            os.mkdir(processing / claim_id)
        except FileExistsError:
            continue
        return processing / claim_id
    raise FileExistsError("could not allocate unique claim id")


def acknowledge_claims(
    mesh_root: str | Path, agent_id: str, claims: list[dict[str, str]]
) -> list[dict[str, Any]]:
    mesh_root = Path(mesh_root)
    processing = _processing_dir(mesh_root, agent_id)
    normalized = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("each claim must be a mapping")
        claim_id = validate_claim_id(claim.get("claim_id"))
        claim_token = claim.get("claim_token")
        if not isinstance(claim_token, str) or not claim_token:
            raise ValueError("claim_token must be a non-empty string")
        normalized.append((claim_id, claim_token))

    results = []
    for claim_id, claim_token in normalized:
        claim_dir = processing / claim_id
        if not claim_dir.exists():
            results.append({"claim_id": claim_id, "status": "not-found"})
            continue
        shape, message, sidecar = inspect_claim_shape(claim_dir)
        if shape != "complete" or sidecar is None or message is None:
            results.append({"claim_id": claim_id, "status": "unacknowledgeable", "shape": shape})
            continue
        sidecar_data = json.loads(sidecar.read_text(encoding="utf-8"))
        if sidecar_data.get("claim_token") != claim_token:
            results.append({"claim_id": claim_id, "status": "token-mismatch"})
            continue
        cleanup_errors = []
        try:
            try:
                message.unlink()
            except FileNotFoundError:
                pass
            try:
                sidecar.unlink()
            except FileNotFoundError:
                pass
            claim_dir.rmdir()
        except FileNotFoundError:
            pass
        except OSError as exc:
            cleanup_errors.append(str(exc))
        if cleanup_errors:
            results.append(
                {
                    "claim_id": claim_id,
                    "status": "partial",
                    "cleanup_errors": cleanup_errors,
                }
            )
        else:
            results.append({"claim_id": claim_id, "status": "acknowledged"})
    return results


def scan_and_clear_inbox(
    mesh_root: str | Path,
    agent_id: str,
    max_messages: int = MAX_CLAIM_BATCH_SIZE,
    coordinator: AgentMeshCoordinator | None = None,
) -> InboxScanResult:
    result = claim_inbox_messages(
        mesh_root, agent_id, max_messages=max_messages, coordinator=coordinator
    )
    result.ack_results = acknowledge_claims(
        mesh_root,
        agent_id,
        [{"claim_id": item.claim_id, "claim_token": item.claim_token} for item in result.claimed],
    )
    return result


def inspect_claim_shape(claim_dir: Path) -> tuple[str, Path | None, Path | None]:
    files = [path for path in claim_dir.iterdir() if path.is_file()]
    messages = [
        path for path in files if path.suffix == ".json" and not path.name.endswith(".claim.json")
    ]
    sidecars = [path for path in files if path.name.endswith(".claim.json")]
    message = messages[0] if messages else None
    sidecar = sidecars[0] if sidecars else None
    if message is None:
        return "empty", None, sidecar
    if sidecar is None:
        return "no-sidecar", message, None
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        validate_name(data["claimant_agent_id"])
        if not isinstance(data["claimed_at"], (int, float)):
            raise ValueError("invalid claimed_at")
        if not isinstance(data["claim_token"], str) or not data["claim_token"]:
            raise ValueError("invalid claim_token")
    except Exception:
        return "malformed-sidecar", message, sidecar
    return "complete", message, sidecar


def claim_age_seconds(
    shape: str, claim_dir: Path, message: Path | None, sidecar: Path | None
) -> float:
    now = time.time()
    if shape == "complete" and sidecar is not None:
        try:
            claimed_at = json.loads(sidecar.read_text(encoding="utf-8"))["claimed_at"]
            return max(0.0, now - float(claimed_at))
        except Exception:
            pass
    anchor = claim_dir if message is None else message
    return max(0.0, now - anchor.stat().st_mtime)


def recover_processing(
    mesh_root: str | Path,
    agent_id: str,
    older_than_seconds: float | None = None,
    claim_ids: list[str] | None = None,
    action: str | None = None,
) -> list[dict[str, Any]]:
    mesh_root = Path(mesh_root)
    agent_id = validate_name(agent_id)
    if action not in {None, "requeue", "quarantine"}:
        raise ValueError("action must be None, 'requeue', or 'quarantine'")
    normalized_claim_ids = None
    if claim_ids is not None:
        normalized_claim_ids = [validate_claim_id(claim_id) for claim_id in claim_ids]
    inbox = _inbox_dir(mesh_root, agent_id)
    processing = inbox / ".processing"
    if not processing.exists():
        return []
    candidates = (
        [processing / claim_id for claim_id in normalized_claim_ids]
        if normalized_claim_ids is not None
        else sorted([path for path in processing.iterdir() if path.is_dir()], key=lambda p: p.name)
    )

    results = []
    for claim_dir in candidates:
        claim_id = claim_dir.name
        if not claim_dir.exists():
            results.append({"claim_id": claim_id, "status": "not-found"})
            continue
        shape, message, sidecar = inspect_claim_shape(claim_dir)
        age = claim_age_seconds(shape, claim_dir, message, sidecar)
        selected = normalized_claim_ids is not None or (
            older_than_seconds is not None and age >= older_than_seconds
        )
        row: dict[str, Any] = {
            "claim_id": claim_id,
            "shape": shape,
            "age_seconds": age,
            "selected": selected,
            "action": action or "report",
        }
        if not selected or action is None:
            row["status"] = "reported" if selected else "not-selected"
            results.append(row)
            continue
        if message is None:
            try:
                claim_dir.rmdir()
            except OSError as exc:
                row["status"] = "partial"
                row["cleanup_errors"] = [str(exc)]
            else:
                row["status"] = "recovered"
            results.append(row)
            continue
        dest_dir = inbox if action == "requeue" else inbox / ".invalid"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / message.name
        if dest.exists():
            raise FileExistsError(f"recovery destination exists: {dest}")
        os.rename(message, dest)
        row["status"] = "recovered"
        row["destination"] = str(dest)
        cleanup_errors = []
        try:
            if sidecar is not None and sidecar.exists():
                sidecar.unlink()
            claim_dir.rmdir()
        except OSError as exc:
            cleanup_errors.append(str(exc))
            row["status"] = "partial"
        if cleanup_errors:
            row["cleanup_errors"] = cleanup_errors
        results.append(row)
    return results


def recover_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-mesh-recover-processing")
    parser.add_argument("--mesh-root", required=True)
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--older-than-seconds", type=float)
    parser.add_argument("--claim-id", action="append", dest="claim_ids")
    parser.add_argument("--action", choices=["report", "requeue", "quarantine"], default="report")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    action = None if args.dry_run or args.action == "report" else args.action
    result = recover_processing(
        mesh_root=args.mesh_root,
        agent_id=args.agent_id,
        older_than_seconds=args.older_than_seconds,
        claim_ids=args.claim_ids,
        action=action,
    )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(recover_main())
