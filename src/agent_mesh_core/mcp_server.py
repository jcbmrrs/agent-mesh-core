from __future__ import annotations

import argparse
import functools
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from agent_mesh_core.dispatch import EXPOSED_OPERATIONS, MeshDispatch

# Kept as an alias: existing callers/tests import EXPOSED_TOOL_NAMES from
# this module specifically (MCP's own vocabulary for the exposed set).
EXPOSED_TOOL_NAMES = EXPOSED_OPERATIONS

# Exceptions MeshDispatch lets propagate unmapped for expected, caller-facing
# failures (bad input, missing resources, etc). Mapped to ToolError here, at
# the MCP-specific boundary, so the real reason reaches the client instead of
# FastMCP's generic masked message - see IMPLEMENTATION_PLAN_v2.md's "let it
# raise, map at the boundary" rule.
_MAPPED_EXCEPTIONS = (ValueError, FileNotFoundError, NotADirectoryError, FileExistsError)


def validate_mesh_root(mesh_root: str | Path) -> Path:
    path = Path(mesh_root)
    if not path.exists():
        raise ValueError(f"mesh root {path} does not exist")
    if not path.is_dir():
        raise ValueError(f"mesh root {path} is not a directory")
    if not os.access(path, os.W_OK | os.X_OK):
        raise ValueError(f"mesh root {path} is not writable")
    try:
        with tempfile.NamedTemporaryFile(prefix=".startup_check_", dir=path, delete=True):
            pass
    except OSError:
        raise ValueError(f"mesh root {path} is not writable")
    return path


def _map_tool_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except _MAPPED_EXCEPTIONS as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def build_server(mesh_root: str | Path) -> FastMCP:
    dispatch = MeshDispatch(mesh_root)
    mcp: FastMCP = FastMCP("agent-mesh-core")

    @mcp.tool(name="acquire_lock")
    @_map_tool_errors
    def acquire_lock_tool(
        agent_id: str, lock_name: str, timeout: float = 0, retry_interval: float = 0.1
    ) -> dict[str, str] | None:
        return dispatch.acquire_lock(
            agent_id, lock_name, timeout=timeout, retry_interval=retry_interval
        )

    @mcp.tool(name="release_lock")
    @_map_tool_errors
    def release_lock_tool(agent_id: str, lock_name: str, token: str) -> None:
        dispatch.release_lock(agent_id, lock_name, token)

    @mcp.tool(name="update_state")
    @_map_tool_errors
    def update_state_tool(
        agent_id: str,
        status: str,
        tasks: list[Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> None:
        dispatch.update_state(agent_id, status, tasks=tasks, extra_metadata=extra_metadata)

    @mcp.tool(name="send_message")
    @_map_tool_errors
    def send_message_tool(
        agent_id: str, target_agent_id: str, message_type: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return dispatch.send_message(agent_id, target_agent_id, message_type, body)

    @mcp.tool(name="claim_inbox_messages")
    @_map_tool_errors
    def claim_inbox_messages_tool(agent_id: str, max_messages: int = 50) -> dict[str, Any]:
        return dispatch.claim_inbox_messages(agent_id, max_messages=max_messages)

    @mcp.tool(name="acknowledge_claims")
    @_map_tool_errors
    def acknowledge_claims_tool(
        agent_id: str, claims: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        return dispatch.acknowledge_claims(agent_id, claims)

    @mcp.tool(name="read_local_rules")
    @_map_tool_errors
    def read_local_rules_tool() -> dict[str, Any]:
        return dispatch.read_local_rules()

    @mcp.tool(name="health_check")
    @_map_tool_errors
    def health_check_tool() -> dict[str, Any]:
        return dispatch.health_check()

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-mesh-mcp-server")
    parser.add_argument("--mesh-root", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    try:
        mesh_root = validate_mesh_root(args.mesh_root)
    except ValueError as exc:
        print(f"agent-mesh-mcp-server: {exc}", file=sys.stderr)
        return 2

    server = build_server(mesh_root)
    server.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
