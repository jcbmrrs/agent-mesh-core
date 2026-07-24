from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_mesh_core.coordinator import AgentMeshCoordinator, LockHandle, MeshJsonWriter
from agent_mesh_core.inbox import acknowledge_claims as _acknowledge_claims
from agent_mesh_core.inbox import claim_inbox_messages as _claim_inbox_messages
from agent_mesh_core.rules_template import read_local_rules as _read_local_rules

# The runtime-facing operations every transport (MCP tools, the Ollama HTTP
# wrapper) exposes. Never atomic_write_json, recover_processing, or
# bootstrap_mesh - those stay operator/admin-only, per IMPLEMENTATION_PLAN_v2.md.
EXPOSED_OPERATIONS = frozenset(
    {
        "acquire_lock",
        "release_lock",
        "update_state",
        "send_message",
        "claim_inbox_messages",
        "acknowledge_claims",
        "read_local_rules",
        "health_check",
    }
)


class CoordinatorRegistry:
    """One AgentMeshCoordinator per agent_id, reused across calls.

    Constructing an AgentMeshCoordinator is idempotent (mkdir(exist_ok=True)),
    so a rare race between two concurrent first-calls for the same agent_id
    just discards one harmless extra instance - no lock needed.
    """

    def __init__(self, mesh_root: str | Path):
        self.mesh_root = Path(mesh_root)
        self._coordinators: dict[str, AgentMeshCoordinator] = {}

    def get(self, agent_id: str) -> AgentMeshCoordinator:
        coordinator = self._coordinators.get(agent_id)
        if coordinator is None:
            coordinator = AgentMeshCoordinator(self.mesh_root, agent_id)
            self._coordinators[agent_id] = coordinator
        return coordinator


class MeshDispatch:
    """Transport-agnostic dispatch layer over coordinator/inbox/rules_template.

    Every method here does exactly what the underlying agent_mesh_core
    function does and raises exactly what it raises (ValueError,
    FileNotFoundError, NotADirectoryError, FileExistsError, etc.) -
    unmapped. Mapping those exceptions to a transport's own error shape
    (fastmcp.exceptions.ToolError for MCP, an HTTP status code for the
    Ollama wrapper) is each transport's own job, done at its own boundary,
    not this layer's. This is what lets both transports share one
    implementation instead of duplicating it.
    """

    def __init__(self, mesh_root: str | Path):
        self.registry = CoordinatorRegistry(mesh_root)

    @property
    def mesh_root(self) -> Path:
        return self.registry.mesh_root

    def acquire_lock(
        self, agent_id: str, lock_name: str, timeout: float = 0, retry_interval: float = 0.1
    ) -> dict[str, str] | None:
        handle = self.registry.get(agent_id).acquire_lock(
            lock_name, timeout=timeout, retry_interval=retry_interval
        )
        if handle is None:
            return None
        return {"lock_name": handle.lock_name, "token": handle.token}

    def release_lock(self, agent_id: str, lock_name: str, token: str) -> None:
        self.registry.get(agent_id).release_lock(LockHandle(lock_name=lock_name, token=token))

    def update_state(
        self,
        agent_id: str,
        status: str,
        tasks: list[Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.registry.get(agent_id).update_state(status, tasks=tasks, extra_metadata=extra_metadata)

    def send_message(
        self, agent_id: str, target_agent_id: str, message_type: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self.registry.get(agent_id).send_message(target_agent_id, message_type, body)

    def claim_inbox_messages(self, agent_id: str, max_messages: int = 50) -> dict[str, Any]:
        result = _claim_inbox_messages(
            self.mesh_root,
            agent_id,
            max_messages=max_messages,
            coordinator=self.registry.get(agent_id),
        )
        return {
            "claimed": [
                {
                    "claim_id": item.claim_id,
                    "claim_token": item.claim_token,
                    "filename": item.filename,
                    "message": item.message,
                }
                for item in result.claimed
            ],
            "skipped": result.skipped,
            "ignored": result.ignored,
            "orphaned": result.orphaned,
        }

    def acknowledge_claims(
        self, agent_id: str, claims: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        return _acknowledge_claims(self.mesh_root, agent_id, claims)

    def read_local_rules(self) -> dict[str, Any]:
        return _read_local_rules(self.mesh_root)

    def health_check(self) -> dict[str, Any]:
        # health_check reports on the whole mesh, not any one agent - use the
        # identity-free writer so calling this never creates a synthetic
        # agent directory as a side effect.
        return MeshJsonWriter(self.mesh_root).health_check()
