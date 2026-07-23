import json

import pytest

from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.coordinator import MAX_MESSAGE_BYTES
from conftest import FakeClock


def test_send_message_requires_existing_real_target_inbox(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_a")
    with pytest.raises(FileNotFoundError):
        sender.send_message("agent_b", "task.assigned", {})

    (mesh_root / "agents" / "agent_b").mkdir(parents=True)
    (mesh_root / "agents" / "agent_b" / "inbox").write_text("not-dir")
    with pytest.raises(NotADirectoryError):
        sender.send_message("agent_b", "task.assigned", {})


def test_send_message_rejects_symlink_target_inbox(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_a")
    real = mesh_root / "real_inbox"
    real.mkdir()
    (mesh_root / "agents" / "agent_b").mkdir(parents=True)
    (mesh_root / "agents" / "agent_b" / "inbox").symlink_to(real, target_is_directory=True)

    with pytest.raises(NotADirectoryError):
        sender.send_message("agent_b", "task.assigned", {})


def test_send_message_writes_versioned_envelope(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_a", clock=FakeClock())
    AgentMeshCoordinator(mesh_root, "agent_b", clock=FakeClock())

    envelope = sender.send_message("agent_b", "task.assigned", {"task": "x"})

    files = list((mesh_root / "agents" / "agent_b" / "inbox").glob("*.json"))
    assert len(files) == 1
    assert json.loads(files[0].read_text()) == envelope
    assert envelope["schema_version"] == 1
    assert envelope["sender"] == "agent_a"
    assert envelope["target_agent_id"] == "agent_b"
    assert envelope["type"] == "task.assigned"
    assert envelope["body"] == {"task": "x"}


def test_send_message_ids_are_unique_with_identical_timestamps(mesh_root):
    clock = FakeClock()
    sender = AgentMeshCoordinator(mesh_root, "agent_a", clock=clock)
    AgentMeshCoordinator(mesh_root, "agent_b", clock=clock)

    first = sender.send_message("agent_b", "task.assigned", {})
    second = sender.send_message("agent_b", "task.assigned", {})

    assert first["created_at"] == second["created_at"]
    assert first["id"] != second["id"]
    assert len(list((mesh_root / "agents" / "agent_b" / "inbox").glob("*.json"))) == 2


@pytest.mark.parametrize("message_type", ["", "Task", "task assigned", "task/assigned", "a" * 65])
def test_send_message_validates_message_type(mesh_root, message_type):
    sender = AgentMeshCoordinator(mesh_root, "agent_a")
    AgentMeshCoordinator(mesh_root, "agent_b")

    with pytest.raises(ValueError):
        sender.send_message("agent_b", message_type, {})


@pytest.mark.parametrize("payload", ["body", ["body"]])
def test_send_message_requires_object_body(mesh_root, payload):
    sender = AgentMeshCoordinator(mesh_root, "agent_a")
    AgentMeshCoordinator(mesh_root, "agent_b")

    with pytest.raises(ValueError):
        sender.send_message("agent_b", "task.assigned", payload)


def test_send_message_rejects_oversized_envelope_before_writing(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_a")
    AgentMeshCoordinator(mesh_root, "agent_b")

    with pytest.raises(ValueError):
        sender.send_message("agent_b", "task.assigned", {"x": "é" * MAX_MESSAGE_BYTES})

    assert list((mesh_root / "agents" / "agent_b" / "inbox").glob("*.json")) == []


def test_send_message_non_serializable_payload_fails_cleanly(mesh_root):
    sender = AgentMeshCoordinator(mesh_root, "agent_a")
    AgentMeshCoordinator(mesh_root, "agent_b")

    with pytest.raises(TypeError):
        sender.send_message("agent_b", "task.assigned", {"bad": set()})

    assert list((mesh_root / "agents" / "agent_b" / "inbox").glob("*.json")) == []
