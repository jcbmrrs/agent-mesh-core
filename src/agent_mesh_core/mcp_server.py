from __future__ import annotations

import argparse
import functools
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from agent_mesh_core.coordinator import AgentMeshCoordinator, LockHandle, MeshJsonWriter
from agent_mesh_core.inbox import acknowledge_claims as _acknowledge_claims
from agent_mesh_core.inbox import claim_inbox_messages as _claim_inbox_messages
from agent_mesh_core.rules_template import read_local_rules as _read_local_rules

# Exceptions the underlying coordinator/inbox/rules_template modules raise for
# expected, caller-facing failures (bad input, missing resources, etc). Mapped
# to ToolError so the real reason reaches the client instead of a generic
# masked message - see IMPLEMENTATION_PLAN_v2.md's "let it raise, map at the
# boundary" rule.
_MAPPED_EXCEPTIONS = (ValueError, FileNotFoundError, NotADirectoryError, FileExistsError)

EXPOSED_TOOL_NAMES = frozenset(
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

def _map_tool_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _MAPPED_EXCEPTIONS as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


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


def build_server(mesh_root: str | Path) -> FastMCP:
    registry = CoordinatorRegistry(mesh_root)
    mcp: FastMCP = FastMCP("agent-mesh-core")

    @mcp.tool(name="acquire_lock")
    @_map_tool_errors
    def acquire_lock_tool(
        agent_id: str, lock_name: str, timeout: float = 0, retry_interval: float = 0.1
    ) -> dict[str, str] | None:
        handle = registry.get(agent_id).acquire_lock(
            lock_name, timeout=timeout, retry_interval=retry_interval
        )
        if handle is None:
            return None
        return {"lock_name": handle.lock_name, "token": handle.token}

    @mcp.tool(name="release_lock")
    @_map_tool_errors
    def release_lock_tool(agent_id: str, lock_name: str, token: str) -> None:
        registry.get(agent_id).release_lock(LockHandle(lock_name=lock_name, token=token))

    @mcp.tool(name="update_state")
    @_map_tool_errors
    def update_state_tool(
        agent_id: str,
        status: str,
        tasks: list[Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        registry.get(agent_id).update_state(status, tasks=tasks, extra_metadata=extra_metadata)

    @mcp.tool(name="send_message")
    @_map_tool_errors
    def send_message_tool(
        agent_id: str, target_agent_id: str, message_type: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return registry.get(agent_id).send_message(target_agent_id, message_type, body)

    @mcp.tool(name="claim_inbox_messages")
    @_map_tool_errors
    def claim_inbox_messages_tool(agent_id: str, max_messages: int = 50) -> dict[str, Any]:
        result = _claim_inbox_messages(
            registry.mesh_root,
            agent_id,
            max_messages=max_messages,
            coordinator=registry.get(agent_id),
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

    @mcp.tool(name="acknowledge_claims")
    @_map_tool_errors
    def acknowledge_claims_tool(
        agent_id: str, claims: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        return _acknowledge_claims(registry.mesh_root, agent_id, claims)

    @mcp.tool(name="read_local_rules")
    @_map_tool_errors
    def read_local_rules_tool() -> dict[str, Any]:
        return _read_local_rules(registry.mesh_root)

    @mcp.tool(name="health_check")
    @_map_tool_errors
    def health_check_tool() -> dict[str, Any]:
        # health_check reports on the whole mesh, not any one agent - use the
        # identity-free writer so calling this tool never creates a synthetic
        # agent directory as a side effect.
        return MeshJsonWriter(registry.mesh_root).health_check()

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-mesh-mcp-server")
    parser.add_argument("--mesh-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    server = build_server(args.mesh_root)
    server.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
