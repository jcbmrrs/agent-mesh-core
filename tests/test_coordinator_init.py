import pytest

from agent_mesh_core import AgentMeshCoordinator


def test_init_creates_agent_inbox_and_locks(mesh_root):
    AgentMeshCoordinator(mesh_root, "agent_mac_mini")

    assert (mesh_root / "agents" / "agent_mac_mini" / "inbox").is_dir()
    assert (mesh_root / "locks").is_dir()


def test_init_rejects_invalid_agent_id_before_touching_filesystem(mesh_root):
    with pytest.raises(ValueError):
        AgentMeshCoordinator(mesh_root, "../agent")

    assert not mesh_root.exists()
