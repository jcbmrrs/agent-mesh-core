import pytest

from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.dispatch import EXPOSED_OPERATIONS, MeshDispatch


def test_dispatch_send_message_raises_raw_exception_not_wrapped(mesh_root):
    dispatch = MeshDispatch(mesh_root)

    with pytest.raises(FileNotFoundError):
        dispatch.send_message("agent_a", "agent_b", "task.assigned", {})


def test_dispatch_acquire_lock_raises_raw_exception_for_invalid_name(mesh_root):
    dispatch = MeshDispatch(mesh_root)

    with pytest.raises(ValueError):
        dispatch.acquire_lock("agent_a", "../bad")


def test_dispatch_reuses_one_coordinator_per_agent_id(mesh_root):
    dispatch = MeshDispatch(mesh_root)

    assert dispatch.registry.get("agent_a") is dispatch.registry.get("agent_a")


def test_dispatch_health_check_creates_no_synthetic_agent_directory(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_a")
    dispatch = MeshDispatch(mesh_root)

    dispatch.health_check()

    agent_dirs = {path.name for path in (mesh_root / "agents").iterdir()}
    assert agent_dirs == {"agent_a"}


def test_exposed_operations_match_mcp_server_tool_names():
    from agent_mesh_core.mcp_server import EXPOSED_TOOL_NAMES

    assert EXPOSED_TOOL_NAMES == EXPOSED_OPERATIONS
