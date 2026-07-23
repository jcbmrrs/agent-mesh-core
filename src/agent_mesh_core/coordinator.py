from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_mesh_core.names import validate_name

MESSAGE_SCHEMA_VERSION = 1
MAX_MESSAGE_BYTES = 256 * 1024


@dataclass(frozen=True)
class LockHandle:
    lock_name: str
    token: str


class _RealClock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)
    time = staticmethod(time.time)


class MeshJsonWriter:
    def __init__(self, mesh_root_path: str | Path):
        self.mesh_root = Path(mesh_root_path)
        self.mesh_root.mkdir(parents=True, exist_ok=True)

    def _assert_under_mesh_no_symlinks(self, target_file_path: Path) -> Path:
        target = Path(target_file_path)
        if not target.is_absolute():
            target = self.mesh_root / target
        mesh_abs = Path(os.path.abspath(self.mesh_root))
        target_abs = Path(os.path.abspath(target))
        try:
            target_abs.relative_to(mesh_abs)
        except ValueError as exc:
            raise ValueError(f"target path {target_file_path!r} is outside mesh root") from exc

        current = mesh_abs
        for part in target_abs.relative_to(mesh_abs).parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError(f"target path {target_file_path!r} contains symlink component")

        mesh_resolved = mesh_abs.resolve(strict=False)
        target_resolved = target.resolve(strict=False)
        try:
            target_resolved.relative_to(mesh_resolved)
        except ValueError as exc:
            raise ValueError(f"target path {target_file_path!r} is outside mesh root") from exc
        return target_resolved

    def atomic_write_json(self, target_file_path: str | Path, data: Any) -> None:
        target = self._assert_under_mesh_no_symlinks(Path(target_file_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        fd: int | None = None
        tmp_name: str | None = None
        try:
            fd, tmp_name = tempfile.mkstemp(prefix=".tmp_", suffix=".json", dir=target.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fd = None
                json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, target)
            self._fsync_parent_best_effort(target.parent)
        except Exception as exc:
            if fd is not None:
                os.close(fd)
            if tmp_name is not None:
                try:
                    os.unlink(tmp_name)
                except FileNotFoundError:
                    pass
            if isinstance(exc, OSError):
                raise OSError(f"atomic write failed for {target}") from exc
            raise

    def _fsync_parent_best_effort(self, directory: Path) -> None:
        try:
            dir_fd = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            try:
                os.fsync(dir_fd)
            except OSError:
                pass
        finally:
            os.close(dir_fd)


class AgentMeshCoordinator(MeshJsonWriter):
    def __init__(self, mesh_root_path: str | Path, agent_id: str, clock: Any | None = None):
        self.agent_id = validate_name(agent_id)
        super().__init__(mesh_root_path)
        self.clock = clock or _RealClock()
        (self.mesh_root / "agents" / self.agent_id / "inbox").mkdir(parents=True, exist_ok=True)
        (self.mesh_root / "locks").mkdir(parents=True, exist_ok=True)

    def _lock_dir(self, lock_name: str) -> Path:
        return self.mesh_root / "locks" / validate_name(lock_name)

    def _write_lock_token(self, token_file: Path, token: str) -> None:
        token_file.write_text(token, encoding="utf-8")

    def acquire_lock(
        self, lock_name: str, timeout: float = 0, retry_interval: float = 0.1
    ) -> LockHandle | None:
        lock_dir = self._lock_dir(lock_name)
        deadline = self.clock.monotonic() + max(timeout, 0)
        while True:
            try:
                os.mkdir(lock_dir)
            except FileExistsError:
                if self.clock.monotonic() >= deadline:
                    return None
                self.clock.sleep(retry_interval)
                continue

            token = secrets.token_hex(16)
            try:
                self._write_lock_token(lock_dir / "owner.token", token)
            except Exception:
                try:
                    os.rmdir(lock_dir)
                except OSError:
                    pass
                if self.clock.monotonic() >= deadline:
                    return None
                self.clock.sleep(retry_interval)
                continue
            return LockHandle(validate_name(lock_name), token)

    def release_lock(self, handle: LockHandle) -> None:
        lock_name = validate_name(handle.lock_name)
        lock_dir = self.mesh_root / "locks" / lock_name
        token_file = lock_dir / "owner.token"
        try:
            token = token_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        if token != handle.token:
            return
        try:
            os.remove(token_file)
        except FileNotFoundError:
            return
        os.rmdir(lock_dir)

    def update_state(
        self,
        status: str,
        tasks: list[Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "agent_id": self.agent_id,
            "timestamp": self.clock.time(),
            "status": status,
            "active_tasks": [] if tasks is None else tasks,
            "metadata": {} if extra_metadata is None else extra_metadata,
        }
        self.atomic_write_json(self.mesh_root / "agents" / self.agent_id / "state.json", payload)

    def send_message(
        self, target_agent_id: str, message_type: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        target_agent_id = validate_name(target_agent_id)
        self._validate_message_type(message_type)
        if not isinstance(payload, dict):
            raise ValueError("message body must be a JSON object")

        inbox = self.mesh_root / "agents" / target_agent_id / "inbox"
        if inbox.is_symlink():
            raise NotADirectoryError(f"target inbox is a symlink: {inbox}")
        if not inbox.exists():
            raise FileNotFoundError(f"target inbox does not exist: {inbox}")
        if not inbox.is_dir():
            raise NotADirectoryError(f"target inbox is not a directory: {inbox}")

        message_id = uuid.uuid4().hex
        envelope = {
            "schema_version": MESSAGE_SCHEMA_VERSION,
            "id": message_id,
            "created_at": self.clock.time(),
            "sender": self.agent_id,
            "target_agent_id": target_agent_id,
            "type": message_type,
            "body": payload,
        }
        serialized = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(serialized) > MAX_MESSAGE_BYTES:
            raise ValueError(f"message envelope exceeds {MAX_MESSAGE_BYTES} bytes")

        filename = f"{message_id}.json"
        self.atomic_write_json(inbox / filename, envelope)
        return envelope

    @staticmethod
    def _validate_message_type(message_type: str) -> None:
        import re

        if not isinstance(message_type, str):
            raise ValueError("message type must be a string")
        if not message_type or len(message_type) > 64:
            raise ValueError("message type must be non-empty and <=64 characters")
        if not re.fullmatch(r"[a-z0-9._-]+", message_type):
            raise ValueError(f"invalid message type {message_type!r}")

    def health_check(self) -> dict[str, Any]:
        from agent_mesh_core.inbox import claim_age_seconds, inspect_claim_shape

        agents = []
        agents_dir = self.mesh_root / "agents"
        if agents_dir.exists():
            for agent_dir in sorted([path for path in agents_dir.iterdir() if path.is_dir()]):
                processing = agent_dir / "inbox" / ".processing"
                claims = []
                if processing.exists():
                    claim_dirs = sorted([path for path in processing.iterdir() if path.is_dir()])
                    for claim_dir in claim_dirs:
                        shape, message, sidecar = inspect_claim_shape(claim_dir)
                        claims.append(
                            {
                                "claim_id": claim_dir.name,
                                "shape": shape,
                                "age_seconds": claim_age_seconds(
                                    shape, claim_dir, message, sidecar
                                ),
                            }
                        )
                agents.append({"agent_id": agent_dir.name, "processing_claims": claims})

        locks = []
        locks_dir = self.mesh_root / "locks"
        if locks_dir.exists():
            for lock_dir in sorted([path for path in locks_dir.iterdir() if path.is_dir()]):
                shape = "token-present" if (lock_dir / "owner.token").exists() else "token-missing"
                locks.append(
                    {
                        "lock_name": lock_dir.name,
                        "shape": shape,
                        "age_seconds": max(0.0, time.time() - lock_dir.stat().st_mtime),
                    }
                )

        return {
            "status": "ok",
            "mesh_root": str(self.mesh_root),
            "agents": agents,
            "locks": locks,
        }
