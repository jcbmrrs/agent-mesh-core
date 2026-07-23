import json

import pytest

from agent_mesh_core import AgentMeshCoordinator
from agent_mesh_core.rules_template import (
    build_local_rules,
    read_local_rules,
    write_local_rules_template,
)


def test_default_rules_have_required_keys_and_exclusions():
    rules = build_local_rules()

    assert {"schema_version", "network_context", "model_overrides", "file_tree_exclusions"} <= set(
        rules
    )
    for pattern in [".git", "__pycache__", ".venv", "node_modules"]:
        assert pattern in rules["file_tree_exclusions"]


def test_deep_merge_overrides_preserves_defaults_and_takes_precedence():
    rules = build_local_rules(
        {
            "network_context": {"transport": "custom"},
            "model_overrides": {"agent_a": {"model": "x"}},
        }
    )

    assert rules["network_context"]["transport"] == "custom"
    assert rules["network_context"]["mesh_root_writer"] == "mac_mini_only"
    assert rules["model_overrides"] == {"agent_a": {"model": "x"}}


def test_write_local_rules_refuses_and_force_overwrites(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_mac_mini")
    write_local_rules_template(mesh_root, coordinator=coordinator)

    with pytest.raises(FileExistsError):
        write_local_rules_template(mesh_root, coordinator=coordinator)

    write_local_rules_template(
        mesh_root,
        overrides={"network_context": {"transport": "forced"}},
        force=True,
        coordinator=coordinator,
    )
    assert read_local_rules(mesh_root)["network_context"]["transport"] == "forced"


def test_write_local_rules_delegates_to_atomic_write_json(monkeypatch, mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_mac_mini")
    seen = {}

    def spy(path, data):
        seen["path"] = path
        seen["data"] = data

    monkeypatch.setattr(coordinator, "atomic_write_json", spy)

    write_local_rules_template(mesh_root, coordinator=coordinator)

    assert seen["path"] == mesh_root / "config" / "local_rules.json"
    assert seen["data"]["schema_version"] == 1


def test_read_local_rules_round_trip_and_missing(mesh_root):
    coordinator = AgentMeshCoordinator(mesh_root, "agent_mac_mini")
    rules = write_local_rules_template(mesh_root, coordinator=coordinator)

    assert read_local_rules(mesh_root) == rules

    with pytest.raises(FileNotFoundError):
        read_local_rules(mesh_root / "missing")


def test_read_local_rules_raises_on_malformed_json(mesh_root):
    target = mesh_root / "config" / "local_rules.json"
    target.parent.mkdir(parents=True)
    target.write_text("{")

    with pytest.raises(json.JSONDecodeError):
        read_local_rules(mesh_root)
