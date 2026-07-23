import json

import pytest

from agent_mesh_core import AgentMeshCoordinator
from conftest import FakeClock


def test_update_state_payload_shape_and_defaults(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a", clock=FakeClock())

    coordinator.update_state("idle")

    payload = json.loads((mesh_root / "agents" / "agent_a" / "state.json").read_text())
    assert payload == {
        "agent_id": "agent_a",
        "timestamp": 1000.0,
        "status": "idle",
        "active_tasks": [],
        "metadata": {},
    }


def test_update_state_passes_tasks_and_metadata(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a", clock=FakeClock())

    coordinator.update_state("busy", tasks=["task-1"], extra_metadata={"host": "mini"})

    payload = json.loads((mesh_root / "agents" / "agent_a" / "state.json").read_text())
    assert payload["active_tasks"] == ["task-1"]
    assert payload["metadata"] == {"host": "mini"}


def test_update_state_delegates_to_atomic_write_json(monkeypatch, mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")
    seen = {}

    def spy(path, data):
        seen["path"] = path
        seen["data"] = data

    monkeypatch.setattr(coordinator, "atomic_write_json", spy)

    coordinator.update_state("idle", extra_metadata={"x": 1})

    assert seen["path"] == mesh_root / "agents" / "agent_a" / "state.json"
    assert seen["data"]["metadata"] == {"x": 1}


def test_update_state_non_serializable_metadata_fails_cleanly(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")

    with pytest.raises(TypeError):
        coordinator.update_state("idle", extra_metadata={"bad": set()})

    assert list((mesh_root / "agents" / "agent_a").glob(".tmp_*")) == []
