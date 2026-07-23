import json
import os

import pytest

from agent_mesh_core import AgentMeshCoordinator


def test_atomic_write_json_writes_and_creates_parent(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")

    coordinator.atomic_write_json(mesh_root / "nested" / "state.json", {"a": 1})

    assert json.loads((mesh_root / "nested" / "state.json").read_text()) == {"a": 1}


def test_atomic_write_json_rejects_outside_mesh(mesh_root, tmp_path):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")

    with pytest.raises(ValueError):
        coordinator.atomic_write_json(tmp_path / "outside.json", {"a": 1})


def test_atomic_write_json_rejects_symlink_component(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")
    real_dir = mesh_root / "real"
    real_dir.mkdir()
    (mesh_root / "link").symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(ValueError):
        coordinator.atomic_write_json(mesh_root / "link" / "x.json", {"a": 1})
    assert not (real_dir / "x.json").exists()


def test_replace_failure_cleans_temp_and_leaves_target(monkeypatch, mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")
    target = mesh_root / "state.json"
    target.write_text('{"old":true}')

    def boom(_src, _dst):
        raise OSError("replace failed")

    monkeypatch.setattr("agent_mesh_core.coordinator.os.replace", boom)

    with pytest.raises(OSError):
        coordinator.atomic_write_json(target, {"new": True})

    assert json.loads(target.read_text()) == {"old": True}
    assert list(mesh_root.glob(".tmp_*")) == []


def test_non_serializable_payload_leaves_no_temp_or_target(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")
    target = mesh_root / "bad.json"

    with pytest.raises(TypeError):
        coordinator.atomic_write_json(target, {"bad": set()})

    assert not target.exists()
    assert list(mesh_root.glob(".tmp_*")) == []


def test_parent_dir_fsync_error_is_swallowed(monkeypatch, mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_a")
    original_fsync = os.fsync
    calls = 0

    def fsync_spy(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("dir fsync unsupported")
        return original_fsync(fd)

    monkeypatch.setattr("agent_mesh_core.coordinator.os.fsync", fsync_spy)

    coordinator.atomic_write_json(mesh_root / "state.json", {"ok": True})

    assert json.loads((mesh_root / "state.json").read_text()) == {"ok": True}
